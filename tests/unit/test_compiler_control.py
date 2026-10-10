"""Compiler charges each reply before tools and stops before another call."""

from unittest.mock import Mock

import pytest

from rehearsal.agents.llm import LLMReply, ToolCall
from rehearsal.compiler.agent import Tool, run_agent
from rehearsal.worker.context import BudgetExceeded


def tool(name, fn):
    return Tool(name, name, {"type": "object", "properties": {}}, fn)


def test_usage_is_accounted_before_submit(monkeypatch):
    charged = []
    def submit(args):
        assert charged == [(0.75, 15)]
        return {"accepted": True}
    call = ToolCall("submit", "submit", {}, "{}")
    monkeypatch.setattr("rehearsal.compiler.agent.chat", lambda *a, **kw: LLMReply("", [call], "local", "m", 10, 5, .75))
    result = run_agent(role="test", chain="local:m", system="s", user="u", tools=[],
                       submit=tool("submit", submit), log=lambda *a: None,
                       check=lambda: None, add_cost=lambda usd, tokens: charged.append((usd, tokens)))
    assert result.result == {"accepted": True}
    assert result.cost_usd == .75


def test_reply_reaching_budget_cannot_dispatch_tools(monkeypatch):
    spent = []
    def check():
        if spent:
            raise BudgetExceeded("budget")
    fn = Mock()
    chat = Mock(return_value=LLMReply("", [ToolCall("work", "work", {}, "{}")], "local", "m", 10, 5, .75))
    monkeypatch.setattr("rehearsal.compiler.agent.chat", chat)
    with pytest.raises(BudgetExceeded):
        run_agent(role="test", chain="local:m", system="s", user="u", tools=[tool("work", fn)],
                  submit=tool("submit", Mock()), log=lambda *a: None, check=check,
                  add_cost=lambda *usage: spent.append(usage))
    fn.assert_not_called()
    chat.assert_called_once()
    assert spent == [(.75, 15)]


def test_cancellation_stops_between_tools_in_one_reply(monkeypatch):
    first, second = Mock(), Mock()
    def check():
        if first.called:
            raise BudgetExceeded("stopped")
    calls = [ToolCall("one", "one", {}, "{}"), ToolCall("two", "two", {}, "{}")]
    monkeypatch.setattr("rehearsal.compiler.agent.chat", Mock(return_value=LLMReply("", calls, "local", "m")))
    with pytest.raises(BudgetExceeded):
        run_agent(role="test", chain="local:m", system="s", user="u", tools=[tool("one", first), tool("two", second)],
                  submit=tool("submit", Mock()), log=lambda *a: None, check=check)
    first.assert_called_once()
    second.assert_not_called()


def test_compiler_uses_owned_destroy_callback(tmp_path):
    from rehearsal.compiler.pipeline import AppInput, Compiler
    from rehearsal.db.queue import LeaseLost
    from types import SimpleNamespace
    inst = SimpleNamespace(destroy=Mock())
    destroy = Mock(side_effect=LeaseLost("replacement owns sandbox"))
    compiler = Compiler(app=AppInput("test", tmp_path, {}, "", {}), checkpoint={},
                        workdir=tmp_path / "build", chain="local:m", log=lambda *a: None,
                        save=lambda *a: None, heartbeat=lambda: None, add_cost=lambda *a: None,
                        destroy=destroy)
    with pytest.raises(LeaseLost):
        compiler.destroy(inst)
    inst.destroy.assert_not_called()


@pytest.mark.parametrize("unsafe", ["..", ".", "../other", "/absolute", "nested/name", "nested\\name", "bad\0name"])
def test_export_file_names_reject_traversal(unsafe):
    from rehearsal.worker.export import _safe_name
    from rehearsal.sdk.examples import _safe_name as example_name
    for check in (_safe_name, example_name):
        with pytest.raises(ValueError):
            check(unsafe)


def test_event_commands_preserve_payload_but_public_data_is_masked():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from rehearsal.db.events import emit, serialize
    session = SimpleNamespace(execute=Mock(), scalar=lambda q: 0, add=Mock(), flush=Mock())
    payload = {"args": {"password": "sandbox-password"}, "actor": "a"}
    event = emit(session, project_id="p", stream="r", type="external.action.submitted", data=payload)
    assert event.data == payload
    event.id = 1
    event.created_at = datetime.now(timezone.utc)
    assert serialize(event)["data"]["args"]["password"] == "[REDACTED]"
    assert event.data["args"]["password"] == "sandbox-password"


def test_role_stops_early_when_the_same_rejection_keeps_coming_back(monkeypatch):
    from rehearsal.compiler.agent import CompilerAgentError, Rejected

    tries = []

    def submit(args):
        tries.append(1)
        raise Rejected(f"get_user as admin -> FAILED: 401 invalid token (try {len(tries)})")

    call = ToolCall("submit", "submit", {}, "{}")
    monkeypatch.setattr("rehearsal.compiler.agent.chat", lambda *a, **kw: LLMReply("", [call], "local", "m", 10, 5, .01))
    with pytest.raises(CompilerAgentError) as stuck:
        run_agent(role="adapter", chain="local:m", system="s", user="u", tools=[], submit=tool("submit", submit),
                  log=lambda *a: None, check=lambda: None, add_cost=lambda usd, tokens: None, max_submits=8)
    assert len(tries) == 3 and stuck.value.terminal and "invalid token" in str(stuck.value)  # 3 tries, not 8; no automatic new attempt


def test_build_goes_back_to_seed_when_adaptation_is_blocked_by_sign_in_errors():
    from types import SimpleNamespace

    from rehearsal.compiler.pipeline import Compiler

    ck = {"done": ["inspect", "plan", "materialize", "discover", "seed"], "seed": {"steps": [{"path": "/login"}], "roles": [{"name": "admin"}], "vars": {"t": "x"}},
          "rejected": {"adapter": {"args": {}, "error": "old"}}}
    c = SimpleNamespace(ck=ck, save=lambda: None, log=lambda *a: None)
    assert Compiler._rewind(c, "adapt", "adapter: the same problem came back 3 times; last reason: get_user -> FAILED 401 invalid token") is True
    assert "seed" not in ck["done"] and "seed" not in ck and "adapter" not in ck["rejected"]
    assert ck["rejected"]["seeder"]["args"]["steps"] == [{"path": "/login"}] and "invalid token" in ck["rejected"]["seeder"]["error"]
    ck["seed"] = {"steps": [], "roles": [], "vars": {}}
    assert Compiler._rewind(c, "adapt", "401 invalid token") is False  # once per build
    assert Compiler._rewind(SimpleNamespace(ck={"seed": {}}, save=None, log=None), "adapt", "you submitted 48 tools; submit between 3 and 40") is False


def _lanes_compiler(monkeypatch, parallel):
    import threading
    from types import SimpleNamespace

    from rehearsal.compiler import pipeline

    monkeypatch.setattr(pipeline, "settings", lambda: SimpleNamespace(build_parallel=parallel))
    made, destroyed = [], []

    def create(*a, **k):
        inst = SimpleNamespace(record=SimpleNamespace(to_json=lambda: {"instance_id": f"lane{len(made)}"}))
        made.append(inst)
        return inst

    monkeypatch.setattr(pipeline.WorldInstance, "create", create)
    c = pipeline.Compiler.__new__(pipeline.Compiler)
    c.ck, c._lock, c._save = {"secrets": {}, "base_snapshot": "/snap"}, threading.RLock(), lambda ck: None
    main = SimpleNamespace(name="main")
    c.instance, c.manifest, c.world_key, c.log = (lambda: main), (lambda: None), (lambda: "k"), (lambda *a: None)
    c.app, c.destroy = SimpleNamespace(source_dir=None), destroyed.append
    return c, main, made, destroyed


def test_scenarios_are_checked_several_at_a_time_each_in_its_own_sandbox(monkeypatch):
    import threading

    c, main, made, destroyed = _lanes_compiler(monkeypatch, parallel=3)
    together, seen = threading.Barrier(3, timeout=5), []

    def work(item, sandbox):
        if item < 3:
            together.wait()  # fails unless three scenarios really run at the same time
        seen.append((item, sandbox))

    c._in_parallel(list(range(7)), work, own_sandbox=True)
    assert sorted(i for i, _ in seen) == list(range(7))
    assert len(made) == 2 and {id(s) for _, s in seen} <= {id(main), *map(id, made)}  # main plus two copies
    assert destroyed == made and "lanes" not in c.ck  # copies are always removed


def test_a_stop_in_one_lane_stops_the_others_and_still_cleans_up(monkeypatch):
    c, main, made, destroyed = _lanes_compiler(monkeypatch, parallel=2)
    done = []

    def work(item, sandbox):
        if item == 0:
            raise KeyboardInterrupt("pause requested")
        done.append(item)

    with pytest.raises(KeyboardInterrupt):
        c._in_parallel(list(range(50)), work, own_sandbox=True)
    assert len(done) < 49 and destroyed == made


def test_plan_rules_catch_a_mix_the_writers_cannot_fix_later():
    from rehearsal.compiler.pipeline import plan_problems

    def brief(i, family, split, revises=True):
        return {"id": f"job_{i}", "title": "t", "family": family, "split": split, "brief": "b", "revises_goal": revises}

    good = [brief(1, "a", "train"), brief(2, "a", "train"), brief(3, "b", "dev"), brief(4, "c", "holdout")]
    assert plan_problems(good, 4) == []
    bad = [brief(1, "a", "train"), brief(1, "a", "dev", False), brief(3, "b", "dev", False), brief(4, "b", "dev", False)]
    found = " ".join(plan_problems(bad, 4))
    for expected in ("duplicate ids", "three families", "more than one split", "no holdout", "revise the goal"):
        assert expected in found
