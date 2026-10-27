"""Why episodes failed, as named causes with the episodes behind them.

Deterministic: each cause is read from the verifier's result and the recorded actions, never from a model's opinion.
One failed episode can have several causes. Episodes that hit an environment error are left out: they are not the
agent's fault. The run page, the CLI, the MCP server, the CI gate and the fix loop all read the same summary; the fix
loop reads it for train and dev jobs only.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from sqlalchemy import select

# cause: (label, what it means, what usually fixes it)
CAUSES: dict[str, tuple[str, str, str]] = {
    "broke_rule": ("Broke a hard rule", "A check that must never fail did fail: the agent did something it was not allowed to do.",
                   "State the rule in the instructions and tell the agent to refuse, or ask, before acting outside it."),
    "old_request": ("Acted on the old request", "The customer changed the request, and the agent changed records for the earlier version.",
                    "Re-read the latest customer message before every change."),
    "duplicate": ("Did the same thing twice", "A change was made twice, usually a blind retry after a call timed out.",
                  "After a timeout or an unclear result, look the record up before trying again."),
    "no_recovery": ("Did not recover from a fault", "A call failed or timed out on purpose, and the work was not finished correctly afterwards.",
                    "Treat an error as information: check what happened, then continue or retry once."),
    "false_done": ("Said it was done when it was not", "The agent told the customer the work was done, but the records say otherwise.",
                   "Confirm the change in the records before saying it is done."),
    "stalled": ("Gave up or ran out of steps", "The agent stopped acting, or used every step it had, before the work was done.",
                "Plan the steps first, and ask the customer when information is missing instead of waiting."),
    "refused_calls": ("Kept making calls the application refused", "Three or more calls were rejected: wrong arguments, a missing permission, or a tool the role may not use.",
                      "Describe each tool's arguments, and which role may do what, in the tool guidance."),
    "wrong_result": ("Finished with the wrong records", "The episode ended normally, but the records do not match what the customer asked for.",
                     "Confirm the target record and every value with the customer before changing it."),
}
STALLED = {"stalled", "max_steps", "max_turns", "budget", "external_timeout"}


def classify(oracle: dict[str, Any] | None, termination: str | None, actions: Iterable[Any] = ()) -> list[str]:
    """The causes of one failed episode. `actions` need `mutating`, `status`, `goal_version` and `observed_goal_version`."""
    o = oracle or {}
    if o.get("environment_error"):
        return []
    causes = []
    if o.get("hard_constraint_violations"):
        causes.append("broke_rule")
    if any(a.mutating and a.status == "SUCCEEDED" and (a.observed_goal_version or 0) < (a.goal_version or 0) for a in actions):
        causes.append("old_request")
    if o.get("duplicate_effects"):
        causes.append("duplicate")
    if o.get("recovery_result") == "not_recovered":
        causes.append("no_recovery")
    if o.get("false_completion"):
        causes.append("false_done")
    if termination in STALLED and not o.get("goal_satisfied"):
        causes.append("stalled")
    if (o.get("rejected_attempts") or 0) >= 3:
        causes.append("refused_calls")
    if not causes and not o.get("goal_satisfied"):
        causes.append("wrong_result")
    return causes


def _failed_checks(oracle: dict[str, Any], role: str) -> list[str]:
    return [str(c.get("description") or c.get("id")) for c in oracle.get("check_results") or [] if not c.get("passed") and (c.get("role") == "constraint") == (role == "constraint")]


def summarize(episodes: Iterable[dict[str, Any]], max_examples: int = 5) -> dict[str, Any]:
    """Per agent: how many episodes failed and, for each cause, how many and which. Each item of `episodes` has
    `id`, `profile`, `scenario`, `oracle`, `termination`, `reward` and `actions`."""
    out: dict[str, Any] = {}
    for ep in episodes:
        oracle = ep.get("oracle") or {}
        if ep.get("reward") == 1 or oracle.get("environment_error") or not oracle:
            continue
        causes = classify(oracle, ep.get("termination"), ep.get("actions") or [])
        agent = out.setdefault(ep["profile"], {"failed": 0, "causes": {}})
        agent["failed"] += 1
        for cause in causes:
            row = agent["causes"].setdefault(cause, {"count": 0, "episodes": [], "jobs": Counter(), "checks": Counter()})
            row["count"] += 1
            if len(row["episodes"]) < max_examples:
                row["episodes"].append(ep["id"])
            row["jobs"][ep.get("scenario")] += 1
            row["checks"].update(_failed_checks(oracle, "constraint" if cause == "broke_rule" else "goal"))
    for agent in out.values():
        agent["causes"] = [
            {"cause": cause, "label": CAUSES[cause][0], "meaning": CAUSES[cause][1], "fix": CAUSES[cause][2], "count": row["count"],
             "share": round(row["count"] / agent["failed"], 3), "episodes": row["episodes"],
             "jobs": [j for j, _ in row["jobs"].most_common(5)], "checks": [c for c, _ in row["checks"].most_common(3)]}
            for cause, row in sorted(agent["causes"].items(), key=lambda kv: -kv[1]["count"])
        ]
    return out


def run_failures(run_id: str, *, splits: Iterable[str] | None = None, profile_id: str | None = None) -> dict[str, Any]:
    """The causes of every failed episode in a run, per agent (`name@vN`), optionally limited to splits or one agent."""
    from ..db.models import Action, AgentProfileRow, Episode, Scenario
    from ..db.session import session

    with session() as s:
        q = (select(Episode, Scenario.slug, AgentProfileRow.name, AgentProfileRow.version)
             .join(Scenario, Scenario.id == Episode.scenario_id)
             .outerjoin(AgentProfileRow, AgentProfileRow.id == Episode.profile_id)
             .where(Episode.run_id == run_id, Episode.status == "finished"))
        if splits:
            q = q.where(Scenario.split.in_(list(splits)))
        if profile_id:
            q = q.where(Episode.profile_id == profile_id)
        rows = s.execute(q).all()
        failed = [ep.id for ep, *_ in rows if ep.reward != 1]
        actions: dict[str, list[Any]] = {}
        for a in s.scalars(select(Action).where(Action.episode_id.in_(failed))) if failed else []:
            actions.setdefault(a.episode_id, []).append(a)
        episodes = [{"id": ep.id, "profile": f"{name or 'default'}@v{version or 1}", "scenario": slug, "oracle": ep.oracle,
                     "termination": ep.termination, "reward": ep.reward, "actions": actions.get(ep.id, [])}
                    for ep, slug, name, version in rows]
    return summarize(episodes)
