"""Plan limits, quiet hours, operator admins, and Dodo Payments billing against PostgreSQL (Dodo itself is faked)."""

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from rehearsal import billing
from rehearsal.api.app import app
from rehearsal.api.auth import bootstrap
from rehearsal.config import settings
from rehearsal.db import queue
from rehearsal.db.models import Job, Membership, Organization, PlanCredit, Project, User, now
from rehearsal.db.session import session

WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"test-signing-key-32-bytes-long!!").decode()
PRODUCTS = {"pro_monthly": "pdt_pro_m", "pro_yearly": "pdt_pro_y", "team_monthly": "pdt_team_m", "team_yearly": "pdt_team_y", "episodes_1000": "pdt_eps", "build_1": "pdt_build"}


@pytest.fixture
def plans(db, monkeypatch):
    monkeypatch.setenv("REHEARSAL_PLANS", "on")
    monkeypatch.setenv("REHEARSAL_ADMIN_EMAILS", "boss@example.test")
    monkeypatch.setenv("REHEARSAL_QUIET_HOURS_UTC", "00:00-00:01")  # practically never: free runs wait
    monkeypatch.setenv("DODO_PAYMENTS_API_KEY", "test-key")
    monkeypatch.setenv("DODO_PAYMENTS_WEBHOOK_KEY", WEBHOOK_SECRET)
    for k, v in PRODUCTS.items():
        monkeypatch.setenv(f"DODO_PRODUCT_{k.upper()}", v)
    settings.cache_clear()
    yield
    settings.cache_clear()


def _workspace(name: str) -> tuple[str, dict[str, str], str]:
    project, key = bootstrap(name, name)
    with session() as s:
        return project, {"Authorization": f"Bearer {key}"}, s.get(Project, project).org_id


def _app(client, auth, name="a") -> str:
    r = client.post("/v1/applications", headers=auth, json={"name": name, "source": {"kind": "git", "url": "https://example.test/x"}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_free_plan_limits_are_enforced(plans):
    from tests.integration.test_api_queue import _published_world

    project, auth, org_id = _workspace(f"free-{uuid.uuid4().hex[:6]}")
    client = TestClient(app)
    plan = client.get("/v1/billing", headers=auth).json()
    assert plan["plan"]["name"] == "free" and plan["usage"]["applications"] == 0

    app_id = _app(client, auth)
    second = client.post("/v1/applications", headers=auth, json={"name": "b", "source": {"kind": "git", "url": "https://example.test/y"}})
    assert second.status_code == 402 and "1 application" in second.json()["detail"]
    assert client.post("/v1/applications/import-catalog", headers=auth).status_code == 402

    built = client.post("/v1/world-builds", headers=auth, json={"application_id": app_id, "budget_usd": 50}).json()
    with session() as s:
        job = s.get(Job, built["job_id"])
        assert job.budget_usd == 5.0 and job.payload["options"]["parallel"] == 1  # free: $5 cap, one sandbox
        job.status = "failed"
    again = client.post("/v1/world-builds", headers=auth, json={"application_id": app_id})
    assert again.status_code == 402 and "restarted" in again.json()["detail"]  # the free build is once, but a retry is free
    assert client.post(f"/v1/jobs/{built['job_id']}/commands", headers=auth, json={"command": "retry"}).status_code == 200

    wv = _published_world(project, scenarios=5)
    prof = client.post("/v1/agent-profiles", headers=auth, json={"name": "baseline"}).json()["id"]
    too_many = client.post("/v1/evaluations", headers=auth, json={"world_version_id": wv, "profile_ids": [prof], "repeats": 9})
    assert too_many.status_code == 402 and "45 episodes" in too_many.json()["detail"]

    run = client.post("/v1/evaluations", headers=auth, json={"world_version_id": wv, "profile_ids": [prof], "repeats": 2}).json()
    assert run["shards"] == 1 and run["starts_at"]  # one sandbox; waits for the quiet window
    with session() as s:
        shard = s.get(Job, run["job_id"])
        assert shard.not_before is not None and shard.not_before > now()
        s.execute(Job.__table__.update().where(Job.kind == "evaluation", Job.id != shard.id, Job.status.in_(("queued", "running"))).values(status="cancelled"))
    with session() as s:
        assert queue.claim(s, "w-quiet", ["evaluation"]) is None  # not claimable before the window
    busy = client.post("/v1/evaluations", headers=auth, json={"world_version_id": wv, "profile_ids": [prof], "repeats": 1})
    assert busy.status_code == 429 and "sandbox" in busy.json()["detail"]
    with session() as s:
        s.get(Job, run["job_id"]).not_before = now() - timedelta(seconds=1)
    with session() as s:
        claimed = queue.claim(s, "w-quiet", ["evaluation"])
        assert claimed is not None and claimed.id == run["job_id"]
        claimed.status = "cancelled"
        queue._fail_owner(s, claimed, "cancelled")  # what a stopped shard does to its run
    used = client.get("/v1/billing", headers=auth).json()["usage"]
    assert used["episodes"] == 0  # the stopped run never started its episodes, so they are not counted


def test_admin_sets_any_plan_and_grants_credits(plans):
    project, auth, org_id = _workspace(f"adm-{uuid.uuid4().hex[:6]}")
    client = TestClient(app)
    assert client.get("/v1/admin/organizations", headers=auth).status_code == 403  # API keys never reach admin pages

    with session() as s:  # an operator admin signed in with Google, and a look-alike with a password only
        boss = s.scalars(select(User).where(User.email == "boss@example.test")).first() or User(email="boss@example.test", name="Boss")
        boss.google_sub = boss.google_sub or uuid.uuid4().hex
        fake = User(email=f"{uuid.uuid4().hex[:6]}@example.test", name="Fake", password_hash="scrypt$00$00")
        s.add_all([boss, fake])
        s.flush()
        s.add(Membership(user_id=boss.id, org_id=org_id, role="member"))
        boss_id, fake_id = boss.id, fake.id
    from rehearsal.api.auth import COOKIE, user_cookie

    admin = TestClient(app, cookies={COOKIE: user_cookie(boss_id, project)})
    orgs = admin.get("/v1/admin/organizations").json()
    assert any(o["id"] == org_id and o["plan"] == "free" for o in orgs)
    with session() as s:
        assert billing.is_admin(s.get(User, fake_id)) is False

    r = admin.put(f"/v1/admin/organizations/{org_id}", json={"plan_override": "team", "limits_override": {"applications": 2, "episodes": None}})
    assert r.status_code == 200 and r.json()["plan"]["name"] == "team" and r.json()["plan"]["applications"] == 2 and r.json()["plan"]["episodes"] is None
    assert admin.put(f"/v1/admin/organizations/{org_id}", json={"limits_override": {"bogus": 1}}).status_code == 422
    _app(client, auth, "one")
    _app(client, auth, "two")
    assert client.post("/v1/applications", headers=auth, json={"name": "three", "source": {"kind": "git", "url": "https://example.test/z"}}).status_code == 402

    granted = admin.post(f"/v1/admin/organizations/{org_id}/credits", json={"kind": "builds", "quantity": 3, "note": "pilot"})
    assert granted.status_code == 201 and granted.json()["usage"]["extra_builds"] == 3


def _signed(body: bytes, wid: str, ts: int | None = None) -> dict[str, str]:
    ts = ts or int(time.time())
    key = base64.b64decode(WEBHOOK_SECRET.removeprefix("whsec_"))
    sig = base64.b64encode(hmac.new(key, f"{wid}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"webhook-id": wid, "webhook-timestamp": str(ts), "webhook-signature": f"v1,{sig}", "content-type": "application/json"}


def test_dodo_webhook_and_sync_apply_subscription_and_top_ups(plans, monkeypatch):
    project, auth, org_id = _workspace(f"pay-{uuid.uuid4().hex[:6]}")
    cid = f"cus_{uuid.uuid4().hex[:10]}"
    calls = []
    state = {"subs": [], "payments": []}

    def fake(method, path, **kw):
        calls.append((method, path))
        if path == "/customers":
            return {"customer_id": cid}
        if path == "/checkouts":
            assert kw["json"]["customer"] == {"customer_id": cid} and kw["json"]["metadata"]["org_id"] == org_id
            return {"session_id": "cks_1", "checkout_url": "https://test.checkout.dodopayments.com/cks_1"}
        if path == "/subscriptions":
            return {"items": state["subs"]}
        if path == "/payments":
            return {"items": [{"payment_id": p["payment_id"], "status": "succeeded", "subscription_id": None} for p in state["payments"]]}
        if path.startswith("/payments/"):
            return next(p for p in state["payments"] if p["payment_id"] == path.split("/")[-1])
        raise AssertionError(path)

    monkeypatch.setattr(billing, "_dodo", fake)
    client = TestClient(app)
    url = client.post("/v1/billing/checkout", headers=auth, json={"item": "pro_monthly"}).json()["url"]
    assert url.startswith("https://test.checkout")
    assert client.post("/v1/billing/checkout", headers=auth, json={"item": "episodes_1000"}).status_code == 409  # top-ups need a paid plan

    # Dodo reports the subscription; the webhook only names the customer, the state comes from the API.
    state["subs"] = [{"subscription_id": "sub_1", "status": "active", "product_id": "pdt_pro_m", "next_billing_date": "2026-11-10T00:00:00Z",
                      "cancel_at_next_billing_date": False, "created_at": "2026-10-10T00:00:00Z", "metadata": {"org_id": org_id}}]
    body = json.dumps({"type": "subscription.active", "business_id": "bus_1", "timestamp": "2026-10-10T00:00:00Z",
                       "data": {"payload_type": "Subscription", "subscription_id": "sub_1", "customer": {"customer_id": cid}}}).encode()
    wid = f"msg_{uuid.uuid4().hex}"
    assert client.post("/v1/billing/webhook", content=body, headers={**_signed(body, wid), "webhook-signature": "v1,AAAA"}).status_code == 401
    assert client.post("/v1/billing/webhook", content=body, headers=_signed(body, wid, ts=int(time.time()) - 3600)).status_code == 401
    assert client.post("/v1/billing/webhook", content=body, headers=_signed(body, wid)).json() == {"ok": True}
    assert client.post("/v1/billing/webhook", content=body, headers=_signed(body, wid)).json()["duplicate"] is True
    summary = client.get("/v1/billing", headers=auth).json()
    assert summary["plan"]["name"] == "pro" and summary["subscription"]["status"] == "active"
    assert client.post("/v1/billing/checkout", headers=auth, json={"item": "team_monthly"}).status_code == 409  # change the plan instead

    # A top-up payment arrives; syncing twice adds it once.
    state["payments"] = [{"payment_id": f"pay_{uuid.uuid4().hex[:10]}", "status": "succeeded", "created_at": now().isoformat(), "metadata": {"org_id": org_id},
                          "product_cart": [{"product_id": "pdt_eps", "quantity": 2}]}]
    assert client.post("/v1/billing/sync", headers=auth).json()["usage"]["extra_episodes"] == 2000
    client.post("/v1/billing/sync", headers=auth)
    with session() as s:
        assert s.query(PlanCredit).filter(PlanCredit.org_id == org_id).count() == 1
        assert billing.allowance(s, project) == 60.0 + 40.0  # top-ups raise the model-spend safety net with them

    # A failed renewal puts the subscription on hold: the workspace is back on free limits.
    state["subs"][0]["status"] = "on_hold"
    assert client.post("/v1/billing/sync", headers=auth).json()["plan"]["name"] == "free"
    with session() as s:
        assert billing.plan_of(s, s.get(Organization, org_id)).name == "free"


def test_one_free_workspace_per_account_and_browser(plans, monkeypatch):
    from rehearsal.api import auth
    from rehearsal.api.auth import COOKIE, DEVICE_COOKIE, user_cookie

    monkeypatch.setattr(auth, "FREE_PER_IP", (10_000, 30))  # every test client shares one address

    with session() as s:
        a, b = User(email=f"{uuid.uuid4().hex[:6]}@example.test", name="A"), User(email=f"{uuid.uuid4().hex[:6]}@example.test", name="B")
        s.add_all([a, b])
        s.flush()
        ids = a.id, b.id
    device = uuid.uuid4().hex + "xx"
    first = TestClient(app, cookies={COOKIE: user_cookie(ids[0], None), DEVICE_COOKIE: device})
    assert first.post("/v1/onboarding/workspace", json={"organization": "A co"}).status_code == 201
    assert first.post("/v1/onboarding/workspace", json={"organization": "A again"}).status_code == 409  # one owned workspace per account
    other = TestClient(app, cookies={COOKIE: user_cookie(ids[1], None), DEVICE_COOKIE: device})
    r = other.post("/v1/onboarding/workspace", json={"organization": "B co"})
    assert r.status_code == 409 and "browser" in r.json()["detail"]


def test_google_sign_in_takes_over_an_unverified_password_account(db):
    from rehearsal.api import auth

    email = f"{uuid.uuid4().hex[:6]}@example.test"
    auth.create_user("Squatter", email, "a-password-123")
    auth.google_user({"sub": uuid.uuid4().hex, "email": email, "name": "Real Owner"}, allow_new=False)
    with session() as s:
        assert s.scalars(select(User).where(User.email == email)).one().password_hash is None
    with pytest.raises(Exception):
        auth.password_login(email, "a-password-123")  # the squatter's password no longer opens the account


def test_quiet_window_crosses_midnight(monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setenv("REHEARSAL_QUIET_HOURS_UTC", "18:00-02:00")
    settings.cache_clear()
    try:
        at = lambda h, m=0: datetime(2026, 10, 10, h, m, tzinfo=timezone.utc)  # noqa: E731
        assert billing.quiet_start(at(19)) is None and billing.quiet_start(at(1, 59)) is None
        assert billing.quiet_start(at(10)) == at(18)
        assert billing.quiet_start(at(2)) == at(18)
        assert billing.quiet_start(at(17, 59)) == at(18)
    finally:
        settings.cache_clear()


def _stop_run(run_id: str) -> None:
    with session() as s:  # what stopped shards do to their run
        for j in queue.run_jobs(s, run_id):
            if j.status in ("queued", "running", "paused"):
                j.status = "cancelled"
                queue._fail_owner(s, j, "cancelled")


def test_restarting_a_stopped_run_counts_its_episodes_again(plans):
    from tests.integration.test_api_queue import _published_world

    project, auth, org_id = _workspace(f"rst-{uuid.uuid4().hex[:6]}")
    client = TestClient(app)
    wv = _published_world(project, scenarios=10)
    prof = client.post("/v1/agent-profiles", headers=auth, json={"name": "baseline"}).json()["id"]
    a = client.post("/v1/evaluations", headers=auth, json={"world_version_id": wv, "profile_ids": [prof], "repeats": 2}).json()
    _stop_run(a["run_id"])  # 20 episodes never started: not counted
    b = client.post("/v1/evaluations", headers=auth, json={"world_version_id": wv, "profile_ids": [prof], "repeats": 3})
    assert b.status_code == 202, b.text  # 30 of 40 now in use
    again = client.post(f"/v1/runs/{a['run_id']}/commands", headers=auth, json={"command": "retry"})
    assert again.status_code == 402 and "brings back 20 episodes" in again.json()["detail"]  # stop and restart cannot dodge the limit
    _stop_run(b.json()["run_id"])
    again = client.post(f"/v1/runs/{a['run_id']}/commands", headers=auth, json={"command": "retry"})
    assert again.status_code == 200 and again.json()["status"] == "queued"
    with session() as s:
        shard = queue.run_jobs(s, a["run_id"])[0]
        assert shard.not_before is not None and shard.not_before > now()  # still waits for quiet hours
    assert client.get("/v1/billing", headers=auth).json()["usage"]["episodes"] == 20


def test_jobs_get_their_own_spend_cap_not_the_whole_allowance(plans):
    from tests.integration.test_api_queue import _published_world

    project, auth, org_id = _workspace(f"cap-{uuid.uuid4().hex[:6]}")
    with session() as s:
        s.get(Organization, org_id).plan_override = "pro"  # $60 a month
    client = TestClient(app)
    app_id = _app(client, auth)
    build = client.post("/v1/world-builds", headers=auth, json={"application_id": app_id}).json()
    wv = _published_world(project, scenarios=5)
    prof = client.post("/v1/agent-profiles", headers=auth, json={"name": "baseline"}).json()["id"]
    run = client.post("/v1/evaluations", headers=auth, json={"world_version_id": wv, "profile_ids": [prof], "repeats": 2})
    assert run.status_code == 202, run.text  # the build in progress did not reserve the whole month
    with session() as s:
        assert s.get(Job, build["job_id"]).budget_usd == billing.DEFAULT_BUDGET_USD["world_build"]
        shards = queue.run_jobs(s, run.json()["run_id"])
        assert abs(sum(j.budget_usd for j in shards) - 10 * billing.EPISODE_BUDGET_USD) < 1e-9


def test_a_paid_plan_that_ended_without_news_is_checked_again(plans, monkeypatch):
    project, auth, org_id = _workspace(f"old-{uuid.uuid4().hex[:6]}")
    old = (now() - timedelta(days=5)).isoformat()
    with session() as s:
        s.get(Organization, org_id).billing = {"customer_id": "cus_x", "subscription_id": "sub_x", "status": "active", "plan": "team", "period_end": old, "synced_at": old}

    def unreachable(*a, **k):
        raise billing.BillingError("down")

    monkeypatch.setattr(billing, "_dodo", unreachable)
    client = TestClient(app)
    assert client.get("/v1/billing", headers=auth).json()["plan"]["name"] == "free"  # 5 days past the period: no longer paid
    renewed = (now() + timedelta(days=25)).isoformat()
    monkeypatch.setattr(billing, "_dodo", lambda method, path, **kw: {"items": [{"subscription_id": "sub_x", "status": "active", "product_id": "pdt_team_m",
                                                                                 "next_billing_date": renewed}]} if path == "/subscriptions" else {"items": []})
    with session() as s:
        billing.lock(s, project)  # any limit check re-reads a stale subscription first
    assert client.get("/v1/billing", headers=auth).json()["plan"]["name"] == "team"


def test_no_second_subscription_while_one_is_on_hold(plans, monkeypatch):
    project, auth, org_id = _workspace(f"hold-{uuid.uuid4().hex[:6]}")
    with session() as s:
        s.get(Organization, org_id).billing = {"customer_id": "cus_h", "subscription_id": "sub_h", "status": "on_hold", "plan": "pro"}
    monkeypatch.setattr(billing, "_dodo", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call Dodo")))
    r = TestClient(app).post("/v1/billing/checkout", headers=auth, json={"item": "pro_monthly"})
    assert r.status_code == 409 and "on hold" in r.json()["detail"]


def test_a_misconfigured_webhook_secret_is_reported_not_crashed(plans, monkeypatch):
    monkeypatch.setenv("DODO_PAYMENTS_WEBHOOK_KEY", "whsec_not base64!")
    settings.cache_clear()
    body = b"{}"
    r = TestClient(app).post("/v1/billing/webhook", content=body, headers=_signed(body, "msg_bad"))
    assert r.status_code == 500 and "signing secret" in r.json()["detail"]


def test_refunded_top_up_is_removed_and_not_added_again(plans, monkeypatch):
    project, auth, org_id = _workspace(f"ref-{uuid.uuid4().hex[:6]}")
    pay = f"pay_{uuid.uuid4().hex[:10]}"
    with session() as s:
        s.get(Organization, org_id).billing = {"customer_id": f"cus_{org_id}", "subscription_id": "sub_r", "status": "active", "plan": "pro"}
    payment = {"payment_id": pay, "status": "succeeded", "created_at": now().isoformat(), "product_cart": [{"product_id": "pdt_build", "quantity": 3}]}
    monkeypatch.setattr(billing, "_dodo", lambda method, path, **kw: (
        {"items": []} if path == "/subscriptions" else {"items": [{"payment_id": pay, "status": "succeeded"}]} if path == "/payments" else payment))
    client = TestClient(app)
    assert client.post("/v1/billing/sync", headers=auth).json()["usage"]["extra_builds"] == 3
    body = json.dumps({"type": "refund.succeeded", "data": {"payload_type": "Refund", "refund_id": "ref_1", "payment_id": pay, "status": "succeeded",
                                                             "customer": {"customer_id": f"cus_{org_id}"}}}).encode()
    assert client.post("/v1/billing/webhook", content=body, headers=_signed(body, f"msg_{uuid.uuid4().hex}")).json() == {"ok": True}
    assert client.get("/v1/billing", headers=auth).json()["usage"]["extra_builds"] == 0
    assert client.post("/v1/billing/sync", headers=auth).json()["usage"]["extra_builds"] == 0  # the payment still says succeeded


def test_grace_period_lasts_until_dodos_deadline(plans, monkeypatch):
    project, auth, org_id = _workspace(f"grace-{uuid.uuid4().hex[:6]}")
    ended = (now() - timedelta(days=6)).isoformat()
    sub = {"subscription_id": "sub_g", "status": "past_due", "product_id": "pdt_pro_m", "next_billing_date": ended, "metadata": {"org_id": org_id}}
    with session() as s:
        s.get(Organization, org_id).billing = {"customer_id": f"cus_{org_id}", "subscription_id": "sub_g", "status": "past_due", "plan": "pro", "period_end": ended}
    monkeypatch.setattr(billing, "_dodo", lambda method, path, **kw: {"items": [sub]} if path == "/subscriptions" else {"items": []})
    client = TestClient(app)
    assert client.get("/v1/billing", headers=auth).json()["plan"]["name"] == "free"  # no deadline known: 3 days after the period
    deadline = (now() + timedelta(days=10)).isoformat()
    body = json.dumps({"type": "subscription.past_due", "data": {**sub, "past_due_ends_at": deadline, "customer": {"customer_id": f"cus_{org_id}"}}}).encode()
    assert client.post("/v1/billing/webhook", content=body, headers=_signed(body, f"msg_{uuid.uuid4().hex}")).status_code == 200
    assert client.get("/v1/billing", headers=auth).json()["plan"]["name"] == "pro"  # Dodo's grace window still open
    assert client.post("/v1/billing/change", headers=auth, json={"item": "team_monthly"}).status_code == 409  # Dodo refuses plan changes now


def test_plan_change_keeps_the_current_plan_if_the_charge_fails(plans, monkeypatch):
    project, auth, org_id = _workspace(f"chg-{uuid.uuid4().hex[:6]}")
    sent = {}
    with session() as s:
        s.get(Organization, org_id).billing = {"customer_id": f"cus_{org_id}", "subscription_id": "sub_c", "status": "active", "plan": "pro"}

    def fake(method, path, **kw):
        if path.endswith("/change-plan"):
            sent.update(kw["json"])
            return {}
        return {"items": []}

    monkeypatch.setattr(billing, "_dodo", fake)
    assert TestClient(app).post("/v1/billing/change", headers=auth, json={"item": "team_monthly"}).status_code == 200
    assert sent == {"product_id": "pdt_team_m", "quantity": 1, "proration_billing_mode": "prorated_immediately", "on_payment_failure": "prevent_change"}


def test_a_test_key_never_reaches_live_mode(plans, monkeypatch):
    monkeypatch.setenv("DODO_PAYMENTS_API_KEY", "dodo_test_abc")
    monkeypatch.setenv("DODO_PAYMENTS_ENVIRONMENT", "live_mode")
    settings.cache_clear()
    with pytest.raises(billing.BillingError, match="test key"):
        billing._dodo("GET", "/subscriptions")


def test_a_garbled_signature_is_refused_not_crashed(plans):
    body = b"{}"
    headers = {**_signed(body, "msg_x"), "webhook-signature": "v1,ééé".encode("latin-1")}  # raw bytes, as any client could send
    assert TestClient(app).post("/v1/billing/webhook", content=body, headers=headers).status_code == 401
