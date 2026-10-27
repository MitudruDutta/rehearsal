"""improvement job: the Improvement agent proposes a revised agent profile.

It reads only train/dev episodes of the given run (never holdout), sees the
role-visible transcript, the actions with what the agent saw, and which oracle
checks failed, and edits only the profile's system prompt and per-tool
guidance. The new version is evaluated like any other profile; nothing here
claims an improvement.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from ..agents.llm import LLMError, chat_json
from ..config import settings
from ..core.contracts import AgentProfile
from ..db.events import emit
from ..db.models import Action, AgentProfileRow, Episode, Run, Scenario
from ..db.session import session
from ..evaluator.failures import run_failures
from .context import JobContext

MAX_FAILURES = 8


def _episode_digest(s: Any, ep: Episode, sc: Scenario) -> dict[str, Any]:
    actions = list(s.scalars(select(Action).where(Action.episode_id == ep.id).order_by(Action.seq)))
    oracle = ep.oracle or {}
    return {
        "scenario": sc.slug,
        "title": sc.spec.get("title"),
        "goals": [g["instruction"] for g in sc.spec.get("goals", [])],
        "termination": ep.termination,
        "failed_checks": [c["description"] for c in oracle.get("check_results", []) if not c.get("passed")],
        "violations": oracle.get("hard_constraint_violations"),
        "false_completion": oracle.get("false_completion"),
        "duplicate_effects": oracle.get("duplicate_effects"),
        "actions": [
            {"actor": a.actor, "tool": a.tool, "args": a.args, "status": a.status, "saw": json.dumps(a.visible_result, default=str)[:300], "observed_goal_v": a.observed_goal_version, "goal_v": a.goal_version}
            for a in actions[:40]
        ],
    }


def handle(ctx: JobContext) -> dict[str, Any]:
    return propose(ctx, ctx.payload["profile_id"], ctx.payload["run_id"])


def propose(ctx: JobContext, profile_id: str, run_id: str, *, rejected: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Proposes the next version of a profile from its failed train/dev episodes in a run. ``rejected`` lists earlier
    proposals that did not help (their rationale and score), so the agent tries something else instead of repeating
    them. Returns the new profile's id and version, or a message when there is nothing to fix."""
    with session() as s:
        ctx.owned(s)
        prof_row = s.get(AgentProfileRow, profile_id)
        run = s.get(Run, run_id)
        assert prof_row is not None and run is not None
        profile = AgentProfile.model_validate(prof_row.spec)
        rows = s.execute(
            select(Episode, Scenario).join(Scenario, Scenario.id == Episode.scenario_id)
            # Only jobs that are still approved: a job withdrawn as unfair must not teach the agent anything.
            .where(Episode.run_id == run.id, Episode.profile_id == prof_row.id, Episode.status == "finished", Scenario.split.in_(["train", "dev"]), Scenario.status == "approved")
        ).all()
        failures = [_episode_digest(s, ep, sc) for ep, sc in rows if (ep.reward or 0) <= 0][:MAX_FAILURES]
        successes = sum(1 for ep, _ in rows if (ep.reward or 0) > 0)
        tool_names = sorted({a for ep, _ in rows for a in [x.tool for x in s.scalars(select(Action).where(Action.episode_id == ep.id))]})
    # named causes over train and dev only, so the proposal targets the most common ones (never held-out jobs)
    causes = next(iter(run_failures(run_id, splits=("train", "dev"), profile_id=profile_id).values()), {}).get("causes", []) if failures else []
    if not rows:
        raise ValueError("the run has no finished train/dev episodes for this profile")
    if not failures:
        return {"message": "no failed train/dev episodes; nothing to improve", "profile_id": prof_row.id}
    system = (
        "You are the Improvement agent. You revise an AI agent's operating instructions so it does better on the kinds of failures "
        "shown, without overfitting to specific record IDs, names, or scenario wording (those will differ in held-out evaluation). "
        "You may change only the system prompt and per-tool guidance. Describe general behaviours: verify state after uncertain "
        "outcomes before retrying, re-read the latest customer request before acting, confirm the target record, avoid unnecessary "
        "customer contacts, never claim completion without checking. Fix the most common failure causes first. If earlier attempts that did not help are listed, change "
        "your approach rather than restating them. Keep the {actor_id}, {role}, and {instructions} placeholders in "
        "the system prompt. Return JSON: {\"system_prompt\": str, \"tool_guidance\": {tool: str}, \"rationale\": str}."
    )
    user = json.dumps(
        {
            "current_profile": {"system_prompt": profile.system_prompt or "(platform default)", "tool_guidance": profile.tool_guidance},
            "episodes_succeeded": successes,
            "failure_causes": [{k: c[k] for k in ("label", "meaning", "count", "jobs", "checks")} for c in causes],
            "failed_episodes": failures,
            "tools_seen": tool_names,
            **({"earlier_attempts_that_did_not_help": rejected} if rejected else {}),
        },
        default=str,
    )[:120_000]
    ctx.check()
    try:
        data, reply = chat_json(settings().model_improver, [{"role": "system", "content": system}, {"role": "user", "content": user}], check=ctx.check, role="improver")
    except LLMError as exc:
        reply = getattr(exc, "reply", None)
        if reply is not None:
            ctx.add_cost(reply.cost_usd, reply.prompt_tokens + reply.completion_tokens)
        raise
    ctx.add_cost(reply.cost_usd, reply.prompt_tokens + reply.completion_tokens)
    ctx.check()
    out = save_version(ctx, profile, data, parent_id=prof_row.id, created_by="improver", summary=f"proposed from {len(failures)} failed train/dev episodes")
    return {**out, "failures_used": len(failures)}


def save_version(ctx: JobContext, profile: AgentProfile, data: Any, *, parent_id: str | None, created_by: str, summary: str) -> dict[str, Any]:
    """Saves a model-written {system_prompt, tool_guidance, rationale} as the next version of the profile's name.
    The prompt keeps the {actor_id}, {role} and {instructions} placeholders the episode engine fills."""
    if not isinstance(data, dict):
        raise ValueError(f"{created_by} must return a JSON object")
    prompt = str(data.get("system_prompt", "")).strip()
    for ph in ("{actor_id}", "{role}", "{instructions}"):
        if ph not in prompt:
            prompt += f"\n{ph[1:-1].replace('_', ' ').title()}: {ph}"
    try:
        prompt.format(actor_id="a", role="r", instructions="i")
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(f"the written prompt has invalid placeholders: {exc}") from exc
    guidance = {k: str(v)[:600] for k, v in (data.get("tool_guidance") or {}).items() if isinstance(k, str)}
    with session() as s:
        ctx.owned(s)
        from sqlalchemy import func, text

        s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"profile-version:{ctx.project_id}:{profile.name}"})

        version = (s.scalar(select(func.max(AgentProfileRow.version)).where(AgentProfileRow.project_id == ctx.project_id, AgentProfileRow.name == profile.name)) or 0) + 1
        spec = profile.model_copy(update={"version": version, "system_prompt": prompt, "tool_guidance": guidance})
        row = AgentProfileRow(project_id=ctx.project_id, name=profile.name, version=version, spec=spec.model_dump(), parent_id=parent_id, created_by=created_by, rationale=str(data.get("rationale", ""))[:4000])
        s.add(row)
        s.flush()
        emit(s, project_id=ctx.project_id, stream=ctx.job_id, type="profile.proposed", summary=f"{profile.name} v{version} {summary}", data={"profile_id": row.id, "rationale": row.rationale[:1000]})
        return {"profile_id": row.id, "version": version, "rationale": row.rationale[:500]}


def score(run_id: str, profile_id: str, splits: tuple[str, ...]) -> dict[str, Any]:
    """One profile's results in a run on the given splits (jobs withdrawn as unfair are left out)."""
    from .evaluate import _agg

    with session() as s:
        eps = list(s.scalars(select(Episode).join(Scenario, Scenario.id == Episode.scenario_id)
                             .where(Episode.run_id == run_id, Episode.profile_id == profile_id, Scenario.split.in_(splits), Scenario.status == "approved")))
    return _agg(eps)
