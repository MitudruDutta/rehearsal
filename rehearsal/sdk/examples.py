"""Exports what Rehearsal actually produced for an application into examples/<app>/.

Only published, validated output is written. Train scenarios are written in
full; dev and held-out scenarios are listed by title only, so publishing the
example does not leak the evaluation set. Run results come from finished runs.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from .client import Rehearsal

ROOT = Path.cwd()


def _safe_name(value: str) -> str:
    if not value or value in (".", "..") or "/" in value or "\\" in value or "\0" in value:
        raise ValueError("unsafe example file name")
    return value


def _catalog() -> dict[str, Any]:
    data = yaml.safe_load(files("rehearsal").joinpath("assets/catalog.yaml").read_text())
    return {a["name"]: a for a in data["applications"]}


def export_example(client: Rehearsal, world_version_id: str) -> dict[str, Any]:
    wv = client.worlds.version(world_version_id)
    manifest = wv["manifest"]
    app = _safe_name(manifest["name"])
    entry = _catalog().get(app, {})
    dest = ROOT / "examples" / app
    if not dest.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("example directory escapes the working directory")
    (dest / "scenarios" / "train").mkdir(parents=True, exist_ok=True)
    (dest / "runs").mkdir(exist_ok=True)
    scenarios = [s for s in client.worlds.scenarios(world_version_id) if s["status"] == "approved"]
    for s in scenarios:
        if s["split"] == "train":
            (dest / "scenarios" / "train" / f"{_safe_name(s['slug'])}.json").write_text(json.dumps(s["spec"], indent=1))
    validation = wv.get("validation") or {}
    (dest / "world.json").write_text(json.dumps({"version": wv["version"], "content_hash": wv["content_hash"], "manifest": manifest}, indent=1))
    (dest / "capabilities.json").write_text(json.dumps({"capabilities": wv["capabilities"], "isolation": validation.get("isolation"), "repairs": validation.get("repairs"), "rejected": validation.get("rejected")}, indent=1, default=str))
    runs = [r for r in client.get("/v1/runs") if r["world_version_id"] == world_version_id and r["status"] == "finished"]
    for r in runs:
        (dest / "runs" / f"{_safe_name(r['id'])}.json").write_text(json.dumps({"config": r["config"], "summary": r["summary"], "finished_at": r["finished_at"]}, indent=1, default=str))
    prov = wv.get("provenance") or {}
    tools = manifest.get("tools", [])
    by_split: dict[str, list[dict[str, Any]]] = {}
    for s in scenarios:
        by_split.setdefault(s["split"], []).append(s)
    lines = [
        f"# {app}",
        "",
        f"{entry.get('domain', '').capitalize()} application, {entry.get('license', 'licence: see upstream')}. Not written by the Rehearsal authors.",
        f"Role in testing: {'held out (never inspected while developing the compiler)' if entry.get('split') == 'holdout' else 'development application'}.",
        "",
        "## Source compiled",
        "",
        f"- Repository: {prov.get('url', entry.get('source', {}).get('url', ''))} at commit `{prov.get('commit', entry.get('source', {}).get('commit', ''))}`",
        *[f"- Image `{name}`: `{img}`" for name, img in (prov.get("images") or {}).items()],
        f"- World version {wv['version']}, content hash `{wv['content_hash']}`",
        f"- Compiler model chain: `{prov.get('compiler_chain', '')}`; model spend ${prov.get('spent_usd', 0) or 0:.2f}" + (f", {prov['tokens']:,} tokens" if prov.get("tokens") else ""),
        "",
        "## What the World Compiler produced",
        "",
        f"- {len(manifest.get('services', []))} services in an isolated network: " + ", ".join(f"`{s['name']}`" for s in manifest.get("services", [])),
        f"- {len(manifest.get('roles', []))} roles: " + ", ".join(f"`{r['name']}`" for r in manifest.get("roles", [])),
        f"- {len(tools)} agent tools ({sum(1 for t in tools if t['mutating'])} that change state)",
        f"- {len(scenarios)} validated scenarios: " + ", ".join(f"{len(v)} {k}" for k, v in sorted(by_split.items())),
        f"- {sum(1 for r in (validation.get('repairs') or []) if r.get('outcome') == 'repaired')} scenarios repaired by the compiler after failing validation; {len(validation.get('rejected') or {})} rejected",
        "",
        "## Scenarios",
        "",
        "| Scenario | Family | Split | Goal changes |",
        "|---|---|---|---|",
        *[f"| {s['spec']['title']} | {s['family']} | {s['split']} | {len(s['spec']['goals']) - 1} |" for s in sorted(scenarios, key=lambda x: (x["split"], x["slug"]))],
        "",
        "Train scenarios are in `scenarios/train/`. Dev and held-out scenarios are kept in the private evaluation bundle.",
        "",
        "## Tools",
        "",
        "| Tool | Operation | Roles |",
        "|---|---|---|",
        *[f"| `{t['name']}` | `{('GraphQL' if t.get('graphql') else t['method'])} {t['path']}` | {', '.join(t['roles'])} |" for t in tools],
        "",
        "## Results",
        "",
    ]
    if not runs:
        lines.append("No finished evaluations yet.")
    else:
        lines += ["| Run | Agent | Scenarios | Verified success | Episodes with rule violations | False completions | Recovered after faults |", "|---|---|---|---|---|---|---|"]
        for r in runs:
            for prof, s in (r["summary"] or {}).get("profiles", {}).items():
                o = s["overall"]
                rate = "–" if o.get("success_rate") is None else f"{round(o['success_rate'] * 100)}% ({o['successes']}/{o['finished']})"
                lines.append(f"| `{r['id']}` | {prof} | {', '.join(r['config'].get('splits') or [])} | {rate} | {o['hard_violation_episodes']} | {o['false_completions']} | {o['recovered']} |")
    (dest / "README.md").write_text("\n".join(lines) + "\n")
    row = {
        "application": app, "domain": entry.get("domain", ""), "license": entry.get("license", ""), "split": entry.get("split", "development"),
        "status": "published", "world_version": wv["version"], "scenarios": len(scenarios), "tools": len(tools),
        "repairs": sum(1 for r in (validation.get("repairs") or []) if r.get("outcome") == "repaired"),
        "spend_usd": prov.get("spent_usd"), "tokens": prov.get("tokens"),
    }
    index_path = ROOT / "examples" / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"applications": []}
    index["applications"] = [a for a in index["applications"] if a["application"] != app] + [row]
    index_path.write_text(json.dumps(index, indent=1))
    public = ROOT / "web" / "public" / "examples"
    public.mkdir(parents=True, exist_ok=True)
    (public / "index.json").write_text(json.dumps(index, indent=1))
    return row
