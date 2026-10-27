"""Failure analysis: every failed episode gets named causes, read from the verifier and the actions, never a model."""

from types import SimpleNamespace

from rehearsal.evaluator.failures import CAUSES, classify, summarize
from rehearsal.sdk import gate


def act(observed=1, goal=1, status="SUCCEEDED", mutating=True):
    return SimpleNamespace(observed_goal_version=observed, goal_version=goal, status=status, mutating=mutating)


def oracle(**kw):
    return {"goal_satisfied": False, "hard_constraint_violations": [], "check_results": [], **kw}


def test_each_cause_is_read_from_the_record():
    assert classify(oracle(hard_constraint_violations=["refund_once"]), "completed") == ["broke_rule"]
    assert classify(oracle(), "completed", [act(observed=1, goal=2)]) == ["old_request"]
    assert classify(oracle(), "completed", [act(observed=1, goal=2, mutating=False)]) == ["wrong_result"]  # reading stale data is not acting on it
    assert classify(oracle(duplicate_effects=1, recovery_result="not_recovered"), "completed") == ["duplicate", "no_recovery"]
    assert classify(oracle(false_completion=True), "claimed_complete") == ["false_done"]
    assert classify(oracle(), "max_steps") == ["stalled"]
    assert classify(oracle(rejected_attempts=3), "completed") == ["refused_calls"]
    assert classify(oracle(), "completed") == ["wrong_result"]
    assert classify(oracle(environment_error="sandbox died"), "environment_error") == []  # not the agent's fault
    assert set(CAUSES) >= {"broke_rule", "old_request", "duplicate", "no_recovery", "false_done", "stalled", "refused_calls", "wrong_result"}


def ep(i, profile="agent@v1", reward=0, scenario="refund", termination="completed", actions=(), **o):
    return {"id": f"ep{i}", "profile": profile, "scenario": scenario, "reward": reward, "termination": termination, "oracle": oracle(**o), "actions": list(actions)}


def test_a_run_summary_counts_causes_per_agent_most_common_first():
    goal_check = {"id": "c1", "description": "refund amount is 20", "passed": False, "role": "goal"}
    rule_check = {"id": "c2", "description": "no second refund", "passed": False, "role": "constraint"}
    episodes = [
        ep(1, duplicate_effects=1, check_results=[goal_check]),
        ep(2, duplicate_effects=1, scenario="cancel"),
        ep(3, hard_constraint_violations=["c2"], check_results=[rule_check, goal_check], reward=-1),
        ep(4, reward=1, goal_satisfied=True),  # verified: not a failure
        ep(5, environment_error="no sandbox"),  # not scored: left out
        ep(6, profile="agent@v2", false_completion=True),
    ]
    out = summarize(episodes)
    v1 = out["agent@v1"]
    assert v1["failed"] == 3 and [c["cause"] for c in v1["causes"]] == ["duplicate", "broke_rule"]
    dup = v1["causes"][0]
    assert dup["count"] == 2 and dup["share"] == 0.667 and dup["episodes"] == ["ep1", "ep2"] and set(dup["jobs"]) == {"refund", "cancel"}
    assert dup["checks"] == ["refund amount is 20"] and dup["fix"].startswith("After a timeout")
    assert v1["causes"][1]["checks"] == ["no second refund"]  # a broken rule names the rule, not the goal checks
    assert out["agent@v2"]["causes"][0]["label"] == "Said it was done when it was not"


def test_the_ci_report_says_why_the_change_failed():
    causes = summarize([ep(1, duplicate_effects=1), ep(2, duplicate_effects=1), ep(3)])["agent@v1"]["causes"]
    text = gate.report({"profiles": {}}, "agent@v1", None, False, [(False, "verified success 0%")], "https://x/run", causes=causes)
    assert "Why `agent@v1` failed episodes" in text and "- Did the same thing twice: 2 episodes." in text
    assert "Why" not in gate.report({"profiles": {}}, "agent@v1", None, True, [], "https://x/run")
