"""Shard retry and monthly usage regressions without services or provider calls."""

from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock, call

import pytest
from fastapi import HTTPException

from rehearsal import billing
from rehearsal.api import app as api
from rehearsal.api.auth import Principal
from rehearsal.db import queue
from rehearsal.db.models import Job, ModelSpend, Organization, Project
from tests.unit.test_billing_regressions import store


@pytest.fixture
def shards(monkeypatch):
    run = NS(id="run", project_id="p1")
    monkeypatch.setattr(api, "session", lambda: nullcontext(NS(get=lambda *args: run)))
    monkeypatch.setattr(queue, "run_jobs", lambda *args: [NS(id="first"), NS(id="second")])
    command = Mock()
    monkeypatch.setattr(api, "job_command", command)
    return command, Principal("p1", "key", ["admin"])


@pytest.mark.parametrize("failure_first", [True, False])
@pytest.mark.parametrize("failure", [
    queue.AllowanceExhausted("job exhausted its budget"),
    billing.PlanLimit("all sandboxes are in use", 429),
    billing.PlanLimit("monthly episode limit reached", 402),
])
def test_run_retry_succeeds_when_any_shard_restarts(shards, failure_first, failure):
    command, principal = shards
    result = {"status": "queued", "pause_requested": False, "cancel_requested": False}
    command.side_effect = [failure, result] if failure_first else [result, failure]
    body = api.CommandIn(command="retry")
    assert api.run_command("run", body, principal) is result
    assert command.call_args_list == [call("first", body, principal), call("second", body, principal)]


@pytest.mark.parametrize("failure_first", [True, False])
@pytest.mark.parametrize("failure", [
    queue.AllowanceExhausted("no model allowance remains"),
    billing.PlanLimit("all sandboxes are in use", 429),
    billing.PlanLimit("monthly episode limit reached", 402),
])
def test_all_failed_shards_preserve_concrete_error(shards, failure_first, failure):
    command, principal = shards
    conflict = HTTPException(409, "cannot retry a succeeded job")
    command.side_effect = [failure, conflict] if failure_first else [conflict, failure]
    with pytest.raises(type(failure)) as error:
        api.run_command("run", api.CommandIn(command="retry"), principal)
    assert error.value is failure
    assert command.call_count == 2


def test_all_conflicting_shards_keep_actual_conflict(shards):
    command, principal = shards
    conflict = HTTPException(409, "cannot retry a succeeded job")
    command.side_effect = [HTTPException(409, "cannot retry a running job"), conflict]
    with pytest.raises(HTTPException) as error:
        api.run_command("run", api.CommandIn(command="retry"), principal)
    assert error.value is conflict


def test_run_command_does_not_swallow_other_http_errors(shards):
    command, principal = shards
    forbidden = HTTPException(403, "forbidden")
    command.side_effect = forbidden
    with pytest.raises(HTTPException) as error:
        api.run_command("run", api.CommandIn(command="retry"), principal)
    assert error.value is forbidden
    command.assert_called_once()


@pytest.fixture
def usage_store(store, monkeypatch):
    s, _, cfg = store
    september = datetime(2026, 9, 1, tzinfo=timezone.utc)
    october = datetime(2026, 10, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(queue, "month_start", lambda: october)
    monkeypatch.setattr(api, "session", lambda: nullcontext(s))
    s.add(Organization(id="other", name="Other", plan_override="pro"))
    s.add(Project(id="p3", org_id="other", name="Other"))
    s.add_all([
        Job(id="carry", project_id="p1", kind="world_build", status="succeeded", created_at=september, spent_usd=15),
        Job(id="peer", project_id="p2", kind="evaluation", status="succeeded", created_at=october, spent_usd=3),
        Job(id="active", project_id="p2", kind="world_validate", status="running", created_at=september,
            budget_usd=10, spent_usd=3),
        Job(id="foreign", project_id="p3", kind="improvement", status="succeeded", created_at=october, spent_usd=5),
    ])
    s.add_all([
        ModelSpend(job_id="carry", project_id="p1", month="2026-09", spent_usd=10),
        ModelSpend(job_id="carry", project_id="p1", month="2026-10", spent_usd=4),
        ModelSpend(job_id="carry", project_id="p1", month="2026-11", spent_usd=1),
        ModelSpend(job_id="peer", project_id="p2", month="2026-10", spent_usd=3),
        ModelSpend(job_id="active", project_id="p2", month="2026-10", spent_usd=3),
        ModelSpend(job_id="foreign", project_id="p3", month="2026-10", spent_usd=5),
    ])
    s.commit()
    return s, cfg


@pytest.mark.parametrize("project", ["p1", "p2"])
@pytest.mark.parametrize("hosted", [True, False])
def test_usage_matches_ledger_month_and_allowance_scope(usage_store, project, hosted):
    s, cfg = usage_store
    cfg.plans, cfg.monthly_allowance_usd = hosted, 100
    result = api.usage(Principal(project, "key", ["admin"]))
    expected = {"world_build": 4, "evaluation": 3, "world_validate": 3}
    if not hosted:
        expected["improvement"] = 5
    assert result == {
        "month": "2026-10", "spent_usd": sum(expected.values()), "by_kind": expected,
        "allowance_usd": 60 if hosted else 100, "left_usd": 43 if hosted else 78,
        "renews": "2026-11-01",
    }
    assert result["spent_usd"] == queue.month_spend(s, project)


def test_usage_empty_month_retains_outstanding_reservation(usage_store, monkeypatch):
    monkeypatch.setattr(queue, "month_start", lambda: datetime(2026, 12, 1, tzinfo=timezone.utc))
    result = api.usage(Principal("p1", "key", ["admin"]))
    assert result == {"month": "2026-12", "spent_usd": 0, "by_kind": {},
                      "allowance_usd": 60, "left_usd": 53, "renews": "2027-01-01"}
