"""incident job: turn something an agent got wrong in production into a job that catches it next time.

The owner describes the incident (what was asked, what the agent did, what should have happened; a transcript is best).
The scenario author writes one job for the published world that puts an agent in the same situation, with checks that
pass only when the agent avoids the mistake. The job is validated like every job the World Compiler writes (its reference
run passes, its wrong runs fail, a live agent can pass it), with up to three tries that see the validator's reasons. A job
that validates joins the world's dev split, approved, so every later evaluation and every `rehearsal gate` includes it.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from ..agents import llm
from ..config import settings
from ..core.contracts import ScenarioSpec, WorldManifest
from ..db.events import emit
from ..db.models import Scenario, WorldVersion
from ..db.session import session
from .context import JobContext

TRIES = 3
ROLE = "incident_author"


def _brief(manifest: WorldManifest, variables: dict[str, Any], example: dict[str, Any] | None, incident: str) -> list[dict[str, Any]]:
    tools = [{"name": t.name, "description": t.description[:300], "roles": t.roles, "mutating": t.mutating,
              "params": [p.name for p in t.params]} for t in manifest.tools]
    system = (
        "You write one rehearsal job (a scenario) that reproduces a production incident in a practice copy of the application, "
        "so the same mistake is caught before the next release. Put the agent in the same situation the incident describes "
        "(the same kind of request, the same trap: a changed request, a timeout, a missing permission, a look-alike record), "
        "using only the world's tools, roles and seeded records (setup steps may create more). Its checks read the database and "
        "must pass only when the agent does the right thing and fail for what the agent did in the incident: give that wrong "
        "behaviour as a negative trajectory. Keep the customer's words close to the incident's. Answer with the job as one JSON "
        "object matching the schema; use family \"incident\" and split \"dev\"."
    )
    user = (
        f"Incident:\n{incident[:12000]}\n\nTools:\n{json.dumps(tools)}\n\nRoles: {[r.name for r in manifest.roles]}\n"
        f"Seeded values (use as {{{{vars.NAME}}}}): {sorted(variables)}\n\nScenario schema:\n{json.dumps(ScenarioSpec.model_json_schema())}"
        + (f"\n\nA job from this world, for its format:\n{json.dumps(example)[:12000]}" if example else "")
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def handle(ctx: JobContext) -> dict[str, Any]:
    from ..compiler.validation import UNFAIR, live_audit, validate_scenario
    from ..runner.runtime import WorldInstance

    p = ctx.payload
    with session() as s:
        ctx.owned(s)
        wv = s.get(WorldVersion, p["world_version_id"])
        assert wv is not None
        manifest = WorldManifest.model_validate(wv.manifest)
        secrets, variables, snap = wv.private["secrets"], wv.private["vars"], settings().data_path(wv.snapshot_dir)
        example = next((sc.spec for sc in s.scalars(select(Scenario).where(Scenario.world_version_id == wv.id, Scenario.split == "train",
                                                                           Scenario.status == "approved").limit(1))), None)
        taken = set(s.scalars(select(Scenario.slug).where(Scenario.world_version_id == wv.id)))
    messages = _brief(manifest, variables, example, p["incident"])
    inst = WorldInstance.create(manifest, secrets=secrets, snapshot=snap, log=lambda m: ctx.log("incident.sandbox", m))
    reasons: list[str] = []
    try:
        for attempt in range(1, TRIES + 1):
            ctx.check()
            raw: Any = None
            try:
                raw, reply = llm.chat_json(settings().model_reasoner, messages, check=ctx.check, role=ROLE)
                ctx.add_cost(reply.cost_usd, reply.prompt_tokens + reply.completion_tokens)
            except llm.LLMError as exc:
                if exc.reply is not None:
                    ctx.add_cost(exc.reply.cost_usd, exc.reply.prompt_tokens + exc.reply.completion_tokens)
                reasons = [f"the answer was not one JSON object: {exc}"[:500]]
                messages.append({"role": "user", "content": f"{reasons[0]} Answer with the job as one JSON object."})
                continue
            try:
                spec = ScenarioSpec.model_validate({**(raw if isinstance(raw, dict) else {}), "family": "incident", "split": "dev"})
            except Exception as exc:  # noqa: BLE001 - the schema's message goes back to the author
                reasons = [f"the job does not match the schema: {str(exc)[:1500]}"]
            else:
                while spec.id in taken:
                    spec = spec.model_copy(update={"id": f"{spec.id[:40]}_{attempt}"})
                report = validate_scenario(inst, manifest, snap, variables, spec, log=lambda m: ctx.log("incident.validate", m))
                if report.ok:
                    report.live = live_audit(inst, manifest, snap, variables, spec, agent_chain=settings().model_agent,
                                             auditor_chain=settings().model_reasoner, check=ctx.check, add_cost=ctx.add_cost)
                    if report.live["cause"] in UNFAIR:
                        report.ok = False
                        report.reasons.append(f"a live agent could not pass it for a reason that is not its fault ({report.live['cause']}): {report.live.get('evidence', '')}")
                if report.ok:
                    with session() as s:
                        ctx.owned(s)
                        sc = Scenario(project_id=ctx.project_id, world_version_id=wv.id, slug=spec.id, family="incident", split="dev",
                                      spec=spec.model_dump(mode="json"), status="approved", validation=report.to_json(), approved_by="incident")
                        s.add(sc)
                        s.flush()
                        emit(s, project_id=ctx.project_id, stream=ctx.job_id, type="incident.added",
                             summary=f"{spec.title}: validated and added to the dev split", data={"scenario_id": sc.id, "attempt": attempt})
                        return {"scenario_id": sc.id, "title": spec.title, "attempts": attempt}
                reasons = report.reasons
            ctx.log("incident.rejected", f"try {attempt}: {'; '.join(reasons)[:300]}", {"attempt": attempt, "reasons": reasons})
            messages.append({"role": "assistant", "content": json.dumps(raw)[:12000]})
            messages.append({"role": "user", "content": "The validator refused this job:\n- " + "\n- ".join(reasons)[:4000] + "\nFix it and answer with the whole job again."})
    finally:
        inst.destroy()
    raise RuntimeError(f"no valid job after {TRIES} tries; last reasons: {'; '.join(reasons)[:1500]}")
