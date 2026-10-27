"""Dataset and world-bundle exports.

Datasets contain only verified train/dev trajectories: what each actor saw
(role-visible observations and tool results) and the tool calls it made. They
never contain oracle checks, hidden state, provider credentials, or holdout
scenarios. World bundles split into a learner-facing bundle (train scenarios)
and a separately stored private evaluation bundle (dev/holdout + checks).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from ..redaction import redact_any
from ..config import settings
from ..db.models import Application, Artifact, Episode, Run, Scenario, World, WorldVersion, now
from ..db.session import session
from .context import JobContext


def _safe_name(value: str) -> str:
    if not value or value in (".", "..") or "/" in value or "\\" in value or "\0" in value:
        raise ValueError("unsafe archive file name")
    return value


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _artifact(ctx: JobContext, project_id: str, kind: str, name: str, path: Path, meta: dict[str, Any]) -> str:
    with session() as s:
        ctx.owned(s)
        art = Artifact(project_id=project_id, kind=kind, name=name, path=str(path), sha256=_sha(path), size=path.stat().st_size, meta=meta)
        s.add(art)
        s.flush()
        return art.id


def trajectories(episode: Episode) -> list[dict[str, Any]]:
    """One SFT example per actor that acted: its own conversation and tool catalog."""
    out = []
    for actor_id, actor in (episode.state or {}).get("actors", {}).items():
        transcript = [m for m in actor.get("transcript", []) if m.get("role") in ("system", "user", "assistant", "tool")]
        if not any(m.get("role") == "assistant" and m.get("tool_calls") for m in transcript):
            continue
        cleaned = []
        for m in transcript:
            m = {k: v for k, v in m.items() if k in ("role", "content", "tool_calls", "tool_call_id", "name")}
            if m.get("tool_calls"):
                m["tool_calls"] = [{"id": c["id"], "type": "function", "function": c["function"]} for c in m["tool_calls"]]
            cleaned.append(m)
        out.append({"actor": actor_id, "role": actor.get("role"), "messages": cleaned, "tools": actor.get("tools", [])})
    return redact_any(out)


def handle_dataset(ctx: JobContext) -> dict[str, Any]:
    ctx.check()
    p = ctx.payload
    splits = [sp for sp in p.get("splits", ["train"]) if sp in ("train", "dev")]
    rows: list[dict[str, Any]] = []
    sources: dict[str, Any] = {}
    with session() as s:
        ctx.owned(s)
        for rid in p["run_ids"]:
            run = s.get(Run, rid)
            assert run is not None and run.project_id == ctx.project_id
            wv = s.get(WorldVersion, run.world_version_id)
            sources[rid] = {"world_version_id": run.world_version_id, "world_content_hash": wv.content_hash if wv else None}
            q = select(Episode, Scenario).join(Scenario, Scenario.id == Episode.scenario_id).where(Episode.run_id == rid, Episode.status == "finished", Scenario.split.in_(splits))
            for ep, sc in s.execute(q).all():
                if p.get("verified_only", True) and ep.reward != 1:
                    continue
                for traj in trajectories(ep):
                    rows.append({**traj, "episode_id": ep.id, "scenario": sc.slug, "family": sc.family, "split": sc.split, "reward": ep.reward})
    dest = settings().artifacts_dir / ctx.project_id / "datasets"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{ctx.job_id}.jsonl"
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str) + "\n")
    meta = {"examples": len(rows), "episodes": len({r["episode_id"] for r in rows}), "splits": splits, "verified_only": p.get("verified_only", True), "sources": sources}
    art = _artifact(ctx, ctx.project_id, "dataset", path.name, path, meta)
    ctx.log("dataset.exported", f"{len(rows)} verified trajectories from {meta['episodes']} episodes", meta)
    return {"artifact_id": art, **meta}


def handle_bundle(ctx: JobContext) -> dict[str, Any]:
    ctx.check()
    p = ctx.payload
    with session() as s:
        ctx.owned(s)
        wv = s.get(WorldVersion, p["world_version_id"])
        assert wv is not None and wv.project_id == ctx.project_id
        world = s.get(World, wv.world_id)
        app = s.get(Application, world.application_id) if world else None
        scenarios = [(sc.split, sc.slug, sc.spec) for sc in s.scalars(select(Scenario).where(Scenario.world_version_id == wv.id, Scenario.status == "approved"))]
        data = {
            "manifest": wv.manifest, "capabilities": wv.capabilities, "provenance": wv.provenance, "content_hash": wv.content_hash,
            "secrets": wv.private.get("secrets", {}), "vars": wv.private.get("vars", {}), "snapshot": str(settings().data_path(wv.snapshot_dir)),
            "validation": {k: v for k, v in (wv.validation or {}).items() if k in ("isolation", "repairs")}, "version": wv.version,
            "name": world.name if world else "world", "policies": app.policies if app else "", "license_note": app.notes if app else "",
        }
    out_dir = settings().artifacts_dir / ctx.project_id / "bundles"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{p['world_version_id']}-{ctx.job_id}"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "world-bundle"
        (root / "scenarios" / "train").mkdir(parents=True)
        (root / "fixtures").mkdir()
        (root / "policies").mkdir()
        (root / "validation").mkdir()
        (root / "world.yaml").write_text(yaml.safe_dump({"version": data["version"], "content_hash": data["content_hash"], "manifest": data["manifest"]}, sort_keys=False))
        (root / "fixtures" / "seed-vars.json").write_text(json.dumps(data["vars"], indent=1))
        # Generated sandbox values baked into the snapshot (e.g. a database password).
        # They grant nothing outside the world; without them the snapshot cannot start.
        (root / "fixtures" / "sandbox-secrets.json").write_text(json.dumps(data["secrets"], indent=1))
        (root / "policies" / "owner-policies.md").write_text(data["policies"] or "(none supplied)\n")
        (root / "validation" / "capabilities.json").write_text(json.dumps(data["capabilities"], indent=1))
        (root / "validation" / "isolation.json").write_text(json.dumps(data["validation"], indent=1, default=str))
        for split, slug, spec in scenarios:
            if split == "train":
                (root / "scenarios" / "train" / f"{_safe_name(slug)}.json").write_text(json.dumps(spec, indent=1))
        (root / "provenance.json").write_text(json.dumps({**data["provenance"], "licence": data["license_note"], "exported_at": now().isoformat()}, indent=1, default=str))
        shutil.copytree(data["snapshot"], root / "snapshot")
        if p.get("include_images"):
            images = sorted({img for img in (data["provenance"].get("images") or {}).values()})
            ctx.log("bundle.images", f"saving {len(images)} images")
            subprocess.run(["docker", "save", "-o", str(root / "images.tar"), *images], check=True, timeout=3600)
        checksums = {str(f.relative_to(root)): _sha(f) for f in sorted(root.rglob("*")) if f.is_file()}
        (root / "checksums.json").write_text(json.dumps(checksums, indent=1))
        public = out_dir / f"{stem}-world-bundle.tar.gz"
        with tarfile.open(public, "w:gz") as tar:
            tar.add(root, arcname="world-bundle")
        priv_root = Path(tmp) / "private-evaluation-bundle"
        (priv_root / "holdout-scenarios").mkdir(parents=True)
        (priv_root / "dev-scenarios").mkdir()
        for split, slug, spec in scenarios:
            if split in ("dev", "holdout"):
                (priv_root / f"{split}-scenarios" / f"{_safe_name(slug)}.json").write_text(json.dumps(spec, indent=1))
        private = out_dir / f"{stem}-private-evaluation.tar.gz"
        with tarfile.open(private, "w:gz") as tar:
            tar.add(priv_root, arcname="private-evaluation-bundle")
    pub_id = _artifact(ctx, ctx.project_id, "world_bundle", public.name, public, {"world_version_id": p["world_version_id"], "train_scenarios": sum(1 for sp, *_ in scenarios if sp == "train")})
    priv_id = _artifact(ctx, ctx.project_id, "private_evaluation_bundle", private.name, private, {"world_version_id": p["world_version_id"], "visibility": "evaluators only"})
    return {"world_bundle": pub_id, "private_evaluation_bundle": priv_id}
