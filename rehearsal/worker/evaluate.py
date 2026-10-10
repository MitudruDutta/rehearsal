"""evaluation job: runs episodes for (scenario, profile, seed) combinations.

A run is split into shards. Each shard is one job: one worker, one sandbox. Shards take episodes from the run
one at a time, so a run finishes sooner when more workers are free and still finishes with one.
Every episode starts from the published base snapshot.
If the worker dies mid-episode, the next worker reattaches to the same sandbox
and resumes the episode from its persisted engine state. Tool calls that were
in flight are reported to the agent as outcome-unknown, which is exactly what a
real client would see.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy import func, select

from .. import telemetry
from ..agents.episode import EpisodeState, Engine, ExternalPolicy, LLMPolicy
from ..config import settings
from ..core.contracts import AgentProfile, OracleResult, ScenarioSpec, WorldManifest
from ..db.queue import LeaseLost
from ..db.events import emit
from ..db.models import Action, AgentProfileRow, Episode, Event, Message, Run, Scenario, WorldVersion, now
from ..db.session import session
from ..runner.runtime import InstanceRecord, RuntimeError_, WorldInstance
from ..runner.seed import SeedError, run_seed
from .context import JobContext


class DBRecorder:
    """Commit observations, engine state and usage together under the job lease."""

    def __init__(self, project_id: str, run_id: str, episode_id: str, cursor: dict[str, int] | int = 0, ctx: JobContext | None = None):
        self.project_id, self.run_id, self.episode_id = project_id, run_id, episode_id
        self.ctx = ctx
        self.pending: list[tuple[str, Any]] = []
        start = cursor if isinstance(cursor, dict) else {}
        default = cursor if isinstance(cursor, int) else 0
        self.cursor = {t: start.get(t, default) for t in ("intervention.requested", "external.action.submitted")}

    def _poll(self, type: str) -> list[Event]:
        with session() as s:
            rows = list(s.scalars(select(Event).where(
                Event.stream == self.run_id, Event.episode_id == self.episode_id,
                Event.type == type, Event.id > self.cursor[type],
            ).order_by(Event.id)))
            for row in rows:
                s.expunge(row)
        return rows

    def poll_interventions(self) -> list[dict[str, Any]]:
        rows = self._poll("intervention.requested")
        if rows:
            self.cursor["intervention.requested"] = rows[-1].id
        return [r.data for r in rows]

    def poll_external(self, actor: str) -> dict[str, Any] | None:
        for r in self._poll("external.action.submitted"):
            self.cursor["external.action.submitted"] = r.id
            if r.data.get("actor") == actor:
                return r.data
            self.event("external.action.rejected", f"action for {r.data.get('actor')} arrived during {actor}'s turn", data={"idempotency_key": r.data.get("idempotency_key")})
        return None

    def publish(self, type: str, data: dict[str, Any]) -> None:
        self.event(type, f"{type} for {data.get('actor')}", actor=data.get("actor"), data=data)

    def action(self, r: dict[str, Any]) -> None:
        self.pending.append(("action", _jsonable(r)))

    def message(self, r: dict[str, Any]) -> None:
        self.pending.append(("message", _jsonable(r)))

    def event(self, type: str, summary: str, *, actor: str | None = None, goal_version: int | None = None, data: dict[str, Any] | None = None) -> None:
        self.pending.append(("event", dict(type=type, summary=summary, actor=actor, goal_version=goal_version, data=_jsonable(data or {}))))

    def save(self, state: EpisodeState) -> None:
        delta = 0.0
        with session() as s:
            job = self.ctx.owned(s) if self.ctx else None
            ep = s.get(Episode, self.episode_id)
            if ep is None:
                raise RuntimeError("episode disappeared")
            delta = max(0.0, state.cost_usd - (ep.cost_usd or 0.0))
            tokens = max(0, state.tokens - (ep.tokens or 0))
            ep.state = {**_jsonable(state.to_json()), "event_cursor": dict(self.cursor)}
            ep.cost_usd, ep.tokens = state.cost_usd, state.tokens
            if job is not None:
                job.spent_usd = (job.spent_usd or 0.0) + delta
                job.tokens = (job.tokens or 0) + tokens
            for kind, r in self.pending:
                if kind == "action":
                    s.add(Action(episode_id=self.episode_id, finished_at=now(), **telemetry._redact_any(r)))
                elif kind == "message":
                    s.add(Message(episode_id=self.episode_id, **telemetry._redact_any(r)))
                else:
                    emit(s, project_id=self.project_id, stream=self.run_id, episode_id=self.episode_id,
                         type=r["type"], summary=r["summary"], actor_id=r["actor"], goal_version=r["goal_version"], data=r["data"])
        self.pending.clear()
        if self.ctx:
            self.ctx.spent += delta


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _instance(ctx: JobContext, manifest: WorldManifest, wv: dict[str, Any]) -> WorldInstance:
    rec = ctx.checkpoint.get("instance")
    if rec:
        inst = WorldInstance(InstanceRecord.from_json(rec))
        if inst.alive():
            return inst
        _destroy_owned(ctx, inst)
    ctx.check()
    inst = WorldInstance.create(manifest, secrets=wv["secrets"], snapshot=Path(wv["snapshot_dir"]), log=lambda m: ctx.log("run.sandbox", m))
    ctx.checkpoint["instance"] = inst.record.to_json()
    ctx.save_checkpoint(ctx.checkpoint)
    return inst


def _close_dangling_calls(state: EpisodeState, recorder: DBRecorder, *, external: bool = False) -> None:
    """Consume persisted intents without repeating potentially completed effects."""
    unknown = {"error": "the platform restarted while this request was in flight; its outcome is unknown"}
    intents = dict(state.pending)
    for intent in intents.values():
        if intent.get("request"):
            state.ops[intent["op_id"]] = {"actor": intent["actor"], "request": intent["request"]}
    closed: set[str] = set()
    for actor in state.actors.values():
        answered = {m.get("tool_call_id") for m in actor.transcript if m.get("role") == "tool"}
        calls = {c["id"]: c for m in actor.transcript if m.get("role") == "assistant"
                 for c in m.get("tool_calls", [])}
        for call_id, intent in intents.items():
            if intent["actor"] == actor.id and call_id not in calls:
                call = {"id": call_id, "type": "function", "function": {"name": intent["tool"], "arguments": json.dumps(intent.get("args", {}))}}
                actor.transcript.append({"role": "assistant", "content": "", "tool_calls": [call]})
                calls[call_id] = call
        for call_id, call in calls.items():
            if call_id in answered:
                continue
            actor.transcript.append({"role": "tool", "tool_call_id": call_id, "content": json.dumps(unknown)})
            recorder.event("action.unknown", f"{call['function']['name']} interrupted by worker restart; outcome unknown", actor=actor.id, goal_version=state.goal_version)
            if external:
                recorder.publish("external.action.result", {"actor": actor.id, "idempotency_key": call_id,
                                 "tool": call["function"]["name"], "result": unknown})
            closed.add(call_id)
    for call_id, intent in intents.items():
        if call_id not in closed and intent["actor"] not in state.actors:
            recorder.event("action.unknown", f"{intent['tool']} interrupted by worker restart; outcome unknown", goal_version=state.goal_version)
    state.pending.clear()


def run_episode(ctx: JobContext, inst: WorldInstance, manifest: WorldManifest, wv: dict[str, Any], episode_id: str) -> OracleResult | None:
    with session() as s:
        ctx.owned(s)
        ep = s.get(Episode, episode_id)
        assert ep is not None
        if ep.status in ("finished", "error"):
            return None
        sc_row = s.get(Scenario, ep.scenario_id)
        prof_row = s.get(AgentProfileRow, ep.profile_id) if ep.profile_id else None
        scenario = ScenarioSpec.model_validate(sc_row.spec)  # type: ignore[union-attr]
        profile = AgentProfile.model_validate(prof_row.spec) if prof_row else AgentProfile(name="default", system_prompt="")
        resume = ep.status == "running" and bool(ep.state) and ctx.checkpoint.get("current_episode") == ep.id
        stored_vars = dict((ep.instance or {}).get("vars", {}))
        run_id, project_id = ep.run_id, ep.project_id
    recorder = DBRecorder(project_id, run_id, episode_id, ctx=ctx, cursor=(ep.state or {}).get("event_cursor", 0) if resume else _max_event(run_id))
    if ep.status == "running" and not resume:
        _finish_error(ctx, episode_id, "running episode has no resumable state and checkpoint claim; refusing to replay")
        return None
    if resume and (ep.instance or {}).get("instance_id") != inst.record.instance_id:
        _finish_error(ctx, episode_id, "the original sandbox was lost; persisted actions cannot be resumed in a fresh sandbox")
        ctx.checkpoint.pop("current_episode", None)
        ctx.save_checkpoint(ctx.checkpoint)
        return None
    if resume:
        raw = dict(ep.state)
        raw.pop("event_cursor", None)
        state = EpisodeState.from_json(raw)
        _close_dangling_calls(state, recorder, external=profile.driver == "external")
        variables = stored_vars
        recorder.event("episode.resumed", "worker restarted; resuming episode in the same sandbox")
        recorder.save(state)
    else:
        state = None
        try:
            inst.restore(Path(wv["snapshot_dir"]))
            variables = run_seed(inst, scenario.setup, dict(wv["vars"]))
        except (SeedError, RuntimeError_) as exc:
            _finish_error(ctx, episode_id, f"environment setup failed: {exc}")
            return None
        fp_before = _fingerprint(inst)
        with session() as s:
            ctx.owned(s)
            ep = s.get(Episode, episode_id)
            ep.status, ep.started_at, ep.instance = "running", now(), {"instance_id": inst.record.instance_id, "vars": variables, "fingerprint": fp_before}  # type: ignore[union-attr]
        ctx.checkpoint["current_episode"] = episode_id
        ctx.save_checkpoint(ctx.checkpoint)
    engine = Engine(
        episode_id=episode_id,
        instance=inst,
        manifest=manifest,
        scenario=scenario,
        variables=variables,
        recorder=recorder,
        policy=(
            ExternalPolicy(profile, recorder.poll_external, recorder.publish, timeout_s=float(ctx.payload.get("external_turn_timeout_s", 600)))
            if profile.driver == "external"
            else LLMPolicy(profile, settings().model_agent)
        ),
        participant_mode="llm",
        check=ctx.check,
        state=state,
        max_cost_usd=ctx.payload.get("max_episode_cost_usd"),
        max_turns_per_actor=profile.max_turns_per_actor,
    )
    with telemetry.span(f"episode.{scenario.id}", "CHAIN", session_id=episode_id, run=run_id, profile=f"{profile.name}@v{profile.version}"):
        result = engine.run()
    recorder.save(engine.state)
    fp_after = _fingerprint(inst)
    with session() as s:
        ctx.owned(s)
        ep = s.get(Episode, episode_id)
        before = (ep.instance or {}).get("fingerprint", {})  # type: ignore[union-attr]
        changed = sorted(k for k in set(before) | set(fp_after) if before.get(k) != fp_after.get(k))
        ep.status, ep.finished_at = ("error" if result.environment_error else "finished"), now()  # type: ignore[union-attr]
        ep.oracle, ep.reward = {**result.model_dump(), "changed_tables": changed}, result.reward  # type: ignore[union-attr]
        ep.cost_usd, ep.tokens, ep.termination = engine.state.cost_usd, engine.state.tokens, engine.state.termination  # type: ignore[union-attr]
    ctx.checkpoint.pop("current_episode", None)
    ctx.save_checkpoint(ctx.checkpoint)
    return result


def _max_event(run_id: str) -> int:
    from sqlalchemy import func

    with session() as s:
        return s.scalar(select(func.max(Event.id)).where(Event.stream == run_id)) or 0


def _fingerprint(inst: WorldInstance) -> dict[str, str]:
    from ..evaluator.probes import Prober

    try:
        return Prober(inst).fingerprint()
    except Exception:  # noqa: BLE001 - the diff is a convenience, never a reason to fail
        return {}


def _finish_error(ctx: JobContext, episode_id: str, message: str) -> None:
    with session() as s:
        ctx.owned(s)
        ep = s.get(Episode, episode_id)
        ep.status, ep.finished_at, ep.termination = "error", now(), "environment_error"  # type: ignore[union-attr]
        ep.oracle = {"environment_error": message[:2000]}  # type: ignore[union-attr]
        emit(s, project_id=ep.project_id, stream=ep.run_id, type="environment.error", summary=message[:500], episode_id=episode_id)  # type: ignore[union-attr]


_OPEN = ("pending", "running")


def _claim(ctx: JobContext, run_id: str) -> str | None:
    """The next episode for this shard: the one it was running (worker restart), else one of its own, else a free one."""
    with session() as s:
        ctx.owned(s)
        mine = ctx.checkpoint.get("current_episode")
        ep = s.get(Episode, mine) if mine else None
        if ep is None or ep.status not in _OPEN:
            ep = s.scalars(select(Episode).where(Episode.run_id == run_id, Episode.job_id == ctx.job_id, Episode.status.in_(_OPEN)).order_by(Episode.id).limit(1)).first()
        if ep is None:
            ep = s.scalars(select(Episode).where(Episode.run_id == run_id, Episode.job_id.is_(None), Episode.status.in_(_OPEN))
                           .order_by(Episode.id).limit(1).with_for_update(skip_locked=True)).first()
        if ep is None:
            return None
        ep.job_id = ctx.job_id
        return ep.id


def _settle(ctx: JobContext, run_id: str) -> bool:
    """Called when a shard finds nothing to claim. Finishes the run if every episode is done. Returns False when a
    failed shard handed episodes back in the meantime, so the caller claims again. The run row is the lock shared
    with queue.release_shard."""
    with session() as s:
        job = ctx.owned(s)
        run = s.scalars(select(Run).where(Run.id == run_id).with_for_update()).first()
        left = list(s.scalars(select(Episode.job_id).where(Episode.run_id == run_id, Episode.status.in_(_OPEN))))
        if any(owner is None for owner in left):
            return False
        job.checkpoint = ctx.checkpoint = {**ctx.checkpoint, "shard_done": True}
        if not left and run.status != "finished":  # type: ignore[union-attr]
            summary = summarize_run(run_id)  # episodes are committed already; it reads them on its own connection
            run.status, run.summary, run.finished_at = "finished", summary, now()  # type: ignore[union-attr]
            emit(s, project_id=run.project_id, stream=run_id, type="run.finished", summary=json.dumps(summary.get("overall", {}))[:500], data=summary)  # type: ignore[union-attr]
        return True


def handle(ctx: JobContext) -> dict[str, Any]:
    run_id = ctx.payload["run_id"]
    with session() as s:
        ctx.owned(s)
        run = s.scalars(select(Run).where(Run.id == run_id).with_for_update()).first()
        assert run is not None
        total = s.scalar(select(func.count()).select_from(Episode).where(Episode.run_id == run_id))
        if run.status != "running":
            run.status = "running"
            emit(s, project_id=run.project_id, stream=run_id, type="run.started", summary=f"{total} episodes")
        wv_row = s.get(WorldVersion, run.world_version_id)
        wv = {"manifest": wv_row.manifest, "secrets": wv_row.private["secrets"], "vars": wv_row.private["vars"], "snapshot_dir": str(settings().data_path(wv_row.snapshot_dir))}  # type: ignore[union-attr]
    manifest = WorldManifest.model_validate(wv["manifest"])
    inst: WorldInstance | None = None
    try:
        while True:
            ctx.check()
            eid = _claim(ctx, run_id)
            if eid is None:
                if _settle(ctx, run_id):
                    break
                continue
            inst = inst or _instance(ctx, manifest, wv)  # a shard that finds no work never starts a sandbox
            try:
                run_episode(ctx, inst, manifest, wv, eid)
            except RuntimeError_ as exc:
                _finish_error(ctx, eid, f"sandbox failure: {exc}")
                inst = _instance(ctx, manifest, wv) if inst.alive() else _replace(ctx, inst, manifest, wv)
            with session() as s:
                done = s.scalar(select(func.count()).select_from(Episode).where(Episode.run_id == run_id, Episode.status.notin_(_OPEN)))
            ctx.log("run.progress", f"{done}/{total} episodes done")
    finally:
        if ctx._stop is None:
            rec = ctx.checkpoint.get("instance")
            inst = inst or (WorldInstance(InstanceRecord.from_json(rec)) if rec else None)
            if inst is not None:
                try:
                    _destroy_owned(ctx, inst, clear=True)
                except LeaseLost:
                    pass  # Replacement worker owns the sandbox and its cleanup.
    with session() as s:
        run = s.get(Run, run_id)
        return {"run_id": run_id, "overall": (run.summary or {}).get("overall")}  # type: ignore[union-attr]


def _destroy_owned(ctx: JobContext, inst: WorldInstance, *, clear: bool = False) -> None:
    # Hold the claim lock through destruction so a replacement cannot attach midway.
    with session() as s:
        job = ctx.owned(s)
        current = (job.checkpoint or {}).get("instance")
        if current and current.get("instance_id") != inst.record.instance_id:
            raise LeaseLost("sandbox belongs to a replacement claim")
        inst.destroy()
        if clear:
            checkpoint = {k: v for k, v in ctx.checkpoint.items() if k != "instance"}
            job.checkpoint = checkpoint
    if clear:
        ctx.checkpoint = checkpoint


def _replace(ctx: JobContext, inst: WorldInstance, manifest: WorldManifest, wv: dict[str, Any]) -> WorldInstance:
    _destroy_owned(ctx, inst, clear=True)
    return _instance(ctx, manifest, wv)


def summarize_run(run_id: str, *, fair_only: bool = False) -> dict[str, Any]:
    """Scores of a run. With fair_only, jobs withdrawn since (a re-check found them unfair) are left out, so a
    verdict never rests on a job the agent could not pass for reasons that were not its fault."""
    with session() as s:
        q = (
            select(Episode, Scenario.split, Scenario.slug, Scenario.family, AgentProfileRow.name, AgentProfileRow.version)
            .join(Scenario, Scenario.id == Episode.scenario_id)
            .outerjoin(AgentProfileRow, AgentProfileRow.id == Episode.profile_id)
            .where(Episode.run_id == run_id)
        )
        rows = s.execute(q.where(Scenario.status != "rejected") if fair_only else q).all()
    groups: dict[str, list[tuple[Episode, str, str, str]]] = defaultdict(list)
    for ep, split, slug, family, pname, pver in rows:
        groups[f"{pname or 'default'}@v{pver or 1}"].append((ep, split, slug, family))
    out: dict[str, Any] = {"profiles": {}}
    for prof, items in groups.items():
        out["profiles"][prof] = {"overall": _agg([e for e, *_ in items])}
        for split in ("train", "dev", "holdout"):
            eps = [e for e, sp, *_ in items if sp == split]
            if eps:
                out["profiles"][prof][split] = _agg(eps)
        out["profiles"][prof]["per_scenario"] = {slug: _agg([e for e, _, sl, _ in items if sl == slug]) for slug in sorted({sl for _, _, sl, _ in items})}
    out["overall"] = _agg([e for e, *_ in rows])
    return out


def _agg(eps: list[Episode]) -> dict[str, Any]:
    errors = [e for e in eps if e.status == "error" or (e.oracle or {}).get("environment_error")]
    done = [e for e in eps if e.status == "finished" and not (e.oracle or {}).get("environment_error")]
    o = [e.oracle for e in done]
    success = [x for x in o if x.get("goal_satisfied") and not x.get("hard_constraint_violations")]
    faulted = [x for x in o if x.get("recovery_result") in ("recovered", "not_recovered")]
    return {
        "episodes": len(eps),
        "finished": len(done),
        "environment_errors": len(errors),
        "successes": len(success),
        "success_rate": round(len(success) / len(done), 3) if done else None,
        "hard_violation_episodes": sum(1 for x in o if x.get("hard_constraint_violations")),
        "false_completions": sum(1 for x in o if x.get("false_completion")),
        "duplicate_effects": sum(x.get("duplicate_effects", 0) for x in o),
        "recovered": f"{sum(1 for x in faulted if x['recovery_result'] == 'recovered')}/{len(faulted)}",
        "unnecessary_interruptions": sum(x.get("unnecessary_interruptions", 0) for x in o),
        "rejected_attempts": sum(x.get("rejected_attempts", 0) for x in o),
        "mean_reward": round(mean(e.reward or 0 for e in done), 3) if done else None,
        "cost_usd": round(sum(e.cost_usd or 0 for e in eps), 4),
        "tokens": sum(e.tokens or 0 for e in eps),
    }
