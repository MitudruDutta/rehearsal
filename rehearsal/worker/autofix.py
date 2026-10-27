"""autofix job: fix an agent, prove it, keep only what helps.

Starting from an agent profile and a finished run, each round asks the Improvement agent for a new version from the
failed train/dev episodes, rehearses that version on every train/dev job, and keeps it only when it verifies more
episodes without new rule violations or false "done" claims. A rejected attempt is shown to the next round so it
tries something else. When the rounds end (or every job passes), the original and the best version are rehearsed
side by side on held-out jobs that no round has seen: that comparison is the evidence, not the training score.

Rehearsals run inside this job, one episode at a time on one sandbox, so the loop never waits on other workers. Every
phase is saved in the job checkpoint; after a worker restart the loop resumes where it stopped.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ..db.events import emit
from ..db.models import AgentProfileRow, Episode, Run, Scenario, WorldVersion
from ..db.session import session
from . import evaluate, improve
from .context import JobContext

PRACTICE = ("train", "dev")


def better(new: dict[str, Any], best: dict[str, Any]) -> bool:
    """A version is kept only if it verifies more episodes and adds no rule violation or false completion. Problems are
    compared per finished episode: the starting run (two attempts per job by default) and a round can differ in size."""
    if new.get("success_rate") is None:
        return False

    def rate(score: dict[str, Any], key: str) -> float:
        return score[key] / score["finished"] if score.get("finished") else 0.0

    return (new["success_rate"] > (best.get("success_rate") or 0)
            and rate(new, "hard_violation_episodes") <= rate(best, "hard_violation_episodes")
            and rate(new, "false_completions") <= rate(best, "false_completions"))


def _new_run(ctx: JobContext, wv_id: str, profile_ids: list[str], splits: tuple[str, ...], repeats: int, purpose: str) -> str | None:
    """A run whose episodes belong to this job, so only this job rehearses them."""
    with session() as s:
        ctx.owned(s)
        wv = s.get(WorldVersion, wv_id)
        profiles = [s.get(AgentProfileRow, pid) for pid in profile_ids]
        scenarios = list(s.scalars(select(Scenario).where(Scenario.world_version_id == wv_id, Scenario.status == "approved",
                                                          Scenario.split.in_(splits)).order_by(Scenario.slug)))
        if not scenarios or wv is None:
            return None
        run = Run(project_id=ctx.project_id, world_version_id=wv_id, job_id=ctx.job_id,
                  config={"splits": list(splits), "repeats": repeats, "default_stress": True, "purpose": purpose, "autofix_job": ctx.job_id,
                          "profiles": [f"{r.name}@v{r.version}" for r in profiles if r], "world_content_hash": wv.content_hash})
        s.add(run)
        s.flush()
        n = 0
        for rep in range(repeats):
            for sc in scenarios:
                for prof in profiles:
                    s.add(Episode(project_id=ctx.project_id, run_id=run.id, scenario_id=sc.id, profile_id=prof.id, seed=rep, job_id=ctx.job_id))  # type: ignore[union-attr]
                    n += 1
        emit(s, project_id=ctx.project_id, stream=run.id, type="run.queued", summary=f"{n} episodes queued ({purpose})")
        return run.id


def _rehearse(ctx: JobContext, run_id: str) -> None:
    """Runs a run's episodes in this job with the evaluation handler, then restores this job's own payload."""
    payload = ctx.payload
    ctx.payload = {**payload, "run_id": run_id}
    try:
        evaluate.handle(ctx)
    finally:
        ctx.payload = payload
    ctx.checkpoint.pop("shard_done", None)
    ctx.save_checkpoint(ctx.checkpoint)


def _version(profile_id: str) -> int:
    with session() as s:
        row = s.get(AgentProfileRow, profile_id)
        return row.version if row else 0


def handle(ctx: JobContext) -> dict[str, Any]:
    p = ctx.payload
    st: dict[str, Any] = ctx.checkpoint.get("autofix") or {}
    if not st:
        base = improve.score(p["run_id"], p["profile_id"], PRACTICE)
        if not base["finished"]:
            raise ValueError("the run has no finished train/dev episodes for this agent")
        original = {"profile_id": p["profile_id"], "version": _version(p["profile_id"]), "run_id": p["run_id"], "score": base}
        st = {"phase": "propose", "round": 1, "original": original, "best": original, "rounds": [], "current": None, "holdout": None}
        ctx.checkpoint["autofix"] = st
        ctx.save_checkpoint(ctx.checkpoint)
        ctx.log("autofix.started", f"fixing v{original['version']}: {_pct(base)} verified on train and dev", {"original": original})

    def save() -> None:
        ctx.checkpoint["autofix"] = st
        ctx.save_checkpoint(ctx.checkpoint)

    while st["phase"] != "done":
        ctx.check()
        best = st["best"]
        if st["phase"] == "propose":
            if (best["score"].get("success_rate") or 0) >= 1:
                st["phase"] = "holdout"
                continue
            rejected = [{"rationale": r["rationale"], "verified_rate": r["score"].get("success_rate")} for r in st["rounds"] if not r["accepted"]]
            proposal = improve.propose(ctx, best["profile_id"], best["run_id"], rejected=rejected)
            if "version" not in proposal:  # nothing failed: nothing to fix
                st["phase"] = "holdout"
                continue
            st["current"] = {"profile_id": proposal["profile_id"], "version": proposal["version"], "rationale": proposal.get("rationale", ""), "run_id": None}
            st["phase"] = "rehearse"
            save()
            ctx.log("autofix.proposed", f"round {st['round']}: v{proposal['version']} proposed", {"round": st["round"], **st["current"]})
        elif st["phase"] == "rehearse":
            cur = st["current"]
            if cur["run_id"] is None:
                cur["run_id"] = _new_run(ctx, p["world_version_id"], [cur["profile_id"]], PRACTICE, int(p.get("repeats", 1)), f"fix round {st['round']}")
                save()
            _rehearse(ctx, cur["run_id"])
            sc = improve.score(cur["run_id"], cur["profile_id"], PRACTICE)
            kept = better(sc, best["score"])
            st["rounds"].append({**cur, "round": st["round"], "score": sc, "accepted": kept, "compared_with": {"profile_id": best["profile_id"], "version": best["version"], "score": best["score"]}})
            if kept:
                st["best"] = {**cur, "score": sc}
            ctx.log("autofix.round", f"round {st['round']}: v{cur['version']} verified {_pct(sc)} vs {_pct(best['score'])}: {'kept' if kept else 'discarded'}",
                    {"round": st["round"], "accepted": kept, "version": cur["version"], "score": sc, "previous": best["score"]})
            st["current"] = None
            st["round"] += 1
            st["phase"] = "holdout" if st["round"] > int(p.get("rounds", 3)) else "propose"
            save()
        elif st["phase"] == "holdout":
            original = st["original"]
            if best["profile_id"] == original["profile_id"]:
                st["phase"] = "done"
                ctx.log("autofix.finished", "no version beat the original on train and dev; nothing to prove on held-out jobs", {})
                continue
            if not st.get("holdout_run"):
                st["holdout_run"] = _new_run(ctx, p["world_version_id"], [original["profile_id"], best["profile_id"]], ("holdout",), int(p.get("repeats", 1)), "held-out proof")
                save()
            if st["holdout_run"]:
                _rehearse(ctx, st["holdout_run"])
                st["holdout"] = {"run_id": st["holdout_run"],
                                 "original": improve.score(st["holdout_run"], original["profile_id"], ("holdout",)),
                                 "best": improve.score(st["holdout_run"], best["profile_id"], ("holdout",))}
                h = st["holdout"]
                ctx.log("autofix.finished", f"held-out jobs: v{best['version']} verified {_pct(h['best'])} vs v{original['version']} {_pct(h['original'])}", h)
            else:
                ctx.log("autofix.finished", "this world has no held-out jobs; the train and dev results are the evidence", {})
            st["phase"] = "done"
            save()
    return {k: st[k] for k in ("original", "best", "rounds", "holdout")}


def _pct(score: dict[str, Any]) -> str:
    rate = score.get("success_rate")
    return "–" if rate is None else f"{rate:.0%}"
