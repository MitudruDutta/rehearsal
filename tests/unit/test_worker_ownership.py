"""Mocked worker transactions: no database, handlers, or heartbeat threads."""

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rehearsal.db import events
from rehearsal.worker import main


@pytest.fixture(params=["world_build", "evaluation", "training"])
def worker(request, monkeypatch):
    model, key = {
        "world_build": (main.WorldVersion, "world_version_id"),
        "evaluation": (main.Run, "run_id"),
        "training": (main.TrainingJob, "training_job_id"),
    }[request.param]
    job = SimpleNamespace(
        id="job-1", project_id="project-1", kind=request.param,
        payload={key: "owner-1"}, attempts=1, max_attempts=1,
        status="running", lease_owner="worker-1", lease_expires_at="lease",
        error=None,
    )
    state = SimpleNamespace(
        job=job, owner=SimpleNamespace(status="running", finished_at=None, validation={"existing": True}),
        claimed=deepcopy(job), transactions=[], commits=[], rollbacks=[], lease_lost=False,
    )

    @contextmanager
    def transaction():
        pending = SimpleNamespace(job=deepcopy(state.job), owner=deepcopy(state.owner))
        s = Mock()
        s.job = pending.job
        s.get.return_value = pending.owner
        state.transactions.append(s)
        try:
            yield s
        except BaseException:
            state.rollbacks.append(s)
            raise
        else:
            state.job, state.owner = pending.job, pending.owner
            state.commits.append((pending.job.status, pending.owner.status))

    def owned(s, job_id, worker_id, attempt):
        assert (job_id, worker_id, attempt) == ("job-1", "worker-1", 1)
        if state.lease_lost:
            raise main.queue.LeaseLost("replacement owns job")
        return s.job

    def finish(s, row, *, status, **kwargs):
        assert row is s.job
        row.status, row.lease_owner, row.lease_expires_at = status, None, None

    monkeypatch.setattr(main, "session", Mock(side_effect=transaction))
    monkeypatch.setattr(main.queue, "claim", Mock(return_value=state.claimed))
    monkeypatch.setattr(main.queue, "owned", Mock(side_effect=owned))
    monkeypatch.setattr(main.queue, "release_shard", Mock(return_value=False))  # no other shard is working on the run
    monkeypatch.setattr(main.queue, "finish", Mock(side_effect=finish))
    monkeypatch.setattr(main, "JobContext", Mock(side_effect=lambda *args: nullcontext(SimpleNamespace(models={}))))
    state.handler = Mock(return_value={"ok": True})
    monkeypatch.setattr(main, "_handler", Mock(return_value=state.handler))
    monkeypatch.setattr(events, "emit", Mock())
    monkeypatch.setattr(main.time, "sleep", Mock())
    state.model = model
    return state


@pytest.fixture(params=[main.queue.JobCancelled, main.BudgetExceeded, RuntimeError])
def failure(request):
    return request.param("handler stopped")


def test_terminal_job_and_domain_failure_commit_together(worker, failure):
    worker.handler.side_effect = failure
    assert main.run_one("worker-1") is True
    status = "cancelled" if isinstance(failure, main.queue.JobCancelled) else "failed"
    assert worker.commits == [("running", "running"), (status, status)]
    assert len(worker.transactions) == 2
    main.queue.owned.assert_called_once_with(worker.transactions[1], "job-1", "worker-1", 1)
    worker.transactions[1].get.assert_called_once_with(worker.model, "owner-1")
    if worker.model is main.WorldVersion:
        assert worker.owner.validation["existing"] is True
        assert "handler stopped" in worker.owner.validation["error"]
    else:
        assert worker.owner.finished_at is not None


def test_domain_write_error_rolls_back_job_terminalization(worker, failure):
    worker.handler.side_effect = failure
    original_session = main.session.side_effect

    @contextmanager
    def failing_transaction():
        with original_session() as s:
            s.get.side_effect = RuntimeError("domain update failed")
            yield s

    main.session.side_effect = failing_transaction
    with pytest.raises(RuntimeError, match="domain update failed"):
        main.run_one("worker-1")
    assert worker.job.status == worker.owner.status == "running"
    assert worker.job.lease_owner == "worker-1"
    assert worker.commits == [("running", "running")]
    assert worker.rollbacks == [worker.transactions[1]]


def test_lost_claim_during_failure_does_not_finalize_replacement(worker, failure):
    worker.handler.side_effect = failure
    worker.lease_lost = True
    worker.job.lease_owner, worker.job.attempts = "replacement", 2
    assert main.run_one("worker-1") is True
    main.queue.finish.assert_not_called()
    assert worker.job.status == worker.owner.status == "running"
    assert (worker.job.lease_owner, worker.job.attempts) == ("replacement", 2)
    worker.transactions[1].get.assert_not_called()
    assert worker.rollbacks == [worker.transactions[1]]


def test_handler_lease_loss_does_not_finalize_replacement(worker):
    worker.handler.side_effect = main.queue.LeaseLost("replacement owns job")
    worker.job.lease_owner, worker.job.attempts = "replacement", 2
    assert main.run_one("worker-1") is True
    main.queue.owned.assert_not_called()
    main.queue.finish.assert_not_called()
    assert len(worker.transactions) == 1
    assert worker.job.status == worker.owner.status == "running"
    assert (worker.job.lease_owner, worker.job.attempts) == ("replacement", 2)


def test_retry_keeps_domain_running(worker):
    worker.job.max_attempts = worker.claimed.max_attempts = 3
    worker.handler.side_effect = RuntimeError("retryable")
    assert main.run_one("worker-1") is True
    assert worker.commits == [("running", "running"), ("queued", "running")]
    worker.transactions[1].get.assert_not_called()
    main.queue.finish.assert_not_called()
    events.emit.assert_called_once()


def test_success_still_uses_owned_claim(worker):
    assert main.run_one("worker-1") is True
    assert worker.commits == [("running", "running"), ("succeeded", "running")]
    main.queue.owned.assert_called_once_with(worker.transactions[1], "job-1", "worker-1", 1)
    main.queue.finish.assert_called_once_with(
        worker.transactions[1], worker.job, status="succeeded", result={"ok": True},
    )


@pytest.mark.parametrize("command,status", [("stop", "cancelled"), ("retry", "queued")])
def test_api_commands_keep_owner_changes_in_the_same_locked_transaction(monkeypatch, command, status):
    from contextlib import contextmanager
    from types import SimpleNamespace as NS
    from rehearsal.api import app as api_module
    from rehearsal.api.auth import Principal
    job = NS(kind="world_build", status="failed", pause_requested=False, cancel_requested=False, not_before=None)
    s = NS(refresh=Mock())
    @contextmanager
    def transaction():
        yield s
    monkeypatch.setattr(api_module, "session", transaction)
    monkeypatch.setattr(api_module, "_get", lambda *a: job)
    monkeypatch.setattr(api_module.billing, "check_retry", lambda *a: None)
    def apply(session, row, cmd):
        assert session is s and row is job
        row.status = status
    monkeypatch.setattr(api_module.queue, "command", apply)
    reopen = Mock()
    monkeypatch.setattr(api_module, "_reopen_owner", reopen)
    result = api_module.job_command("job", api_module.CommandIn(command=command), Principal("p", "k", ["admin"]))
    s.refresh.assert_called_once_with(job, with_for_update=True)
    assert result["status"] == status
    if command == "retry":
        reopen.assert_called_once_with(s, job)
    else:
        reopen.assert_not_called()


def test_worker_survives_the_database_being_unreachable(monkeypatch):
    from sqlalchemy.exc import OperationalError

    from rehearsal.worker import main

    calls, sleeps = [], []

    def flaky(worker_id, kinds):
        calls.append(1)
        if len(calls) <= 2:
            raise OperationalError("SELECT 1", {}, Exception("SSL SYSCALL error: Network is unreachable"))
        return False  # the database is back and the queue is empty: with once=True the worker returns

    monkeypatch.setattr(main, "run_one", flaky)
    monkeypatch.setattr(main.time, "sleep", sleeps.append)
    main.run_worker(once=True)
    assert len(calls) == 3 and sleeps == [1.0, 2.0]  # waited and retried with back-off instead of exiting
