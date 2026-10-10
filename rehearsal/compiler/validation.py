"""Deterministic scenario validation (grader validity + task solvability).

A scenario is accepted only when, from a fresh reset:

1. its setup runs;
2. a no-op run (claim completion immediately) does NOT satisfy the final goal,
   so the checks are not trivially true;
3. the reference trajectory satisfies the final goal with no hard violation,
   no rejected step, and no environment error;
4. every negative trajectory is rejected (reward <= 0);
5. replaying the reference gives the same check outcomes (determinism).

No model judgement is involved in those five; the scenario designer cannot approve itself.

A scripted reference proves that a job CAN be passed. It does not prove that a live agent, which only sees the tools,
the instructions and the customer's messages, can find that way, or that the checks accept every correct way. So a
sixth step runs the job once with a plain live agent (``live_audit``). If it passes, the job is proven fair. If it
fails, an auditor reads the run and names the first cause: the agent (the job is fair), a check that rejects correct
work, or something the agent could not have found. Jobs with the last two causes are repaired or withheld.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..agents.episode import Engine, LLMPolicy, MemoryRecorder, ScriptedPolicy
from ..agents.llm import LLMError, chat_json
from ..core.contracts import AgentProfile, ScenarioSpec, TrajectoryStep, WorldManifest
from ..runner.runtime import WorldInstance
from ..runner.seed import SeedError, run_seed


@dataclass
class RunSummary:
    reward: int
    goal_satisfied: bool
    violations: list[str]
    environment_error: str | None
    checks: list[dict[str, Any]]
    rejected_steps: list[dict[str, Any]] = field(default_factory=list)
    failed_steps: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ScenarioReport:
    scenario: str
    ok: bool = False
    reasons: list[str] = field(default_factory=list)
    setup_error: str | None = None
    noop: RunSummary | None = None
    reference: RunSummary | None = None
    negatives: dict[str, RunSummary] = field(default_factory=dict)
    deterministic: bool | None = None
    tools_used: list[str] = field(default_factory=list)
    live: dict[str, Any] | None = None  # live_audit result: passed, cause, evidence, fix

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    def feedback(self) -> str:
        """Compact, evidence-bearing explanation for the repair agent."""
        lines = [f"Scenario {self.scenario} failed validation:"] + [f"- {r}" for r in self.reasons]
        for label, run in [("no-op run", self.noop), ("reference", self.reference), *[(f"negative '{k}'", v) for k, v in self.negatives.items()]]:
            if run is None:
                continue
            lines.append(f"{label}: reward={run.reward} goal_satisfied={run.goal_satisfied} violations={run.violations} env_error={run.environment_error}")
            for c in run.checks:
                lines.append(f"    check {c['id']}: passed={c.get('passed')} actual={c.get('actual')!r} expected {c.get('op')} {c.get('expected')!r}{' error=' + c['error'] if c.get('error') else ''}")
            for s in run.rejected_steps[:5] + run.failed_steps[:5]:
                lines.append(f"    step {s['tool']}({s['args']}) -> {s['status']}: {str(s['visible'])[:400]}")
        if self.live and self.live.get("cause") in UNFAIR:
            lines.append(f"live agent audit: cause={self.live['cause']}. {self.live.get('evidence', '')}\n  suggested fix: {self.live.get('fix', '')}")
            lines += [f"    failed check {c['id']}: actual={c.get('actual')!r} expected {c.get('op')} {c.get('expected')!r}" for c in self.live.get("failed_checks", [])]
            lines.append("  what the live agent did:\n" + "\n".join(f"    {t}" for t in self.live.get("trail", [])[-40:]))
        return "\n".join(lines)


def _summ(engine: Engine, rec: MemoryRecorder, result: Any) -> RunSummary:
    rejected = [{"tool": a["tool"], "args": a["args"], "status": a["status"], "visible": a["visible_result"]} for a in rec.actions if a["status"] == "REJECTED"]
    failed = [{"tool": a["tool"], "args": a["args"], "status": a["status"], "visible": a["visible_result"]} for a in rec.actions if a["status"] in ("FAILED",) and not a.get("fault")]
    for e in rec.events:
        if e["type"] == "action.rejected":
            rejected.append({"tool": "(call)", "args": {}, "status": "REJECTED", "visible": e["summary"]})
    return RunSummary(result.reward, result.goal_satisfied, result.hard_constraint_violations, result.environment_error, result.check_results, rejected, failed)


def _episode(instance: WorldInstance, manifest: WorldManifest, scenario: ScenarioSpec, variables: dict[str, Any], steps: list[TrajectoryStep]) -> tuple[RunSummary, MemoryRecorder]:
    rec = MemoryRecorder()
    eng = Engine(
        episode_id="ep_validation01",
        instance=instance,
        manifest=manifest,
        scenario=scenario,
        variables=dict(variables),
        recorder=rec,
        policy=ScriptedPolicy(steps),
        participant_mode="scripted",
    )
    result = eng.run()
    return _summ(eng, rec, result), rec


def prepare(instance: WorldInstance, base_snapshot: Path, base_vars: dict[str, Any], scenario: ScenarioSpec) -> dict[str, Any]:
    instance.restore(base_snapshot)
    return run_seed(instance, scenario.setup, dict(base_vars))


def validate_scenario(
    instance: WorldInstance,
    manifest: WorldManifest,
    base_snapshot: Path,
    base_vars: dict[str, Any],
    scenario: ScenarioSpec,
    *,
    check_determinism: bool = True,
    log: Any = None,
) -> ScenarioReport:
    report = ScenarioReport(scenario.id)
    problems = scenario.validate_against(manifest)
    if problems:
        report.reasons += problems
        return report

    def fresh() -> dict[str, Any] | None:
        try:
            return prepare(instance, base_snapshot, base_vars, scenario)
        except SeedError as exc:
            report.setup_error = str(exc)
            report.reasons.append(f"setup failed: {exc}")
            return None

    finisher = next(a.id for a in scenario.actors if a.can_complete)

    variables = fresh()
    if variables is None:
        return report
    report.noop, _ = _episode(instance, manifest, scenario, variables, [TrajectoryStep(actor=finisher, tool="complete", args={"summary": "done"})])
    final_goal = scenario.goals[-1]
    if report.noop.goal_satisfied and report.noop.reward > 0:
        report.reasons.append("the no-op run already satisfies the final goal: the goal checks are trivially true before any action")
    errors = [c for c in report.noop.checks if c.get("error")]
    if errors:
        report.reasons.append("some checks error on the initial state: " + "; ".join(f"{c['id']}: {c['error']}" for c in errors))
    if log:
        log(f"{scenario.id}: no-op checked")

    variables = fresh()
    if variables is None:
        return report
    report.reference, rec = _episode(instance, manifest, scenario, variables, scenario.reference)
    report.tools_used = sorted({a["tool"] for a in rec.actions if a["mutating"] and a["status"] == "SUCCEEDED"})
    ref = report.reference
    if not ref.goal_satisfied:
        report.reasons.append(f"reference trajectory does not satisfy goal v{final_goal.version}")
    if ref.violations:
        report.reasons.append(f"reference trajectory violates hard constraints {ref.violations}")
    if ref.environment_error:
        report.reasons.append(f"reference run hit an environment error: {ref.environment_error}")
    if ref.rejected_steps:
        report.reasons.append(f"reference has {len(ref.rejected_steps)} rejected step(s) (bad tool, role, or arguments)")
    if log:
        log(f"{scenario.id}: reference reward {ref.reward}")

    for neg in scenario.negatives:
        variables = fresh()
        if variables is None:
            return report
        summary, _ = _episode(instance, manifest, scenario, variables, neg.steps)
        report.negatives[neg.name] = summary
        if summary.reward > 0:
            report.reasons.append(f"negative trajectory '{neg.name}' ({neg.description}) was accepted by the checks; they cannot tell it apart from success")
        if log:
            log(f"{scenario.id}: negative {neg.name} reward {summary.reward}")
    if len(scenario.negatives) < 2:
        report.reasons.append("at least two negative trajectories are required")

    if check_determinism and not report.reasons:
        variables = fresh()
        if variables is not None:
            again, _ = _episode(instance, manifest, scenario, variables, scenario.reference)
            first = {c["id"]: c.get("passed") for c in ref.checks}
            second = {c["id"]: c.get("passed") for c in again.checks}
            report.deterministic = first == second
            if not report.deterministic:
                report.reasons.append(f"reference replay is not deterministic: {first} vs {second}")
    report.ok = not report.reasons
    return report


# ------------------------------------------------------------------ live audit

UNFAIR = ("check", "undiscoverable")  # causes that are the world's fault, not the agent's

AUDITOR = (
    "You audit whether a practice job for AI agents is fair. A plain agent tried the job in a sandbox and the checks failed it. "
    "You get the job (customer request and its revision, actor instructions, the SQL checks, the tools each role has) and what the "
    "agent did (tool calls with results, its notes, the customer's messages). Name the FIRST cause of the failure:\n"
    "- \"check\": the agent did what the customer asked, in a way a reasonable reviewer would accept, and a check still failed. "
    "Typical: the check needs one specific seeded record or id (for example a reply under an old seeded message, when the customer "
    "wrote a new one during the run), exact wording, or one of several correct ways.\n"
    "- \"undiscoverable\": the agent needed an id, name or fact that it could not get: not in its instructions, not said by the "
    "customer, and not returned by any tool its role can call (for example a private channel that no listing tool shows).\n"
    "- \"agent\": the job was fair. The agent made a mistake, gave up, did the wrong thing, claimed work it did not do, or ran out of steps.\n"
    "Choose \"agent\" unless the run itself shows evidence for one of the other two. Return JSON: "
    "{\"cause\": \"check|undiscoverable|agent\", \"evidence\": \"two sentences citing the calls or check values\", "
    "\"fix\": \"for check/undiscoverable: the exact change to the checks, reference steps, setup or tools that makes the job fair\"}."
)


def _trail(rec: MemoryRecorder) -> list[str]:
    """The run in order, short enough to read: who called what with which result, and what was said."""
    notes = [f"{e['actor'] or 'system'} noted: {e['summary'][:300]}" for e in rec.events if e["type"] in ("agent.decision", "action.held", "goal.revised")]
    calls = [f"{a['actor']} called {a['tool']}({str(a['args'])[:300]}) -> {a['status']}{' [' + a['fault'] + ']' if a.get('fault') else ''}: {str(a['visible_result'])[:500]}" for a in rec.actions]
    return [*calls, *notes]  # ponytail: notes follow calls instead of being interleaved; add sequence numbers to events if order matters


def live_audit(instance: WorldInstance, manifest: WorldManifest, base_snapshot: Path, base_vars: dict[str, Any], scenario: ScenarioSpec, *,
               agent_chain: str, auditor_chain: str, check: Any = None, add_cost: Any = None, max_cost_usd: float = 0.25) -> dict[str, Any]:
    """Runs the job once with a plain live agent. Returns {passed, cause, evidence, fix, ...}: ``cause`` is None when it
    passed, "inconclusive" when the run or the audit could not be completed, else agent | check | undiscoverable."""
    try:
        variables = prepare(instance, base_snapshot, base_vars, scenario)
    except SeedError as exc:
        return {"passed": False, "cause": "inconclusive", "evidence": f"setup failed: {exc}"[:500]}
    rec = MemoryRecorder()
    eng = Engine(episode_id="ep_liveaudit01", instance=instance, manifest=manifest, scenario=scenario, variables=dict(variables), recorder=rec,
                 policy=LLMPolicy(AgentProfile(name="audit", system_prompt=""), agent_chain), participant_mode="llm", check=check, max_cost_usd=max_cost_usd)
    result = eng.run()
    if add_cost:
        add_cost(eng.state.cost_usd, eng.state.tokens)
    out: dict[str, Any] = {"passed": result.reward > 0 and not result.environment_error, "cause": None, "ending": eng.state.termination, "cost_usd": round(eng.state.cost_usd, 4)}
    if out["passed"]:
        return out
    if result.environment_error:
        return {**out, "cause": "inconclusive", "evidence": str(result.environment_error)[:500]}
    out["failed_checks"] = [c for c in result.check_results if not c.get("passed")]
    out["trail"] = _trail(rec)
    job = {
        "goals": [g.model_dump(mode="json") for g in scenario.goals], "actors": [a.model_dump(mode="json") for a in scenario.actors],
        "customer": scenario.participant.model_dump(mode="json"), "checks": [c.model_dump(mode="json") for c in scenario.checks],
        "events": [e.model_dump(mode="json") for e in scenario.events],
        "tools_by_role": {r.name: [t.name for t in manifest.tools if r.name in t.roles] for r in manifest.roles},
    }
    evidence = {"ending": out["ending"], "failed_checks": out["failed_checks"], "run": out["trail"][-80:]}
    try:
        verdict, reply = chat_json(auditor_chain, [{"role": "system", "content": AUDITOR}, {"role": "user", "content": f"Job:\n{json.dumps(job, default=str)[:24000]}\n\nRun:\n{json.dumps(evidence, default=str)[:30000]}"}], max_tokens=1200, check=check)
    except LLMError as exc:
        return {**out, "cause": "inconclusive", "evidence": f"audit unavailable: {exc}"[:300]}
    if add_cost:
        add_cost(reply.cost_usd, reply.prompt_tokens + reply.completion_tokens)
    cause = verdict.get("cause") if isinstance(verdict, dict) else None
    if cause not in ("agent", *UNFAIR):
        return {**out, "cause": "inconclusive", "evidence": "auditor returned no usable verdict"}
    return {**out, "cause": cause, "evidence": str(verdict.get("evidence", ""))[:800], "fix": str(verdict.get("fix", ""))[:800]}
