"""Worker recovery boundaries with mocked transactions, threads, and model calls."""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from rehearsal import pricing
from rehearsal.agents import episode as ep
from rehearsal.agents.llm import LLMError
from rehearsal.db import queue
from rehearsal.db.models import Run
from rehearsal.evaluator.oracle import evaluate as evaluate_result
from rehearsal.runner.gateway import GatewayResult
from rehearsal.worker import context, evaluate as ev
from tests.unit.test_engine_recovery import app_participant, make_engine


@pytest.fixture
def heartbeat(monkeypatch):
    db = NS(commits=0, rollbacks=0, renewals=0, failure=None,
            cancel_requested=False, pause_requested=False)

    @contextmanager
    def transaction():
        s = NS(renewed=False)
        try:
            yield s
        except BaseException:
            db.rollbacks += 1
            raise
        else:
            db.commits += 1
            db.renewals += int(s.renewed)

    def renew(s, job_id, worker_id, attempt, *, check_commands=True):
        assert (job_id, worker_id, attempt) == ("job", "worker", 2)
        if db.failure:
            raise db.failure
        s.renewed = True
        if check_commands:
            if db.cancel_requested:
                raise queue.JobCancelled("cancel requested")
            if db.pause_requested:
                raise queue.JobPaused("pause requested")
        return db

    monkeypatch.setattr(context, "session", transaction)
    monkeypatch.setattr(context, "settings", lambda: NS(lease_seconds=60))
    db.renew = Mock(side_effect=renew)
    monkeypatch.setattr(queue, "heartbeat", db.renew)
    db.ctx = context.JobContext(NS(id="job", project_id="project", kind="evaluation",
        payload={}, checkpoint={}, budget_usd=None, spent_usd=0, attempts=2), "worker")
    db.ctx._halt = NS(wait=Mock(side_effect=[False, True]))
    return db


@pytest.mark.parametrize("mode", ["check", "beat"])
@pytest.mark.parametrize("cancel,pause,error", [
    (True, False, queue.JobCancelled),
    (False, True, queue.JobPaused),
    (True, True, queue.JobCancelled),
])
def test_commands_commit_renewal_before_propagating(heartbeat, mode, cancel, pause, error):
    heartbeat.cancel_requested, heartbeat.pause_requested = cancel, pause
    if mode == "beat":
        heartbeat.ctx._beat()
    with pytest.raises(error):
        heartbeat.ctx.check()
    assert isinstance(heartbeat.ctx._stop, error)
    assert (heartbeat.commits, heartbeat.renewals, heartbeat.rollbacks) == (1, 1, 0)
    heartbeat.renew.assert_called_once_with(
        heartbeat.renew.call_args.args[0], "job", "worker", 2, check_commands=False)


@pytest.mark.parametrize("mode", ["check", "beat"])
def test_lease_loss_still_stops_context(heartbeat, mode):
    heartbeat.failure = queue.LeaseLost("replacement owns claim")
    if mode == "beat":
        heartbeat.ctx._beat()
    with pytest.raises(queue.LeaseLost, match="replacement owns claim"):
        heartbeat.ctx.check()
    assert heartbeat.ctx._stop is heartbeat.failure
    assert (heartbeat.commits, heartbeat.renewals, heartbeat.rollbacks) == (0, 0, 1)


@pytest.mark.parametrize("budget,plans,allowance,required", [
    (None, False, 0, False), (0, False, 0, True),
    (1, False, 0, True), (None, True, 0, True), (None, False, 1, True),
])
@pytest.mark.parametrize("fails", [False, True])
def test_job_pricing_requirement_is_scoped(heartbeat, monkeypatch, budget, plans, allowance, required, fails):
    known = pricing.require_known_prices
    monkeypatch.setattr(context, "settings", lambda: NS(plans=plans, monthly_allowance_usd=allowance))
    heartbeat.ctx.budget = budget
    heartbeat.ctx._thread = Mock()
    heartbeat.ctx._halt = Mock()
    token = known.set(not required)
    try:
        try:
            with heartbeat.ctx:
                assert known.get() is required
                if fails:
                    raise RuntimeError("handler failed")
        except RuntimeError as exc:
            assert fails and str(exc) == "handler failed"
        assert known.get() is not required
        heartbeat.ctx._thread.start.assert_called_once_with()
        heartbeat.ctx._thread.join.assert_called_once_with(timeout=5)
    finally:
        known.reset(token)


@pytest.fixture
def spend(monkeypatch):
    db = NS(job=NS(spent_usd=0.0, tokens=0), ep=NS(state={}, cost_usd=0.0, tokens=0),
            ledger=[], fail=False)

    @contextmanager
    def transaction():
        s = NS(job=deepcopy(db.job), ep=deepcopy(db.ep), ledger=list(db.ledger))
        s.get = lambda model, key: s.ep
        yield s
        if db.fail:
            raise RuntimeError("commit failed")
        db.job, db.ep, db.ledger = s.job, s.ep, s.ledger

    def record(s, job, usd, tokens=0):
        assert job is s.job
        job.spent_usd += usd
        job.tokens += tokens
        if usd:
            s.ledger.append((usd, tokens))

    monkeypatch.setattr(context, "session", transaction)
    monkeypatch.setattr(ev, "session", transaction)
    db.record = Mock(side_effect=record)
    monkeypatch.setattr(queue, "record_spend", db.record)
    db.ctx = context.JobContext(NS(id="job", project_id="project", kind="evaluation",
        payload={}, checkpoint={}, budget_usd=1, spent_usd=0, attempts=2), "worker")
    db.ctx.owned = Mock(side_effect=lambda s: s.job)
    return db


@pytest.mark.parametrize("usd,tokens", [(0.25, 12), (0, 12)])
def test_context_records_spend_under_existing_ownership(spend, usd, tokens):
    spend.ctx.add_cost(usd, tokens)
    assert (spend.job.spent_usd, spend.job.tokens, spend.ctx.spent) == (usd, tokens, usd)
    assert spend.ledger == ([(usd, tokens)] if usd else [])
    spend.ctx.owned.assert_called_once()
    spend.record.assert_called_once_with(spend.ctx.owned.call_args.args[0], spend.job, usd, tokens)


def test_context_spend_commit_failure_does_not_advance_usage(spend):
    spend.fail = True
    with pytest.raises(RuntimeError, match="commit failed"):
        spend.ctx.add_cost(0.25, 12)
    assert (spend.job.spent_usd, spend.job.tokens, spend.ctx.spent) == (0, 0, 0)
    assert spend.ledger == []


def test_recorder_spend_is_transactional_and_idempotent(spend):
    recorder = ev.DBRecorder("project", "run", "episode", ctx=spend.ctx)
    state = ep.EpisodeState(cost_usd=0.25, tokens=12)
    spend.fail = True
    with pytest.raises(RuntimeError, match="commit failed"):
        recorder.save(state)
    assert spend.ledger == [] and spend.ctx.spent == 0 and spend.ep.state == {}
    spend.fail = False
    recorder.save(state)
    recorder.save(state)
    assert spend.ledger == [(0.25, 12)]
    assert (spend.job.spent_usd, spend.job.tokens, spend.ctx.spent) == (0.25, 12, 0.25)
    assert spend.ep.state["cost_usd"] == 0.25
    assert spend.ctx.owned.call_count == 3


@pytest.fixture
def shard(monkeypatch):
    run = NS(status="running", world_version_id="world", summary={"overall": {"finished": 1}})
    world = NS(manifest={}, private={"secrets": {}, "vars": {}}, snapshot_dir="snapshot")
    s = NS(scalars=lambda statement: NS(first=lambda: run), scalar=lambda statement: 1,
           get=lambda model, key: run if model is Run else world)

    @contextmanager
    def transaction():
        yield s

    monkeypatch.setattr(ev, "session", transaction)
    monkeypatch.setattr(ev, "settings", lambda: NS(data_path=lambda value: value))
    monkeypatch.setattr(ev.WorldManifest, "model_validate", lambda value: NS())
    ctx = NS(payload={"run_id": "run"}, project_id="project", checkpoint={
        "instance": {"instance_id": "same"}, "current_episode": "episode"},
        _stop=None, check=Mock(), owned=Mock(), log=Mock())
    inst = NS(record=NS(instance_id="same"), destroy=Mock())
    monkeypatch.setattr(ev, "_claim", Mock(side_effect=["episode", None]))
    monkeypatch.setattr(ev, "_settle", Mock(return_value=True))
    monkeypatch.setattr(ev, "_instance", Mock(return_value=inst))
    episode = Mock()
    monkeypatch.setattr(ev, "run_episode", episode)
    cleanup = Mock()
    monkeypatch.setattr(ev, "_destroy_owned", cleanup)
    return NS(ctx=ctx, inst=inst, episode=episode, cleanup=cleanup)


@pytest.mark.parametrize("error", [RuntimeError, queue.JobPaused, queue.JobCancelled, queue.LeaseLost])
def test_evaluation_failure_retains_resumable_sandbox(shard, error):
    shard.episode.side_effect = error("interrupted")
    checkpoint = deepcopy(shard.ctx.checkpoint)
    with pytest.raises(error, match="interrupted"):
        ev.handle(shard.ctx)
    shard.cleanup.assert_not_called()
    assert shard.ctx.checkpoint == checkpoint


def test_completed_shard_cleans_up_under_ownership(shard):
    assert ev.handle(shard.ctx) == {"run_id": "run", "overall": {"finished": 1}}
    shard.cleanup.assert_called_once_with(shard.ctx, shard.inst, clear=True)


def test_completed_shard_leaves_replacement_sandbox_alone(shard):
    shard.cleanup.side_effect = queue.LeaseLost("replacement owns claim")
    assert ev.handle(shard.ctx)["run_id"] == "run"
    shard.inst.destroy.assert_not_called()


@pytest.mark.parametrize("command", [queue.JobPaused, queue.JobCancelled, queue.LeaseLost])
def test_completed_shard_preserves_background_stop(shard, command):
    shard.ctx._stop = command("stop arrived during final episode")
    assert ev.handle(shard.ctx)["run_id"] == "run"
    shard.cleanup.assert_not_called()


@pytest.mark.parametrize("source", ["model", "participant"])
def test_environment_error_survives_restart_before_scoring(make_engine, monkeypatch, source):
    if source == "model":
        engine = make_engine(ep.LLMPolicy(ep.AgentProfile(name="test"), "test:model"))
        monkeypatch.setattr(ep, "chat", Mock(side_effect=LLMError("offline")))
    else:
        engine = make_engine(participant=app_participant())
        monkeypatch.setattr(engine.gateway, "execute", Mock(return_value=GatewayResult("FAILED", {"error": "offline"})))
    engine.finish = Mock(side_effect=RuntimeError("restart before scoring"))
    with pytest.raises(RuntimeError, match="restart before scoring"):
        engine.run()
    saved = engine.recorder.snapshots[-1]
    assert "offline" in saved["environment_error"]
    restored = ep.EpisodeState.from_json(saved)
    resumed = make_engine(state=restored)
    monkeypatch.setattr(ep, "evaluate", evaluate_result)
    monkeypatch.setattr(ep, "Prober", lambda instance: NS(invalidate=Mock(), query=lambda *args: [[1]]))
    result = resumed.run()
    assert result.environment_error == engine.environment_error == restored.environment_error
    assert not result.goal_satisfied and result.reward == 0
    assert resumed.dispatched == []


def test_oracle_error_survives_restart(make_engine, monkeypatch):
    engine = make_engine()
    monkeypatch.setattr(ep, "evaluate", Mock(side_effect=RuntimeError("oracle offline")))
    result = engine.run()
    restored = ep.EpisodeState.from_json(engine.recorder.snapshots[-1])
    assert restored.environment_error == result.environment_error
    resumed = make_engine(state=restored)
    monkeypatch.setattr(ep, "evaluate", evaluate_result)
    monkeypatch.setattr(ep, "Prober", lambda instance: NS(invalidate=Mock(), query=lambda *args: [[1]]))
    assert resumed.run().environment_error == result.environment_error


def test_legacy_environment_error_stays_unscored(make_engine, monkeypatch):
    assert ep.EpisodeState.from_json({}).environment_error is None
    restored = ep.EpisodeState.from_json({"opened": True, "termination": "environment_error"})
    engine = make_engine(state=restored)
    monkeypatch.setattr(ep, "evaluate", evaluate_result)
    monkeypatch.setattr(ep, "Prober", lambda instance: NS(invalidate=Mock(), query=lambda *args: [[1]]))
    result = engine.run()
    assert result.environment_error and not result.goal_satisfied and result.reward == 0
    assert engine.recorder.snapshots[-1]["environment_error"] == result.environment_error
