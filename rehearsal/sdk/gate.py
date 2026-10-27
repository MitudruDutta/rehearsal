"""`rehearsal gate`: a pass or fail check for an agent change, for CI.

It rehearses the agent (a profile, or a new version made from the instructions file in the change) on a published
world, next to a baseline version when one is given, waits for the run, and judges the result: the verified success
must reach the required rate, rule violations must stay under the limit, and nothing may get worse than the baseline.
It prints a Markdown report (also appended to --report, for example $GITHUB_STEP_SUMMARY) and exits 0 when the change
passes, 1 when it fails, and 2 when the run did not finish.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

PASSED, FAILED, UNFINISHED = 0, 1, 2

ROWS = (("success_rate", "Verified success"), ("hard_violation_episodes", "Episodes with a rule violation"),
        ("false_completions", "Claimed done but was not"), ("duplicate_effects", "Duplicate side effects"),
        ("environment_errors", "Environment errors (not scored)"))


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x:.0%}"


def verdict(summary: dict[str, Any], candidate: str, baseline: str | None = None, *, min_success: float | None = None,
            max_violations: int | None = 0, tolerance: float = 0.0) -> tuple[bool, list[tuple[bool, str]]]:
    """Whether the candidate passes, with one (passed, reason) line per check. Profiles are keyed `name@vN`."""
    profiles = summary.get("profiles") or {}
    cand = (profiles.get(candidate) or {}).get("overall")
    if not cand or cand.get("success_rate") is None:
        return False, [(False, "nothing was scored: every episode hit an environment error, or the agent had no episodes")]
    rate, checks = cand["success_rate"], []
    if min_success is not None:
        checks.append((rate >= min_success, f"verified success {_pct(rate)}, required {_pct(min_success)}"))
    if max_violations is not None:
        checks.append((cand["hard_violation_episodes"] <= max_violations,
                       f"{cand['hard_violation_episodes']} episodes broke a rule, at most {max_violations} allowed"))
    base = (profiles.get(baseline) or {}).get("overall") if baseline else None
    if base and base.get("success_rate") is not None:
        slack = f", {tolerance:.0%} tolerance" if tolerance else ""
        checks.append((rate >= base["success_rate"] - tolerance - 1e-9,  # 0.8 - 0.1 is not quite 0.7 in floating point
                       f"verified success {_pct(rate)} vs {_pct(base['success_rate'])} for the baseline{slack}"))
        for key, what in ROWS[1:4]:
            checks.append((cand[key] <= base[key], f"{what.lower()}: {cand[key]} vs {base[key]} for the baseline"))
    return all(ok for ok, _ in checks), checks


def report(summary: dict[str, Any], candidate: str, baseline: str | None, passed: bool, checks: list[tuple[bool, str]],
           run_link: str, note: str = "", causes: list[dict[str, Any]] | None = None) -> str:
    cols = [(candidate, "this change")] + ([(baseline, "baseline")] if baseline else [])
    aggs = [(summary.get("profiles") or {}).get(key, {}).get("overall") or {} for key, _ in cols]

    def cell(agg: dict[str, Any], key: str) -> str:
        if key == "success_rate":
            return f"{_pct(agg.get(key))} ({agg.get('successes', 0)}/{agg.get('finished', 0)})"
        return str(agg.get(key, "–"))

    lines = [f"### Rehearsal gate: {'passed' if passed else 'failed'}", "",
             f"Every episode is checked against the application's own database. [Open the run]({run_link})", "",
             "| | " + " | ".join(f"`{key}` ({label})" for key, label in cols) + " |", "|---|" + "---|" * len(cols)]
    lines += [f"| {label} | " + " | ".join(cell(a, key) for a in aggs) + " |" for key, label in ROWS]
    lines += [""] + [f"- {'PASS' if ok else 'FAIL'}: {text}" for ok, text in checks]
    if causes:
        lines += ["", f"**Why `{candidate}` failed episodes**", ""]
        lines += [f"- {c['label']}: {c['count']} episode{'s' if c['count'] != 1 else ''}. {c['fix']}" for c in causes[:3]]
    return "\n".join(lines + (["", note] if note else [])) + "\n"


def _stop(message: str) -> None:
    """The check could not run (a usage or server problem): exit 2, so CI does not read it as the agent failing."""
    print(message, file=sys.stderr)
    sys.exit(UNFINISHED)


def _profile(c: Any, profile_id: str | None, prompt_file: str | None, name: str | None) -> dict[str, Any]:
    """The profile to test. From a file, the latest version of `name` with the same instructions is reused, so an
    unchanged file does not add a version on every CI run."""
    if profile_id:
        return c.get(f"/v1/agent-profiles/{profile_id}")
    if not (prompt_file and name):
        _stop("give --profile, or --prompt-file with --name")
    prompt = Path(prompt_file).read_text(encoding="utf-8")
    same = [p for p in c.profiles.list() if p["name"] == name and (p.get("spec") or {}).get("system_prompt") == prompt
            and (p.get("spec") or {}).get("driver", "llm") == "llm"]
    return max(same, key=lambda p: p["version"]) if same else c.profiles.create(name, prompt)


def _wait(c: Any, run_id: str, timeout_s: float, poll_s: float = 15) -> dict[str, Any] | None:
    deadline, last = time.monotonic() + timeout_s, None
    while time.monotonic() < deadline:
        run = c.runs.get(run_id)
        if run["status"] != last:
            print(f"run {run_id}: {run['status']}", file=sys.stderr, flush=True)
            last = run["status"]
        if run["status"] in ("finished", "failed", "cancelled"):
            return run
        time.sleep(poll_s)
    return None


def run(c: Any, args: Any) -> int:
    cand = _profile(c, args.profile, args.prompt_file, args.name)
    base = _profile(c, args.baseline, args.baseline_file, args.name) if (args.baseline or args.baseline_file) else None
    note = ""
    if base and base["id"] == cand["id"]:
        base, note = None, "The change does not touch the agent's instructions, so there is no baseline to compare with."
    key = lambda p: f"{p['name']}@v{p['version']}"  # noqa: E731
    if args.run:
        run_id = args.run
    else:
        if not args.wv_id:
            _stop("give the world version to rehearse on, or --run with a finished run")
        res = c.evaluations.create(args.wv_id, [cand["id"]] + ([base["id"]] if base else []), args.split or None, args.repeats,
                                   **({"budget_usd": args.budget} if args.budget is not None else {}))
        run_id = res["run_id"]
        later = f"; on the free plan it starts at {res['starts_at']} (UTC)" if res.get("starts_at") else ""
        print(f"rehearsing {key(cand)}{' next to ' + key(base) if base else ''}: {res['episodes']} episodes{later}", file=sys.stderr, flush=True)
    finished = _wait(c, run_id, args.timeout * 60)
    link = f"{c.base_url}/app/run/?id={run_id}"
    if not finished or finished["status"] != "finished":
        print(f"The run did not finish ({finished['status'] if finished else 'timed out'}): {link}", file=sys.stderr)
        return UNFINISHED
    passed, checks = verdict(finished.get("summary") or {}, key(cand), key(base) if base else None,
                             min_success=args.min_success, max_violations=args.max_violations, tolerance=args.tolerance)
    try:  # named causes need a key with evaluator access; the verdict does not depend on them
        causes = (c.get(f"/v1/runs/{run_id}/failures").get(key(cand)) or {}).get("causes")
    except Exception:  # noqa: BLE001
        causes = None
    text = report(finished.get("summary") or {}, key(cand), key(base) if base else None, passed, checks, link, note, causes)
    print(text)
    if args.report:
        with open(args.report, "a", encoding="utf-8") as f:
            f.write(text)
    return PASSED if passed else FAILED
