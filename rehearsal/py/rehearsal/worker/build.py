"""world_build job: runs the World Compiler and publishes an immutable version."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from ..compiler.pipeline import AppInput, BuildOptions, Compiler
from ..config import settings
from ..db import queue
from ..db.events import emit
from ..db.models import Application, Job, Scenario, WorldVersion, now
from ..db.session import session
from .context import JobContext
from .sources import materialize


def handle(ctx: JobContext) -> dict:
    p = ctx.payload
    with session() as s:
        ctx.owned(s)
        app = s.get(Application, p["application_id"])
        wv = s.get(WorldVersion, p["world_version_id"])
        assert app is not None and wv is not None
        app_row = {"id": app.id, "name": app.name, "source": dict(app.source), "images": dict(app.images), "policies": app.policies}
    source_dir, provenance = materialize(app_row["id"], app_row["source"])
    workdir = settings().data_dir / "worlds" / p["world_version_id"] / f"attempt-{ctx.attempt}"
    options = BuildOptions(**p.get("options", {}))
    def destroy_owned(inst):
        with session() as s:
            ctx.owned(s)
            inst.destroy()

    compiler = Compiler(
        app=AppInput(app_row["name"], source_dir, app_row["images"], app_row["policies"], {**provenance, "application_id": app_row["id"], "build_job": ctx.job_id}),
        checkpoint=ctx.checkpoint,
        workdir=workdir,
        chain=p.get("model") or settings().model_compiler,
        reasoner=p.get("model") or settings().model_reasoner,  # one model named for the build runs every role
        log=lambda t, m, d: ctx.log(t, m, d),
        save=ctx.save_checkpoint,
        heartbeat=ctx.check,
        add_cost=ctx.add_cost,
        options=options,
        destroy=destroy_owned,
        budget=ctx.budget,
        pause=ctx.request_pause,
    )
    try:
        pkg = compiler.run()
    except BaseException as exc:
        if not isinstance(exc, (queue.LeaseLost, queue.JobPaused, queue.Handover)) and p.get("keep_sandbox_on_failure") is not True:
            compiler.cleanup()
        raise
    publish(ctx, pkg, p)
    return {"world_version_id": p["world_version_id"], "scenarios": len(pkg["scenarios"]), "rejected": len(pkg["rejected"]), "content_hash": pkg["content_hash"]}


def publish(ctx: JobContext, pkg: dict, payload: dict) -> None:
    with session() as s:
        ctx.owned(s)
        wv = s.get(WorldVersion, payload["world_version_id"])
        assert wv is not None
        if wv.status == "published":
            return  # idempotent: a resumed job must not republish
        wv.manifest = pkg["manifest"]
        wv.private = {"secrets": pkg["secrets"], "vars": pkg["vars"]}
        wv.capabilities = pkg["capabilities"]
        wv.validation = {"reports": pkg["reports"], "repairs": pkg["repairs"], "rejected": pkg["rejected"], "isolation": pkg["isolation"], "inspection": pkg["inspection"], "research": pkg.get("research")}
        job_row = s.get(Job, ctx.job_id)
        wv.provenance = {**pkg["provenance"], "spent_usd": round(ctx.spent, 6), "tokens": job_row.tokens if job_row else None}
        wv.content_hash = pkg["content_hash"]
        wv.snapshot_dir = settings().stored_path(pkg["snapshot_dir"])
        wv.status = "published"
        wv.published_at = now()
        auto = payload.get("auto_approve", True)
        existing = {sc.slug for sc in s.scalars(select(Scenario).where(Scenario.world_version_id == wv.id))}
        for sid, spec in pkg["scenarios"].items():
            if sid in existing:
                continue
            s.add(Scenario(
                project_id=wv.project_id, world_version_id=wv.id, slug=sid, family=spec["family"], split=spec["split"], spec=spec,
                status="approved" if auto else "validated", validation=pkg["reports"].get(sid, {}),
                approved_by="policy:auto-approve-validated" if auto else None, approved_at=now() if auto else None,
            ))
        emit(s, project_id=wv.project_id, stream=ctx.job_id, type="world.published", summary=f"world version {wv.version} published with {len(pkg['scenarios'])} validated scenarios", data={"world_version_id": wv.id, "content_hash": wv.content_hash})


def handle_validate(ctx: JobContext) -> dict:
    """Re-runs validation for scenarios of a published world (owner-proposed scenarios, or a full re-check of the
    version): the deterministic checks, then the live agent audit. A job the audit finds unfair is withdrawn."""
    from ..compiler.validation import UNFAIR, live_audit, validate_scenario
    from ..config import settings
    from ..core.contracts import ScenarioSpec, WorldManifest
    from ..runner.runtime import WorldInstance

    p = ctx.payload
    with session() as s:
        ctx.owned(s)
        wv = s.get(WorldVersion, p["world_version_id"])
        assert wv is not None
        manifest = WorldManifest.model_validate(wv.manifest)
        secrets, variables, snap = wv.private["secrets"], wv.private["vars"], settings().data_path(wv.snapshot_dir)
        q = select(Scenario).where(Scenario.world_version_id == wv.id, Scenario.status != "rejected")
        if p.get("scenario_ids"):
            q = q.where(Scenario.id.in_(p["scenario_ids"]))
        targets = [(sc.id, sc.spec) for sc in s.scalars(q)]
    inst = WorldInstance.create(manifest, secrets=secrets, snapshot=snap, log=lambda m: ctx.log("validate.sandbox", m))
    results = {}
    try:
        for sc_id, spec in targets:
            ctx.check()
            scenario = ScenarioSpec.model_validate(spec)
            report = validate_scenario(inst, manifest, snap, variables, scenario, log=lambda m: ctx.log("validate.step", m))
            if report.ok and p.get("live_audit", True):
                report.live = live_audit(inst, manifest, snap, variables, scenario, agent_chain=settings().model_agent, auditor_chain=settings().model_reasoner, check=ctx.check, add_cost=ctx.add_cost)
                if report.live["cause"] in UNFAIR:
                    report.ok = False
                    report.reasons.append(f"a live agent could not pass this job for a reason that is not its fault ({report.live['cause']}): {report.live.get('evidence', '')}")
            results[sc_id] = report.ok
            with session() as s:
                ctx.owned(s)
                sc = s.get(Scenario, sc_id)
                sc.validation = report.to_json()  # type: ignore[union-attr]
                if sc.status == "proposed":  # type: ignore[union-attr]
                    sc.status = "validated" if report.ok else "rejected"  # type: ignore[union-attr]
                elif not report.ok:
                    sc.status = "rejected"  # type: ignore[union-attr]
                emit(s, project_id=ctx.project_id, stream=ctx.job_id, type="validation.result", summary=f"{spec['id']}: {'valid' if report.ok else '; '.join(report.reasons)[:300]}")
    finally:
        inst.destroy()
    return {"validated": results}
