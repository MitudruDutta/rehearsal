"""Episode persistence and limit checks with mocked policies and gateway calls."""

import copy
import json
from types import SimpleNamespace

import pytest

from rehearsal.agents import episode as ep
from rehearsal.agents.llm import LLMError, LLMReply, ToolCall
from rehearsal.core.contracts import (
    ActorSpec, AgentProfile, CheckSpec, GoalVersion, OracleResult, ParticipantSpec,
    RoleSpec, ScenarioSpec, ServiceSpec, ToolParam, ToolSpec, TrajectoryStep, WorldManifest,
)
from rehearsal.runner.gateway import GatewayResult


class Crash(BaseException):
    pass


class Snapshots(ep.MemoryRecorder):
    def __init__(self):
        super().__init__()
        self.snapshots = []
        self.saved_events = []

    def save(self, state):
        self.snapshots.append(copy.deepcopy(state.to_json()))
        self.saved_events = copy.deepcopy(self.events)


class BatchPolicy:
    def __init__(self, calls):
        self.calls = calls
        self.observed = []

    def next_turn(self, engine):
        calls, self.calls = self.calls, None
        return ("agent", calls) if calls is not None else None

    def observe(self, engine, actor, call, visible):
        self.observed.append((call.id, visible))
        ep.LLMPolicy.observe(self, engine, actor, call, visible)


def call(name="mutate", id="call-1", **args):
    return ToolCall(id, name, args, json.dumps(args))


@pytest.fixture
def make_engine(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected model call")

    monkeypatch.setattr(ep, "chat", forbidden)
    monkeypatch.setattr(ep.participant_mod, "reply", lambda *args, **kwargs: ("reply", 0.25, 7))

    def oracle(prober, journal, scenario, variables, goal_version, stats):
        return OracleResult(goal_version=goal_version, goal_satisfied=True, hard_constraint_violations=[],
                            check_results=[], model_cost_usd=stats.cost_usd, tokens=stats.tokens)

    monkeypatch.setattr(ep, "evaluate", oracle)
    manifest = WorldManifest(
        name="world", services=[ServiceSpec(name="app", image="test", port=80)],
        roles=[RoleSpec(name="staff", description="staff", customer_channel=True), RoleSpec(name="customer", description="customer")],
        tools=[ToolSpec(name=name, description=name, service="app", method="POST", path="/write", mutating=True,
                        roles=["staff", "customer"], params=[
                            ToolParam(name="content", location="body", schema={"type": "string"}, required=False),
                            ToolParam(name="value", location="body", schema={"type": "integer"}, required=False),
                        ]) for name in ("mutate", "post_customer")],
    )

    def make(policy=None, *, participant=None, max_steps=40, **kwargs):
        scenario = ScenarioSpec(
            id="scenario", title="Scenario", family="test", actors=[ActorSpec(id="agent", role="staff", instructions="act", can_complete=True)],
            participant=participant or ParticipantSpec(name="Customer", persona="test", opening_message="hello"),
            goals=[GoalVersion(version=1, instruction="do it", checks=["check"])],
            checks=[CheckSpec(id="check", description="check", query="SELECT 1")], reference=[], max_steps=max_steps,
        )
        recorder = kwargs.pop("recorder", Snapshots())
        engine = ep.Engine(episode_id="episode-test", instance=SimpleNamespace(journal=lambda: [], manifest=manifest), manifest=manifest,
                           scenario=scenario, variables={}, recorder=recorder,
                           policy=policy or BatchPolicy([call("complete")]), participant_mode="scripted", **kwargs)
        engine.dispatched = []

        engine.fault_free = []

        def execute(role, tool, args, op_id, *, allow_faults=True):
            engine.dispatched.append((role, tool, args, op_id))
            if not allow_faults:
                engine.fault_free.append(tool)
            return GatewayResult("SUCCEEDED", {"status": 200}, request={
                **engine.gateway.build_request(manifest.tool(tool), args), "operation_id": op_id, "role": role, "tool": tool,
            }, mutating=True)

        monkeypatch.setattr(engine.gateway, "execute", execute)
        return engine

    return make


def app_participant():
    return ParticipantSpec(name="Customer", persona="test", opening_message="hello", channel="app",
                           role="customer", send_tool="post_customer")


def tool_messages(engine):
    return [m for m in engine.state.actors["agent"].transcript if m["role"] == "tool"]


def test_pending_round_trip_and_legacy_default():
    state = ep.EpisodeState(pending={"c": {"actor": "agent", "call_id": "c", "tool": "mutate", "args": {}, "op_id": "op", "request": {}}})
    assert ep.EpisodeState.from_json(state.to_json()).pending == state.pending
    assert ep.EpisodeState.from_json({}).pending == {}


def test_batch_and_intent_are_durable_before_dispatch(make_engine, monkeypatch):
    policy = BatchPolicy([call(value=1), call("complete", id="done")])
    engine = make_engine(policy)
    dispatch = engine.gateway.execute

    def inspect(role, tool, args, op_id, **kwargs):
        saved = engine.recorder.snapshots[-1]
        intent = saved["pending"]["call-1"]
        assert intent == {"actor": "agent", "call_id": "call-1", "tool": "mutate", "args": {"value": 1},
                          "op_id": op_id, "request": {"method": "POST", "service": "app", "path": "/write", "query": {},
                          "json": {"value": 1}, "operation_id": op_id, "role": "staff", "tool": "mutate"}, "external": False}
        batch = next(m for m in saved["actors"]["agent"]["transcript"] if m["role"] == "assistant")
        assert [c["id"] for c in batch["tool_calls"]] == ["call-1", "done"]
        return dispatch(role, tool, args, op_id)

    monkeypatch.setattr(engine.gateway, "execute", inspect)
    engine.run()
    assert engine.state.pending == {}
    assert engine.recorder.snapshots[-1]["pending"] == {}


def test_observation_failure_keeps_pending(make_engine, monkeypatch):
    engine = make_engine(BatchPolicy([call()]))

    def fail(*args):
        assert "call-1" in engine.state.pending
        raise Crash()

    monkeypatch.setattr(engine.policy, "observe", fail)
    with pytest.raises(Crash):
        engine.run()
    assert len(engine.dispatched) == 1
    assert "call-1" in engine.recorder.snapshots[-1]["pending"]
    assert not tool_messages(engine)


def test_script_cursor_prevents_crash_replay(make_engine, monkeypatch):
    steps = [TrajectoryStep(actor="agent", tool="mutate"), TrajectoryStep(actor="agent", tool="complete")]
    engine = make_engine(ep.ScriptedPolicy(steps))
    effects = []

    def crash(*args):
        effects.append(args)
        assert engine.recorder.snapshots[-1]["script_pos"] == 1
        raise Crash()

    monkeypatch.setattr(engine.gateway, "execute", crash)
    with pytest.raises(Crash):
        engine.run()
    restored = ep.EpisodeState.from_json(engine.recorder.snapshots[-1])
    assert restored.pending["s1"]["tool"] == "mutate"
    # Recorder recovery owns unknown observations; emulate its completed handoff.
    restored.actors["agent"].transcript.append({"role": "tool", "tool_call_id": "s1", "content": '{"error":"outcome unknown"}'})
    restored.pending.clear()
    resumed = make_engine(ep.ScriptedPolicy(steps), state=restored)
    resumed.run()
    assert len(effects) == 1
    assert resumed.dispatched == []
    assert resumed.state.completed
    assert resumed.state.script_pos == 2


@pytest.mark.parametrize("stop", ["max_steps", "completed", "budget"])
def test_inner_batch_limits_answer_every_call(stop, make_engine, monkeypatch):
    first = call("complete") if stop == "completed" else call()
    policy = BatchPolicy([first, call(id="second"), call(id="third")])
    engine = make_engine(policy, max_steps=1 if stop == "max_steps" else 40, max_cost_usd=1 if stop == "budget" else None)
    dispatch = engine.gateway.execute

    def spend(*args):
        result = dispatch(*args)
        engine.state.cost_usd = 1
        return result

    if stop == "budget":
        monkeypatch.setattr(engine.gateway, "execute", spend)
    engine.run()
    assert engine.state.termination == stop
    assert engine.state.step == 1
    assert len(engine.dispatched) == (0 if stop == "completed" else 1)
    assert [m["tool_call_id"] for m in tool_messages(engine)] == ["call-1", "second", "third"]
    assert all(json.loads(m["content"])["skipped"] for m in tool_messages(engine)[1:])
    assert engine.state.pending == {}


def test_llm_cost_at_limit_skips_entire_batch_and_saves_usage(make_engine, monkeypatch):
    engine = make_engine(ep.LLMPolicy(AgentProfile(name="test"), "test:model"), max_cost_usd=1)
    checks = []
    engine.check = lambda: checks.append("check")

    def chat(*args, **kwargs):
        assert checks[-1] == "check"
        assert kwargs["check"] is engine.check
        return LLMReply("decision", [call(), call(id="second")], "test", "model", prompt_tokens=10, completion_tokens=5, cost_usd=1)

    monkeypatch.setattr(ep, "chat", chat)
    result = engine.run()
    assert engine.dispatched == []
    assert engine.state.step == 0
    assert engine.state.termination == "budget"
    assert result.model_cost_usd == 1
    assert result.tokens == 15
    assert len(tool_messages(engine)) == 2
    assert engine.recorder.snapshots[-1]["cost_usd"] == 1


def test_llm_unavailable_termination_is_saved(make_engine, monkeypatch):
    engine = make_engine(ep.LLMPolicy(AgentProfile(name="test"), "test:model"))

    def unavailable(*args, **kwargs):
        raise LLMError("offline")

    monkeypatch.setattr(ep, "chat", unavailable)
    engine.run()
    assert engine.recorder.snapshots[-1]["termination"] == "environment_error"
    assert engine.dispatched == []


def test_check_stops_before_policy(make_engine):
    engine = make_engine()

    def cancelled():
        raise Crash()

    engine.check = cancelled
    with pytest.raises(Crash):
        engine.run()
    assert engine.dispatched == []
    assert engine.state.step == 0


def test_external_polls_are_checked(make_engine, monkeypatch):
    polls = []
    policy = ep.ExternalPolicy(AgentProfile(name="external"), lambda actor: polls.append(actor), lambda *args: None)
    engine = make_engine(policy)
    engine.state.actors["agent"].waiting = False

    def check():
        if polls:
            raise Crash()

    engine.check = check
    monkeypatch.setattr(ep.time, "sleep", lambda seconds: None)
    with pytest.raises(Crash):
        policy.next_turn(engine)
    assert polls == ["agent"]


def test_external_call_has_assistant_batch_and_intent(make_engine, monkeypatch):
    published = []
    policy = ep.ExternalPolicy(AgentProfile(name="external"), lambda actor: {"idempotency_key": "external-id", "tool": "mutate"},
                               lambda *args: published.append(args))
    engine = make_engine(policy, max_steps=1)
    dispatch = engine.gateway.execute

    def inspect(*args):
        assert engine.recorder.snapshots[-1]["pending"]["external-id"]["external"] is True
        batch = engine.recorder.snapshots[-1]["actors"]["agent"]["transcript"][-1]
        assert batch["tool_calls"][0]["id"] == "external-id"
        return dispatch(*args)

    monkeypatch.setattr(engine.gateway, "execute", inspect)
    engine.run()
    assert [t for t, _ in published] == ["external.turn", "external.action.result"]
    assert engine.state.pending == {}


def test_nested_customer_post_keeps_outer_intent(make_engine, monkeypatch):
    engine = make_engine(BatchPolicy([call(), call("complete", id="done")]), participant=app_participant())
    engine.scenario.contact_tools = ["mutate"]
    dispatch = engine.gateway.execute
    nested = []

    def inspect(role, tool, args, op_id, **kwargs):
        pending = engine.recorder.snapshots[-1]["pending"]
        if role == "customer" and "call-1" in pending:
            nested.append(copy.deepcopy(pending))
            customer = pending[f"customer:{op_id}"]
            assert customer["actor"] == "customer"
            assert customer["request"]["operation_id"] == op_id
            assert op_id != pending["call-1"]["op_id"]
        return dispatch(role, tool, args, op_id)

    monkeypatch.setattr(engine.gateway, "execute", inspect)
    engine.run()
    assert len(nested) == 1
    assert len(nested[0]) == 2
    assert engine.state.pending == {}
    assert len({a[3] for a in engine.dispatched}) == 3


def test_crash_in_customer_post_preserves_both_intents(make_engine, monkeypatch):
    engine = make_engine(BatchPolicy([call()]), participant=app_participant())
    engine.scenario.contact_tools = ["mutate"]
    dispatch = engine.gateway.execute

    def crash(role, *args, **kwargs):
        if role == "customer" and "call-1" in engine.state.pending:
            raise Crash()
        return dispatch(role, *args)

    monkeypatch.setattr(engine.gateway, "execute", crash)
    with pytest.raises(Crash):
        engine.run()
    saved = engine.recorder.snapshots[-1]
    assert len(saved["pending"]) == 2
    assert saved["pending"]["call-1"]["actor"] == "agent"
    assert saved["cost_usd"] == 0.25
    assert saved["tokens"] == 7


def test_opening_customer_post_is_saved_before_dispatch(make_engine, monkeypatch):
    engine = make_engine(participant=app_participant())

    def crash(*args, **kwargs):
        saved = engine.recorder.snapshots[-1]
        assert saved["opened"] is True
        assert len(saved["pending"]) == 1
        assert next(iter(saved["pending"].values()))["actor"] == "customer"
        raise Crash()

    monkeypatch.setattr(engine.gateway, "execute", crash)
    with pytest.raises(Crash):
        engine.run()


def test_participant_budget_blocks_nested_app_dispatch(make_engine, monkeypatch):
    engine = make_engine(BatchPolicy([call(), call(id="second")]), participant=app_participant(), max_cost_usd=0.25)
    engine.scenario.contact_tools = ["mutate"]
    checks = []
    engine.check = lambda: checks.append("check")

    def reply(*args, **kwargs):
        assert checks[-1] == "check"
        assert kwargs["check"] is engine.check
        return "paid reply", 0.25, 7

    monkeypatch.setattr(ep.participant_mod, "reply", reply)
    engine.run()
    assert [x[1] for x in engine.dispatched] == ["post_customer", "mutate"]
    assert engine.state.termination == "budget"
    assert engine.recorder.snapshots[-1]["cost_usd"] == 0.25
    assert engine.recorder.snapshots[-1]["tokens"] == 7
    assert len(tool_messages(engine)) == 2
    assert engine.state.pending == {}


def test_participant_is_not_called_when_budget_already_reached(make_engine, monkeypatch):
    engine = make_engine(max_cost_usd=1)
    engine.state.cost_usd = 1

    def forbidden(*args, **kwargs):
        raise AssertionError("participant exceeds budget")

    monkeypatch.setattr(ep.participant_mod, "reply", forbidden)
    assert engine._contact("agent", "hello", "customer") == {"delivered": True}
    assert engine.state.termination == "budget"


def test_paid_participant_usage_saved_before_cancellation(make_engine, monkeypatch):
    engine = make_engine(BatchPolicy([call()]), participant=app_participant())
    engine.scenario.contact_tools = ["mutate"]

    def check():
        if engine.state.cost_usd:
            assert engine.recorder.snapshots[-1]["cost_usd"] == 0.25
            assert engine.recorder.snapshots[-1]["tokens"] == 7
            raise Crash()

    engine.check = check
    with pytest.raises(Crash):
        engine.run()
    assert [x[1] for x in engine.dispatched] == ["post_customer", "mutate"]
    assert "call-1" in engine.recorder.snapshots[-1]["pending"]


@pytest.mark.parametrize("reason", ["max_steps", "budget"])
def test_direct_execute_respects_limits(reason, make_engine):
    engine = make_engine(max_steps=0 if reason == "max_steps" else 40, max_cost_usd=0 if reason == "budget" else None)
    assert engine.execute("agent", call())["skipped"] is True
    assert engine.dispatched == []
    assert engine.state.step == 0


@pytest.mark.parametrize("failure", ["journal", "oracle"])
def test_finish_failure_preserves_usage_and_flushes_event(failure, make_engine, monkeypatch):
    engine = make_engine()
    engine.state.cost_usd = 1.75
    engine.state.tokens = 123

    def fail(*args):
        raise RuntimeError("oracle offline")

    if failure == "journal":
        engine.instance.journal = fail
    else:
        monkeypatch.setattr(ep, "evaluate", fail)
    result = engine.finish()
    assert result.model_cost_usd == 1.75
    assert result.tokens == 123
    assert "oracle offline" in result.environment_error
    assert engine.recorder.saved_events[-1]["type"] == "episode.finished"
    assert engine.recorder.saved_events[-1]["data"]["oracle"]["model_cost_usd"] == 1.75


def test_successful_finish_event_is_saved(make_engine):
    engine = make_engine()
    result = engine.run()
    assert result.environment_error is None
    assert engine.recorder.saved_events[-1]["type"] == "episode.finished"


def test_failed_intent_save_prevents_side_effect(make_engine, monkeypatch):
    engine = make_engine(BatchPolicy([call()]))
    save = engine.recorder.save

    def fail(state):
        if state.pending:
            raise Crash()
        save(state)

    monkeypatch.setattr(engine.recorder, "save", fail)
    with pytest.raises(Crash):
        engine.run()
    assert engine.dispatched == []
    assert engine.recorder.snapshots[-1]["pending"] == {}
    assert engine.recorder.snapshots[-1]["actors"]["agent"]["transcript"][-1]["tool_calls"][0]["id"] == "call-1"


def test_callback_after_intent_prevents_dispatch(make_engine):
    engine = make_engine(BatchPolicy([call()]))

    def check():
        if engine.state.pending:
            assert "call-1" in engine.recorder.snapshots[-1]["pending"]
            raise Crash()

    engine.check = check
    with pytest.raises(Crash):
        engine.run()
    assert engine.dispatched == []
    assert engine.state.step == 1


def test_retry_persists_original_request_before_replay(make_engine, monkeypatch):
    engine = make_engine(BatchPolicy([call("retry_operation", operation_id="original"), call("complete", id="done")]))
    request = {"method": "POST", "service": "app", "path": "/write", "query": {}, "json": {"value": 1},
               "operation_id": "original", "role": "staff", "tool": "mutate"}
    engine.state.ops["original"] = {"actor": "agent", "request": request}
    checks = []
    engine.check = lambda: checks.append("check")
    replays = []

    def replay(saved_request):
        assert checks[-1] == "check"
        intent = engine.recorder.snapshots[-1]["pending"]["call-1"]
        assert intent["request"] == request
        assert intent["op_id"] == "original"
        replays.append(saved_request)
        return GatewayResult("SUCCEEDED", {"status": 200}, request=request, mutating=True)

    monkeypatch.setattr(engine.gateway, "replay", replay)
    engine.run()
    assert replays == [request]
    assert engine.recorder.actions[0]["operation_id"] == "original-r1"
    assert engine.state.pending == {}


def test_intervention_poll_checks_lease(make_engine):
    engine = make_engine()
    events = []
    engine.check = lambda: events.append("check")
    engine.recorder.poll_interventions = lambda: events.append("poll") or []
    engine._interventions()
    assert events == ["check", "poll"]


def test_overshooting_participant_cost_is_preserved(make_engine, monkeypatch):
    engine = make_engine(BatchPolicy([call(), call(id="second")]), participant=app_participant(), max_cost_usd=0.25)
    engine.scenario.contact_tools = ["mutate"]
    monkeypatch.setattr(ep.participant_mod, "reply", lambda *args, **kwargs: ("paid reply", 0.4, 9))
    result = engine.run()
    assert result.model_cost_usd == 0.4
    assert result.tokens == 9
    assert [x[1] for x in engine.dispatched] == ["post_customer", "mutate"]
    assert engine.state.termination == "budget"
    assert engine.state.pending == {}


def test_scheduled_change_of_mind_is_delivered_before_a_live_agents_first_write(make_engine):
    """A change scheduled by step count must not land after an irreversible write: the write is held,
    the customer's new request is delivered, and the agent decides again."""
    from rehearsal.core.contracts import EventAction, ScheduledEvent, Trigger

    policy = BatchPolicy([call("mutate", id="w1"), call("mutate", id="w2")])
    engine = make_engine(policy)
    engine.scenario = engine.scenario.model_copy(update={
        "goals": [GoalVersion(version=1, instruction="merge it", checks=["check"]), GoalVersion(version=2, instruction="do not merge", checks=["check"])],
        "events": [ScheduledEvent(id="change", trigger=Trigger(kind="at_step", step=5), actions=[EventAction(kind="goal_change", goal_version=2, text="Stop, do not merge.")])],
    })
    engine.run()
    assert engine.state.goal_version == 2 and "change" in engine.state.fired
    assert [d[1] for d in engine.dispatched if d[0] == "staff"] == []  # neither write ran
    held = [v for _, v in policy.observed if v.get("not_executed")]
    assert len(held) == 2 and "new message from the customer" in held[0]["reason"]


def test_scripted_replays_keep_exact_step_timing(make_engine):
    from rehearsal.core.contracts import EventAction, ScheduledEvent, Trigger, TrajectoryStep

    engine = make_engine()
    engine.scenario = engine.scenario.model_copy(update={
        "goals": [GoalVersion(version=1, instruction="a", checks=["check"]), GoalVersion(version=2, instruction="b", checks=["check"])],
        "events": [ScheduledEvent(id="change", trigger=Trigger(kind="at_step", step=5), actions=[EventAction(kind="goal_change", goal_version=2, text="b")])],
    })
    engine.policy = ep.ScriptedPolicy([TrajectoryStep(actor="agent", tool="mutate", args={})])
    assert engine._hold_for_revision("agent", call("mutate")) is None and "change" not in engine.state.fired


def test_timeout_on_a_write_is_armed_before_a_live_agents_first_use(make_engine):
    from rehearsal.core.contracts import EventAction, ScheduledEvent, Trigger

    engine = make_engine(BatchPolicy([call("complete")]))
    engine.scenario = engine.scenario.model_copy(update={
        "events": [ScheduledEvent(id="timeout", trigger=Trigger(kind="after_tool", tool="mutate"), actions=[EventAction(kind="fault", tool="mutate", fault_mode="drop_response")])],
    })
    engine.run()
    assert "timeout" in engine.state.fired and engine.gateway.faults.get("mutate") == ["drop_response"]


def test_injected_timeout_is_never_spent_on_the_customers_own_post(make_engine):
    engine = make_engine(BatchPolicy([call(), call("complete", id="done")]), participant=app_participant())
    engine.run()
    posts = [tool for _, tool, _, _ in engine.dispatched if tool == "post_customer"]
    assert posts and engine.fault_free == posts


def test_idle_live_agent_still_receives_the_scheduled_goal_change(make_engine):
    from rehearsal.core.contracts import EventAction, ScheduledEvent, Trigger

    engine = make_engine(BatchPolicy(None))  # the agent never acts
    engine.scenario = engine.scenario.model_copy(update={
        "goals": [GoalVersion(version=1, instruction="a", checks=["check"]), GoalVersion(version=2, instruction="b", checks=["check"])],
        "events": [ScheduledEvent(id="change", trigger=Trigger(kind="at_step", step=5), actions=[EventAction(kind="goal_change", goal_version=2, text="b")])],
    })
    engine.run()
    assert "change" in engine.state.fired and engine.state.goal_version == 2 and engine.state.termination == "stalled"


def test_customer_with_nothing_to_add_posts_nothing(make_engine, monkeypatch):
    engine = make_engine(BatchPolicy([call()]), participant=app_participant())
    monkeypatch.setattr(ep.participant_mod, "reply", lambda *args, **kwargs: ("", 0.0, 3))  # the customer stays silent
    posts_before = len(engine.dispatched)
    assert engine._contact("agent", "Thanks, I will follow up.", None) == {"delivered": True}
    assert len(engine.dispatched) == posts_before and engine.state.tokens == 3


def test_checks_can_tell_this_episode_from_seeded_records(make_engine):
    engine = make_engine()
    engine.run()
    v = engine.variables
    assert v["episode_started_ms"] // 1000 == v["episode_started_s"] and v["episode_started_at"].endswith("+00:00")


def _audit(monkeypatch, make_engine, *, reward, verdict):
    """Runs validation.live_audit with a fake episode outcome and a fake auditor reply."""
    from rehearsal.compiler import validation

    engine = make_engine()
    result = OracleResult(goal_version=1, goal_satisfied=reward > 0, hard_constraint_violations=[], model_cost_usd=0, tokens=0,
                          check_results=[{"id": "reply", "passed": reward > 0, "actual": 0, "op": ">=", "expected": 1}])
    monkeypatch.setattr(validation, "prepare", lambda *a, **k: {})
    monkeypatch.setattr(validation.Engine, "run", lambda self: result)
    monkeypatch.setattr(validation, "chat_json", lambda *a, **k: (verdict, SimpleNamespace(cost_usd=0.01, prompt_tokens=5, completion_tokens=5)))
    spent = []
    out = validation.live_audit(SimpleNamespace(journal=lambda: []), engine.manifest, None, {}, engine.scenario, agent_chain="local:m",
                                auditor_chain="local:m", add_cost=lambda usd, tokens: spent.append(usd))
    return out, spent


def test_job_passed_by_a_live_agent_needs_no_auditor(make_engine, monkeypatch):
    out, spent = _audit(monkeypatch, make_engine, reward=1, verdict=None)
    assert out["passed"] and out["cause"] is None and len(spent) == 1  # only the episode was paid for


def test_auditor_separates_an_unfair_check_from_an_agent_mistake(make_engine, monkeypatch):
    from rehearsal.compiler.validation import UNFAIR

    unfair, _ = _audit(monkeypatch, make_engine, reward=-1, verdict={"cause": "check", "evidence": "reply was under the live message", "fix": "count replies since :episode_started_ms"})
    assert unfair["cause"] in UNFAIR and "live message" in unfair["evidence"] and unfair["failed_checks"][0]["id"] == "reply"
    fair, _ = _audit(monkeypatch, make_engine, reward=-1, verdict={"cause": "agent", "evidence": "it never posted"})
    assert fair["cause"] == "agent"
    odd, _ = _audit(monkeypatch, make_engine, reward=-1, verdict={"cause": "maybe"})
    assert odd["cause"] == "inconclusive"  # an unusable verdict never blocks or blesses a job by itself


def test_custom_prompt_with_braces_and_no_placeholder_still_gets_the_job_instructions(make_engine):
    engine = make_engine()
    policy = ep.LLMPolicy(ep.AgentProfile(name="mine", system_prompt='Answer as JSON like {"ok": true}.'), "local:m")
    text = policy.system_prompt(engine, engine.state.actors["agent"])
    assert text.startswith('Answer as JSON like {"ok": true}.') and "Your assignment: act" in text



def test_every_evaluation_episode_is_stress_tested_by_default(make_engine):
    from rehearsal.core.contracts import EventAction, ScheduledEvent, TrajectoryStep, Trigger

    def engine_with(events=(), policy=None, stress=True):
        eng = make_engine(policy or BatchPolicy([call("complete")]), default_stress=stress)
        eng.scenario = eng.scenario.model_copy(update={"reference": [TrajectoryStep(actor="agent", tool="mutate", args={})], "events": list(events)})
        return eng

    plain = engine_with()
    plain.run()
    assert plain.gateway.faults.get("mutate") == ["rate_limit"]  # refused once, not carried out; a careful agent retries
    timeout = ScheduledEvent(id="t", trigger=Trigger(kind="at_step", step=0), actions=[EventAction(kind="fault", tool="mutate", fault_mode="drop_response")])
    own = engine_with([timeout])
    own.run()
    assert "rate_limit" not in (own.gateway.faults.get("mutate") or [])  # the job's own stress is kept as written
    replay = engine_with(policy=ep.ScriptedPolicy([TrajectoryStep(actor="agent", tool="complete", args={"summary": "x"})]))
    replay.run()
    assert not replay.gateway.faults.get("mutate")  # validation replays stay exact
    off = engine_with(stress=False)
    off.run()
    assert not off.gateway.faults.get("mutate")



def test_customer_repeats_the_request_once_after_the_first_change_by_default(make_engine):
    from rehearsal.core.contracts import GoalVersion

    def run(goals=None, stress=True):
        eng = make_engine(BatchPolicy([call("mutate"), call("complete", id="done")]), participant=app_participant(), default_stress=stress)
        if goals:
            eng.scenario = eng.scenario.model_copy(update={"goals": goals})
        eng.run()
        return [args.get("content") for _, tool, args, _ in eng.dispatched if tool == "post_customer"]

    posts = run()
    assert posts[0] == "hello" and len(posts) == 2 and posts[1].startswith("Did my request go through?") and posts[1].endswith("hello")
    two_versions = [GoalVersion(version=1, instruction="a", checks=["check"]), GoalVersion(version=2, instruction="b", checks=["check"])]
    assert run(goals=two_versions) == ["hello"]  # never contradicts a job whose request changes
    assert run(stress=False) == ["hello"]
