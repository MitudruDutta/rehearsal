"""Independent outcome evaluation.

The oracle reads application state through privileged read-only probes and the
emulated-dependency journal. It never consults the agent's own claims except to
flag a false completion. Language-model judgement is not used here.
"""

from __future__ import annotations

import json
import operator
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .. import telemetry
from ..core.contracts import CheckSpec, OracleResult, ScenarioSpec
from .probes import ProbeError, Prober, coerce_equal, effects_connection, query_sqlite_conn

OPS = {"==": operator.eq, "!=": operator.ne, ">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}
DUPLICATE_PROVIDERS = {"payments", "shipping", "email", "smtp"}


@dataclass
class EpisodeStats:
    rejected_attempts: int = 0
    customer_contacts: int = 0
    faults_fired: int = 0
    claimed_complete: bool = False
    elapsed_ms: int = 0
    cost_usd: float = 0.0
    tokens: int = 0
    environment_error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def run_check(check: CheckSpec, prober: Prober, effects: Any, variables: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"id": check.id, "description": check.description, "op": check.op, "expected": check.value}
    try:
        if check.source == "effects":
            rows = query_sqlite_conn(effects, check.query, variables)
        else:
            rows = prober.query(check.query, variables, check.probe)
        if len(rows) != 1 or len(rows[0]) != 1:
            raise ProbeError(f"check must return exactly one row and column, got {len(rows)} rows")
        actual = coerce_equal(rows[0][0], check.value)
        result["actual"] = actual
        try:
            result["passed"] = bool(OPS[check.op](actual, check.value))
        except TypeError:
            result["passed"] = False
            result["error"] = f"cannot compare {actual!r} {check.op} {check.value!r}"
    except ProbeError as exc:
        result["passed"] = False
        result["error"] = str(exc)
    return result


def duplicate_effects(journal: list[dict[str, Any]]) -> int:
    counts = Counter(
        (e["provider"], e["operation"], json.dumps(json.loads(e["request_json"]), sort_keys=True))
        for e in journal
        if e["provider"] in DUPLICATE_PROVIDERS
    )
    return sum(n - 1 for n in counts.values() if n > 1)


def evaluate(
    prober: Prober,
    journal: list[dict[str, Any]],
    scenario: ScenarioSpec,
    variables: dict[str, Any],
    goal_version: int,
    stats: EpisodeStats,
) -> OracleResult:
    with telemetry.span("oracle.evaluate", "GUARDRAIL", scenario=scenario.id, goal_version=goal_version) as sp:
        prober.invalidate()
        effects = effects_connection(journal)
        checks = {c.id: c for c in scenario.checks}
        goal = next(g for g in scenario.goals if g.version == goal_version)
        wanted = list(dict.fromkeys([*goal.checks, *scenario.constraints]))
        results = {cid: run_check(checks[cid], prober, effects, variables) for cid in wanted}
        for cid, r in results.items():
            r["role"] = "constraint" if cid in scenario.constraints else "goal"
        goal_ok = all(results[c]["passed"] for c in goal.checks)
        violations = [c for c in scenario.constraints if not results[c]["passed"]]
        dups = duplicate_effects(journal)
        recovery = "not_applicable"
        if stats.faults_fired:
            recovery = "recovered" if goal_ok and not violations and dups == 0 and not stats.environment_error else "not_recovered"
        out = OracleResult(
            goal_version=goal_version,
            goal_satisfied=goal_ok and not stats.environment_error,
            hard_constraint_violations=violations,
            check_results=list(results.values()),
            rejected_attempts=stats.rejected_attempts,
            unnecessary_interruptions=max(0, stats.customer_contacts - scenario.max_customer_contacts),
            duplicate_effects=dups,
            recovery_result=recovery,  # type: ignore[arg-type]
            elapsed_ms=stats.elapsed_ms,
            model_cost_usd=round(stats.cost_usd, 6),
            tokens=stats.tokens,
            environment_error=stats.environment_error,
            claimed_complete=stats.claimed_complete,
            false_completion=stats.claimed_complete and not goal_ok,
        )
        telemetry.set_attr(sp, "goal_satisfied", out.goal_satisfied)
        telemetry.set_attr(sp, "violations", ",".join(violations))
        telemetry.set_attr(sp, "reward", out.reward)
        return out
