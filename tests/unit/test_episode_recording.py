"""Recorder commits and crash recovery without services, files, or network."""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from rehearsal.agents.episode import ActorState, EpisodeState
from rehearsal.db.models import Episode
from rehearsal.db.queue import LeaseLost
from rehearsal.worker import evaluate as ev


@pytest.fixture
def store(monkeypatch):
    db = NS(ep=NS(state={}, cost_usd=0.0, tokens=0),
            job=NS(spent_usd=0.0, tokens=0, checkpoint={}), rows=[], fail=False)

    @contextmanager
    def transaction():
        working = NS(ep=deepcopy(db.ep), job=deepcopy(db.job), rows=list(db.rows))
        s = NS(get=lambda model, key: working.ep, add=working.rows.append)
        s.job = working.job
        yield s
        if db.fail:
            raise RuntimeError("commit failed")
        db.ep, db.job, db.rows = working.ep, working.job, working.rows

    monkeypatch.setattr(ev, "session", transaction)
    monkeypatch.setattr(ev, "emit", lambda s, **kw: s.add(kw))
    def record_spend(s, job, usd, tokens=0):
        job.spent_usd += usd
        job.tokens += tokens
    monkeypatch.setattr(ev.queue, "record_spend", record_spend)  # ledger persistence has its own database tests
    db.ctx = NS(spent=0.0, owned=lambda s: s.job)
    return db


def test_repeated_save_charges_usage_once(store):
    recorder = ev.DBRecorder("p", "r", "e", ctx=store.ctx)
    recorder.event("test", "buffered")
    state = EpisodeState(cost_usd=0.125, tokens=12)
    recorder.save(state)
    recorder.save(state)
    assert (store.job.spent_usd, store.job.tokens, store.ctx.spent) == (0.125, 12, 0.125)
    assert len(store.rows) == 1 and recorder.pending == []
    state.cost_usd, state.tokens = 0.25, 21
    recorder.save(state)
    assert (store.job.spent_usd, store.job.tokens, store.ctx.spent) == (0.25, 21, 0.25)


def test_commit_failure_keeps_buffers_and_spend_for_retry(store):
    recorder = ev.DBRecorder("p", "r", "e", ctx=store.ctx)
    recorder.event("test", "buffered")
    state = EpisodeState(cost_usd=0.25, tokens=20)
    store.fail = True
    with pytest.raises(RuntimeError, match="commit failed"):
        recorder.save(state)
    assert len(recorder.pending) == 1
    assert store.ctx.spent == store.job.spent_usd == store.ep.cost_usd == 0
    assert store.rows == [] and store.ep.state == {}
    store.fail = False
    recorder.save(state)
    assert store.ctx.spent == 0.25 and len(store.rows) == 1


def test_lost_ownership_writes_nothing(store):
    store.ctx.owned = Mock(side_effect=LeaseLost("replaced"))
    recorder = ev.DBRecorder("p", "r", "e", ctx=store.ctx)
    recorder.event("test", "buffered")
    with pytest.raises(LeaseLost):
        recorder.save(EpisodeState(cost_usd=1, tokens=8))
    assert store.ep.state == {} and store.rows == []
    assert store.ctx.spent == 0 and len(recorder.pending) == 1


def test_external_poll_consumes_only_returned_call(monkeypatch):
    recorder = ev.DBRecorder("p", "r", "e")
    rows = [NS(id=n, data={"actor": "a", "idempotency_key": str(n)}) for n in (1, 2, 3)]
    monkeypatch.setattr(recorder, "_poll", lambda kind: [r for r in rows if r.id > recorder.cursor[kind]])
    assert [recorder.poll_external("a")["idempotency_key"] for _ in rows] == ["1", "2", "3"]
    assert recorder.poll_external("a") is None


def test_poll_does_not_advance_cursor(monkeypatch):
    recorder = ev.DBRecorder("p", "r", "e")
    row = NS(id=7)
    @contextmanager
    def transaction():
        yield NS(scalars=lambda query: [row], expunge=lambda obj: None)
    monkeypatch.setattr(ev, "session", transaction)
    assert recorder._poll("external.action.submitted") == [row]
    assert recorder.cursor["external.action.submitted"] == 0


def test_recovery_closes_partial_batch_once_and_consumes_intent(store):
    actor = ActorState("a", "agent", transcript=[
        {"role": "assistant", "tool_calls": [
            {"id": c, "function": {"name": "change"}} for c in ("done", "flight", "unstarted")]},
        {"role": "tool", "tool_call_id": "done", "content": "ok"},
    ])
    request = {"operation_id": "op1", "tool": "change"}
    state = EpisodeState(actors={"a": actor}, pending={"flight": {
        "actor": "a", "call_id": "flight", "tool": "change", "args": {}, "op_id": "op1", "request": request}})
    recorder = ev.DBRecorder("p", "r", "e", ctx=store.ctx)
    ev._close_dangling_calls(state, recorder, external=True)
    assert state.pending == {} and state.ops["op1"]["request"] == request
    assert [m["tool_call_id"] for m in actor.transcript if m["role"] == "tool"] == ["done", "flight", "unstarted"]
    published = [r for kind, r in recorder.pending if r.get("type") == "external.action.result"]
    assert [r["data"]["idempotency_key"] for r in published] == ["flight", "unstarted"]
    recorder.save(state)
    restored = EpisodeState.from_json({k: v for k, v in store.ep.state.items() if k != "event_cursor"})
    ev._close_dangling_calls(restored, recorder, external=True)
    assert recorder.pending == []


def test_pending_external_without_transcript_returns_original_call_id(store):
    state = EpisodeState(actors={"a": ActorState("a", "agent")}, pending={"original": {
        "actor": "a", "call_id": "original", "tool": "change", "args": {}, "op_id": "op1", "request": {}}})
    recorder = ev.DBRecorder("p", "r", "e", ctx=store.ctx)
    ev._close_dangling_calls(state, recorder, external=True)
    assert state.pending == {}
    assert recorder.pending[-1][1]["data"]["idempotency_key"] == "original"


@pytest.mark.parametrize("state,claim", [({}, "e"), ({"opened": True}, None)])
def test_running_without_resumable_claim_fails_closed(monkeypatch, state, claim):
    ep = NS(id="e", status="running", state=state, instance={}, scenario_id="sc", profile_id=None,
            run_id="r", project_id="p")
    @contextmanager
    def transaction():
        yield NS(get=lambda model, key: ep if model is Episode else NS(spec={}))
    monkeypatch.setattr(ev, "session", transaction)
    monkeypatch.setattr(ev.ScenarioSpec, "model_validate", lambda value: NS())
    monkeypatch.setattr(ev, "_max_event", lambda run: 0)
    finish = Mock()
    monkeypatch.setattr(ev, "_finish_error", finish)
    ctx = NS(owned=lambda s: None, checkpoint={"current_episode": claim})
    inst = NS(restore=Mock(side_effect=AssertionError("must not reset")))
    assert ev.run_episode(ctx, inst, None, {}, "e") is None
    finish.assert_called_once()
    inst.restore.assert_not_called()


def test_cleanup_lost_lease_does_not_destroy(store):
    store.ctx.owned = Mock(side_effect=LeaseLost("replaced"))
    inst = NS(record=NS(instance_id="old"), destroy=Mock())
    with pytest.raises(LeaseLost):
        ev._destroy_owned(store.ctx, inst, clear=True)
    inst.destroy.assert_not_called()


def test_cleanup_replacement_instance_is_untouched(store):
    store.job.checkpoint = {"instance": {"instance_id": "replacement"}}
    inst = NS(record=NS(instance_id="old"), destroy=Mock())
    with pytest.raises(LeaseLost):
        ev._destroy_owned(store.ctx, inst, clear=True)
    inst.destroy.assert_not_called()


def test_aggregate_legacy_environment_errors_keeps_all_usage():
    rows = [NS(status="finished", oracle={"environment_error": "legacy failure", "goal_satisfied": True},
               cost_usd=0.5, tokens=20, reward=1),
            NS(status="error", oracle={}, cost_usd=0.25, tokens=10, reward=None),
            NS(status="finished", oracle={"goal_satisfied": True}, cost_usd=0.125, tokens=5, reward=1)]
    result = ev._agg(rows)
    assert (result["finished"], result["environment_errors"], result["successes"]) == (1, 2, 1)
    assert result["cost_usd"] == 0.875 and result["tokens"] == 35


def test_recovery_commits_before_engine_can_execute(store, monkeypatch):
    actor = ActorState("a", "agent", transcript=[{"role": "assistant", "tool_calls": [
        {"id": "call", "function": {"name": "change"}}]}])
    state = EpisodeState(actors={"a": actor}, pending={"call": {
        "actor": "a", "call_id": "call", "tool": "change", "args": {}, "op_id": "op", "request": {}}})
    store.ep = NS(id="e", status="running", state=state.to_json(), instance={"instance_id": "same", "vars": {}},
                  scenario_id="sc", profile_id=None, run_id="r", project_id="p", cost_usd=0, tokens=0, spec={})
    store.ctx.checkpoint = {"current_episode": "e"}
    store.ctx.payload = {}
    store.ctx.check = Mock()
    monkeypatch.setattr(ev.ScenarioSpec, "model_validate", lambda raw: NS(id="sc"))
    monkeypatch.setattr(ev, "settings", lambda: NS(model_agent="unused"))
    def engine(**kwargs):
        assert store.ep.state["pending"] == {}
        assert store.ep.state["actors"]["a"]["transcript"][-1]["tool_call_id"] == "call"
        assert len(store.rows) == 2  # unknown plus resumed, committed before constructor
        raise RuntimeError("engine reached")
    monkeypatch.setattr(ev, "Engine", engine)
    inst = NS(record=NS(instance_id="same"), restore=Mock())
    with pytest.raises(RuntimeError, match="engine reached"):
        ev.run_episode(store.ctx, inst, None, {}, "e")
    inst.restore.assert_not_called()


def test_failed_recovery_commit_prevents_engine_run(store, monkeypatch):
    store.ep = NS(id="e", status="running", state=EpisodeState().to_json(),
                  instance={"instance_id": "same", "vars": {}}, scenario_id="sc", profile_id=None,
                  run_id="r", project_id="p", cost_usd=0, tokens=0, spec={})
    store.ctx.checkpoint = {"current_episode": "e"}
    monkeypatch.setattr(ev.ScenarioSpec, "model_validate", lambda raw: NS())
    engine = Mock(side_effect=AssertionError("must not execute"))
    monkeypatch.setattr(ev, "Engine", engine)
    # Initial read transaction succeeds; recovery save transaction fails.
    original = ev.session
    count = 0
    @contextmanager
    def transaction():
        nonlocal count
        count += 1
        store.fail = count > 1
        with original() as s:
            yield s
    monkeypatch.setattr(ev, "session", transaction)
    with pytest.raises(RuntimeError, match="commit failed"):
        ev.run_episode(store.ctx, NS(record=NS(instance_id="same")), None, {}, "e")
    engine.assert_not_called()
    assert store.rows == [] and store.ctx.spent == 0


def test_finish_error_lost_ownership_writes_nothing(store):
    store.ctx.owned = Mock(side_effect=LeaseLost("replaced"))
    with pytest.raises(LeaseLost):
        ev._finish_error(store.ctx, "e", "failure")
    assert store.rows == [] and not hasattr(store.ep, "status")


def test_cleanup_commits_checkpoint_after_destroy(store):
    store.ctx.checkpoint = {"instance": {"instance_id": "same"}, "other": 1}
    store.job.checkpoint = deepcopy(store.ctx.checkpoint)
    inst = NS(record=NS(instance_id="same"), destroy=Mock())
    ev._destroy_owned(store.ctx, inst, clear=True)
    inst.destroy.assert_called_once()
    assert store.job.checkpoint == store.ctx.checkpoint == {"other": 1}


def test_pending_retry_keeps_original_operation_without_duplicate_action(store):
    from rehearsal.db.models import Action

    original = Action(episode_id="e", operation_id="original", seq=1, status="SUCCEEDED")
    store.rows.append(original)
    request = {"operation_id": "original", "tool": "change", "role": "agent"}
    actor = ActorState("a", "agent", waiting=True, transcript=[{"role": "assistant", "tool_calls": [
        {"id": "external-retry-id", "function": {"name": "retry_operation"}}]}])
    state = EpisodeState(step=3, action_seq=1, actors={"a": actor},
        ops={"original": {"actor": "a", "request": request}},
        pending={"external-retry-id": {"actor": "a", "call_id": "external-retry-id",
            "tool": "retry_operation", "args": {"operation_id": "original"},
            "op_id": "original", "request": request}})
    recorder = ev.DBRecorder("p", "r", "e", ctx=store.ctx)
    ev._close_dangling_calls(state, recorder, external=True)
    recorder.save(state)
    assert [r.operation_id for r in store.rows if isinstance(r, Action)] == ["original"]
    assert state.ops == {"original": {"actor": "a", "request": request}}
    assert state.pending == {} and state.action_seq == 1
    results = [r for r in store.rows if isinstance(r, dict) and r["type"] == "external.action.result"]
    assert len(results) == 1
    assert results[0]["data"]["idempotency_key"] == "external-retry-id"
    assert "unknown" in results[0]["data"]["result"]["error"]
    assert actor.waiting  # Recovery reports an outcome; scheduling remains Engine's job.
    ev._close_dangling_calls(state, recorder, external=True)
    assert recorder.pending == []
