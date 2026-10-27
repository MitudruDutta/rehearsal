"""Billing logic against isolated SQLite tables; no provider, app, or network calls."""

from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from rehearsal import billing, pricing
from rehearsal.agents import llm
from rehearsal.api.app import AdminPlanIn, BuildIn, EvaluationIn
from rehearsal.db import queue
from rehearsal.db.models import Base, Job, ModelSpend, Organization, PlanCredit, Project


@compiles(JSONB, "sqlite")
def sqlite_json(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def store(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    cfg = NS(plans=True, monthly_allowance_usd=0, dodo_api_key=None, admin_emails=frozenset(),
             dodo_products={"episodes_1000": "eps", "build_1": "build"})
    monkeypatch.setattr(billing, "settings", lambda: cfg)
    monkeypatch.setattr(queue, "settings", lambda: cfg)
    with Session(engine) as s:
        org = Organization(id="org", name="Test", plan_override="pro", billing={})
        s.add(org)
        s.add_all([Project(id=p, name=p, org_id="org") for p in ("p1", "p2")])
        s.commit()
        yield s, org, cfg
    engine.dispose()


@pytest.mark.parametrize("amount", [-1, "NaN", "Infinity", "-Infinity"])
def test_money_rejects_unsafe_values(amount):
    for model, fields in ((BuildIn, {"application_id": "a"}),
                          (EvaluationIn, {"world_version_id": "w", "profile_ids": ["p"]})):
        with pytest.raises(ValidationError):
            model(**fields, budget_usd=amount)
    with pytest.raises(ValidationError):
        AdminPlanIn(limits_override={"allowance_usd": amount})


def test_zero_budget_remains_valid():
    assert BuildIn(application_id="a", budget_usd=0).budget_usd == 0


def test_queue_rejects_nonfinite_before_database_access():
    s = Mock()
    with pytest.raises(ValueError, match="finite"):
        queue.enqueue(s, project_id="p", kind="world_build", payload={}, budget_usd=float("nan"))
    s.add.assert_not_called()


def test_spend_uses_recorded_month_and_whole_workspace(store, monkeypatch):
    s, org, cfg = store
    job = Job(id="j", project_id="p1", kind="world_build", status="finished",
              created_at=datetime(2026, 9, 30, tzinfo=timezone.utc))
    s.add(job); s.commit()
    monkeypatch.setattr(queue, "month_start", lambda: datetime(2026, 10, 1, tzinfo=timezone.utc))
    queue.record_spend(s, job, 20, 100)
    s.commit()
    assert queue.month_spend(s, "p2") == 20
    assert queue.allowance_left(s, "p2") == 40
    monkeypatch.setattr(queue, "month_start", lambda: datetime(2026, 11, 1, tzinfo=timezone.utc))
    queue.record_spend(s, job, 5, 10)
    s.commit()
    assert queue.month_spend(s, "p1") == 5
    assert job.spent_usd == 25 and job.tokens == 110
    assert len(s.scalars(select(ModelSpend)).all()) == 2


def test_spend_and_job_total_roll_back_together(store):
    s, _, _ = store
    job = Job(id="j", project_id="p1", kind="world_build")
    s.add(job); s.commit()
    queue.record_spend(s, job, 12, 3)
    s.flush(); s.rollback()
    assert job.spent_usd == 0 and job.tokens == 0
    assert s.scalar(select(ModelSpend)) is None


def test_workspace_reservations_include_other_projects(store):
    s, _, _ = store
    s.add(Job(project_id="p1", kind="world_build", budget_usd=55, status="running")); s.commit()
    assert queue.allowance_left(s, "p2") == 5


def test_self_hosted_cap_is_server_wide(store):
    s, _, cfg = store
    cfg.plans, cfg.monthly_allowance_usd = False, 100
    s.add(Organization(id="other", name="Other"))
    s.add(Project(id="p3", name="Other", org_id="other"))
    s.add(Job(project_id="p1", kind="world_build", budget_usd=75, status="running")); s.commit()
    assert queue.allowance_left(s, "p3") == 25


def test_reservation_locks_before_reading_allowance(monkeypatch):
    order = []
    monkeypatch.setattr(queue.billing, "lock", lambda *a: order.append("lock"))
    monkeypatch.setattr(queue, "settings", lambda: NS(plans=True))
    monkeypatch.setattr(queue, "allowance_left", lambda *a: order.append("read") or 1)
    assert queue.reserve(None, "p", "improvement", 2) == 1
    assert order == ["lock", "read"]


def test_retry_reserves_remaining_budget_again(store, monkeypatch):
    s, _, _ = store
    j = Job(id="retry", project_id="p1", kind="world_build", status="failed", spent_usd=3, budget_usd=10)
    s.add(j); s.commit()
    monkeypatch.setattr(queue, "emit", lambda *a, **k: None)
    monkeypatch.setattr(queue, "allowance_left", lambda *a: 2)
    queue.command(s, j, "retry")
    assert j.budget_usd == 5 and j.status == "queued"


def test_retry_refuses_exhausted_allowance(store, monkeypatch):
    s, _, _ = store
    j = Job(project_id="p1", kind="improvement", status="failed", spent_usd=0, budget_usd=2)
    s.add(j); s.commit()
    monkeypatch.setattr(queue, "allowance_left", lambda *a: 0)
    with pytest.raises(queue.AllowanceExhausted):
        queue.command(s, j, "retry")
    assert j.status == "failed"


def test_build_retry_respects_capacity(store):
    s, _, _ = store
    s.add(Job(project_id="p2", kind="world_build", status="running")); s.commit()
    with pytest.raises(billing.PlanLimit) as error:
        billing.check_retry(s, "p1", Job(kind="world_build", payload={}))
    assert error.value.status == 429


@pytest.mark.parametrize("other_shard", [False, True])
def test_exhausted_lease_releases_evaluation_work(monkeypatch, other_shard):
    job = NS(id="j", project_id="p", kind="evaluation", status="running", attempts=3, max_attempts=3,
             error=None, finished_at=None, lease_owner="dead", lease_expires_at=None)
    s = Mock()
    s.scalars.side_effect = [NS(first=lambda: job), NS(first=lambda: None)]
    monkeypatch.setattr(queue, "settings", lambda: NS(lease_seconds=60))
    monkeypatch.setattr(queue, "emit", Mock())
    release = Mock(return_value=other_shard)
    fail_owner = Mock()
    monkeypatch.setattr(queue, "release_shard", release)
    monkeypatch.setattr(queue, "_fail_owner", fail_owner)
    assert queue.claim(s, "worker") is None
    release.assert_called_once_with(s, job)
    assert fail_owner.call_count == (0 if other_shard else 1)
    assert job.status == "failed" and job.lease_owner is None


@pytest.mark.parametrize("password", ["offline", "encoded%40password"])
def test_all_migrations_compile_without_a_database(password):
    from io import StringIO
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    root = Path(queue.__file__).parent
    output = StringIO()
    config = Config(str(root / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(root / "migrations"))
    url = f"postgresql+psycopg://offline:{password}@invalid/offline"
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head", sql=True)
    assert "CREATE TABLE model_spend" in output.getvalue()
    assert "INSERT INTO model_spend" in output.getvalue()


def test_migrate_preserves_url_encoded_database_credentials(monkeypatch):
    from alembic import command
    from rehearsal.db import session as database
    url = "postgresql+psycopg://offline:encoded%40password@invalid/offline"
    monkeypatch.setattr(database, "settings", lambda: NS(database_url=url))
    upgrade = Mock()
    monkeypatch.setattr(command, "upgrade", upgrade)
    database.upgrade()
    config, revision = upgrade.call_args.args
    assert config.get_main_option("sqlalchemy.url") == url
    assert revision == "head"


def fake_dodo(monkeypatch, org, payment, *, lines=None):
    org.billing = {"customer_id": "cus"}
    def remote(method, path, **kw):
        if path == "/subscriptions": return {"items": []}
        if path == "/payments": return {"items": [payment]}
        if path.endswith("/line-items"): return {"items": lines or []}
        if path.startswith("/products/"): return {"name": path.rsplit("/", 1)[1]}
        return payment
    monkeypatch.setattr(billing, "billing_enabled", lambda: True)
    monkeypatch.setattr(billing, "_dodo", remote)


def payment(**kw):
    return {"payment_id": "pay_1", "status": "succeeded", "created_at": "2026-10-10T00:00:00Z",
            "product_cart": [{"product_id": "build", "quantity": 3}], **kw}


def test_multi_product_sync_is_idempotent(store, monkeypatch):
    s, org, _ = store
    p = payment(product_cart=[{"product_id": "build", "quantity": 1}, {"product_id": "eps", "quantity": 1}])
    fake_dodo(monkeypatch, org, p)
    billing.sync(s, org); s.commit()
    billing.sync(s, org); s.commit()
    assert sorted(s.scalars(select(PlanCredit.quantity))) == [1, 1000]


def test_partial_refund_keeps_all_units_while_invoice_line_is_partly_paid(store, monkeypatch):
    s, org, _ = store
    p = payment(refund_status="partial")
    fake_dodo(monkeypatch, org, p, lines=[{"amount": 3000, "tax": 0, "refundable_amount": 2000}])
    billing.sync(s, org); s.commit()
    billing.sync(s, org); s.commit()
    assert s.scalar(select(PlanCredit.quantity)) == 3


@pytest.mark.parametrize("tax", [0, 600])
@pytest.mark.parametrize("remaining,expected", [(2000, 3), (1, 3), (0, 0)])
def test_partial_refund_revocation_is_independent_of_tax(store, monkeypatch, tax, remaining, expected):
    s, org, _ = store
    p = payment(refund_status="partial")
    fake_dodo(monkeypatch, org, p, lines=[{"amount": 3000, "tax": tax, "refundable_amount": remaining}])
    billing.sync(s, org); s.commit()
    assert s.scalar(select(PlanCredit.quantity)) == expected


def test_partial_refund_rejects_negative_refundable_balance(store, monkeypatch):
    s, org, _ = store
    p = payment(refund_status="partial")
    fake_dodo(monkeypatch, org, p, lines=[{"amount": 3000, "tax": 600, "refundable_amount": -1}])
    with pytest.raises(billing.BillingError, match="negative refundable"):
        billing.sync(s, org)
    assert s.scalar(select(PlanCredit)) is None


@pytest.mark.parametrize("product_names,line_names", [
    (("build", "build"), ["build", "eps"]),
    (("build", "eps"), ["build", "build"]),
    (("build", "eps"), ["build", "other"]),
    (("build", "eps"), ["build"]),
    (("build", "eps"), ["build", "eps", "other"]),
], ids=["reused-line", "duplicate-invoice-name", "missing-product-name", "missing-line", "extra-line"])
def test_partial_refund_requires_bijective_invoice_mapping(store, monkeypatch, product_names, line_names):
    s, org, _ = store
    p = payment(product_cart=[{"product_id": "build", "quantity": 1}, {"product_id": "eps", "quantity": 1}])
    fake_dodo(monkeypatch, org, p, lines=[
        {"name": name, "amount": 1000, "tax": 0, "refundable_amount": 0} for name in line_names])
    billing.sync(s, org); s.commit()
    p["refund_status"] = "partial"
    remote = billing._dodo
    names = dict(zip(("build", "eps"), product_names))

    def renamed_products(method, path, **kw):
        if path.startswith("/products/"):
            return {"name": names[path.rsplit("/", 1)[1]]}
        return remote(method, path, **kw)

    monkeypatch.setattr(billing, "_dodo", renamed_products)
    with pytest.raises(billing.BillingError, match="invoice lines cannot be matched"):
        billing.sync(s, org)
    assert sorted(s.scalars(select(PlanCredit.quantity))) == [1, 1000]


@pytest.mark.parametrize("ref", ["dodo:pay_1", "dodo:pay_1:build"])
@pytest.mark.parametrize("refund_status", [None, "partial", "full"])
def test_shared_customer_payment_keeps_its_recorded_owner(store, monkeypatch, ref, refund_status):
    s, org, _ = store
    other = Organization(id="other", name="Other", billing={"customer_id": "cus"})
    s.add(other)
    s.add(PlanCredit(org_id=other.id, kind="builds", quantity=3, month="2026-10", ref=ref))
    s.commit()
    p = payment(refund_status=refund_status)
    fake_dodo(monkeypatch, org, p)
    billing.sync(s, org); s.commit()
    billing.sync(s, org); s.commit()
    billing.apply_event(s, org, {"type": "refund.succeeded", "data": {"payment_id": "pay_1", "is_partial": True}})
    s.commit()
    credit = s.scalars(select(PlanCredit)).one()
    assert (credit.org_id, credit.ref, credit.quantity) == (other.id, ref, 3)
    assert org.billing.get("synced_at")


def test_partial_refund_retains_unrelated_products(store, monkeypatch):
    s, org, _ = store
    p = payment(refund_status="partial", product_cart=[{"product_id": "build", "quantity": 1}, {"product_id": "eps", "quantity": 1}])
    fake_dodo(monkeypatch, org, p, lines=[
        {"name": "build", "amount": 1000, "tax": 0, "refundable_amount": 0},
        {"name": "eps", "amount": 2000, "tax": 0, "refundable_amount": 2000}])
    billing.sync(s, org); s.commit()
    assert sorted(s.scalars(select(PlanCredit.quantity))) == [0, 1000]


def test_missing_refund_webhook_is_reconciled(store, monkeypatch):
    s, org, _ = store
    p = payment()
    fake_dodo(monkeypatch, org, p)
    billing.sync(s, org); s.commit()
    p["refund_status"] = "full"
    billing.sync(s, org); s.commit()
    assert s.scalar(select(PlanCredit.quantity)) == 0


def test_refund_matches_exact_payment_not_prefix(store):
    s, org, _ = store
    for ref in ("dodo:pay_1", "dodo:pay_10", "dodo:pay_1:build"):
        s.add(PlanCredit(org_id=org.id, kind="builds", quantity=1, month="2026-10", ref=ref))
    s.commit()
    billing.apply_event(s, org, {"type": "refund.succeeded", "data": {"payment_id": "pay_1"}})
    assert s.scalars(select(PlanCredit).where(PlanCredit.ref == "dodo:pay_10")).one().quantity == 1


def test_dodo_pagination_fetches_later_records(monkeypatch):
    pages = []
    def remote(method, path, **kw):
        page = kw["params"]["page_number"]; pages.append(page)
        return {"items": [{"payment_id": f"pay_{i}"} for i in (range(100) if page == 0 else [100])]}
    monkeypatch.setattr(billing, "_dodo", remote)
    assert len(list(billing._all_dodo("/payments"))) == 101 and pages == [0, 1]


def test_unknown_price_blocks_provider_before_spending(monkeypatch):
    client = Mock(side_effect=AssertionError("provider must not be called"))
    monkeypatch.setattr(llm, "_client", client)
    monkeypatch.setattr(pricing, "billing_quote", lambda *a: None)
    token = pricing.require_known_prices.set(True)
    try:
        with pytest.raises(llm.LLMError, match="no usable price"):
            llm.chat("openai:test", [])
    finally:
        pricing.require_known_prices.reset(token)
    client.assert_not_called()


def test_price_outage_keeps_last_quote_and_retries_soon(monkeypatch):
    clock = NS(at=0)
    monkeypatch.setattr(pricing.time, "time", lambda: clock.at)
    monkeypatch.setattr(pricing, "_cache", {})
    assert pricing._cached("price", lambda: "published") == "published"
    clock.at = pricing.TTL_S + 1
    failed = Mock(side_effect=OSError("offline"))
    assert pricing._cached("price", failed) == "published"
    clock.at += 31
    assert pricing._cached("price", lambda: "updated") == "updated"
