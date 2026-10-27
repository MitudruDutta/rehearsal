"""Job queue leases/resume and API tenancy against PostgreSQL."""

import time

from fastapi.testclient import TestClient

from rehearsal.api.app import app
from rehearsal.api.auth import bootstrap
from rehearsal.db import queue
from rehearsal.db.models import Job
from rehearsal.db.session import session


def test_lease_expiry_resumes_from_checkpoint(db):
    project, _ = bootstrap("Test", "queue")
    with session() as s:
        job = queue.enqueue(s, project_id=project, kind="unit_test_kind", payload={}, max_attempts=3)
        job_id = job.id
    with session() as s:
        claimed = queue.claim(s, "worker-a", ["unit_test_kind"])
        assert claimed is not None and claimed.id == job_id
        queue.save_checkpoint(s, job_id, {"done": ["phase1"]})
    with session() as s:  # a second worker cannot take a live lease
        assert queue.claim(s, "worker-b", ["unit_test_kind"]) is None
    time.sleep(2.5)  # worker-a dies; its lease expires
    with session() as s:
        again = queue.claim(s, "worker-b", ["unit_test_kind"])
        assert again is not None and again.id == job_id
        assert again.checkpoint == {"done": ["phase1"]} and again.attempts == 2
    with session() as s:  # the dead worker's heartbeat must fail rather than steal the job back
        try:
            queue.heartbeat(s, job_id, "worker-a")
            raise AssertionError("stale worker kept its lease")
        except queue.LeaseLost:
            pass
    with session() as s:
        queue.finish(s, s.get(Job, job_id), status="succeeded", result={"ok": True})


def test_api_requires_auth_and_scopes_by_project(db):
    client = TestClient(app)
    assert client.get("/v1/applications").status_code == 401
    _, key_a = bootstrap("A", "a")
    _, key_b = bootstrap("B", "b")
    a = {"Authorization": f"Bearer {key_a}"}
    b = {"Authorization": f"Bearer {key_b}"}
    created = client.post("/v1/applications", headers=a, json={"name": "app1", "source": {"kind": "git", "url": "https://example.test/x"}})
    assert created.status_code == 201
    app_id = created.json()["id"]
    assert client.get(f"/v1/applications/{app_id}", headers=a).status_code == 200
    assert client.get(f"/v1/applications/{app_id}", headers=b).status_code == 404  # other tenant cannot see it
    assert all(x["id"] != app_id for x in client.get("/v1/applications", headers=b).json())
    assert client.get("/v1/applications", headers={"Authorization": "Bearer rh_bad_key"}).status_code == 401


def test_write_keys_can_list_and_agent_keys_cannot(db):
    from rehearsal.api.auth import create_key

    project, admin_key = bootstrap("Scopes", "scopes")
    with session() as s:
        write, agent, read = (create_key(s, project, n, [n]) for n in ("write", "agent", "read"))
        console = create_key(s, project, "console", ["write", "evaluator"])  # what "Build and evaluate" creates
    client = TestClient(app)
    h = lambda k: {"Authorization": f"Bearer {k}"}  # noqa: E731
    assert client.get("/v1/applications", headers=h(write)).status_code == 200  # a write key can list what it changes
    assert client.get("/v1/dashboard", headers=h(write)).status_code == 403  # but not held-out verdicts on its own
    assert client.get("/v1/dashboard", headers=h(console)).status_code == 200  # "Build and evaluate" sees them
    assert client.get("/v1/applications", headers=h(agent)).status_code == 403  # the agent under test sees nothing else
    assert client.get("/v1/dashboard", headers=h(read)).status_code == 403  # read-only does not see held-out verdicts
    assert client.post("/v1/api-keys", headers=h(write), json={"name": "x", "scopes": ["admin"]}).status_code == 403  # nor manage keys


def test_sse_stream_resumes_from_cursor(db):
    project, key = bootstrap("S", "sse")
    with session() as s:
        job = queue.enqueue(s, project_id=project, kind="unit_test_kind", payload={})
        job_id = job.id
        queue.finish(s, job, status="succeeded", result={})
    client = TestClient(app)
    h = {"Authorization": f"Bearer {key}"}
    page = client.get(f"/v1/streams/{job_id}/events/page", headers=h).json()
    assert [e["type"] for e in page] == ["job.queued", "job.succeeded"]
    with client.stream("GET", f"/v1/jobs/{job_id}/events?cursor={page[0]['event_id']}", headers=h) as resp:
        body = "".join(resp.iter_text())
    assert "job.succeeded" in body and "job.queued" not in body and "stream.end" in body


def test_password_sign_up_sign_in_and_onboarding(db, monkeypatch):
    import uuid

    from rehearsal.api import app as api_module
    from rehearsal.config import settings

    email = f"owner-{uuid.uuid4().hex[:8]}@example.test"
    body = {"name": "Ada Owner", "email": email, "password": "correct horse battery"}
    client = TestClient(app)
    monkeypatch.setenv("REHEARSAL_SIGNUP", "closed")
    settings.cache_clear()
    try:
        assert client.post("/v1/auth/signup", json=body).status_code == 403
        monkeypatch.setenv("REHEARSAL_SIGNUP", "open")
        settings.cache_clear()
        api_module._attempts.clear()
        assert client.post("/v1/auth/signup", json={**body, "password": "short"}).status_code == 422
        r = client.post("/v1/auth/signup", json=body)
        assert r.status_code == 201 and r.json() == {"needs_onboarding": True}
        assert client.get("/v1/me").json()["needs_onboarding"] is True
        assert client.post("/v1/onboarding/workspace", json={"organization": "Acme"}).status_code == 201
        me = client.get("/v1/me").json()
        assert me["organization"] == "Acme" and me["user"]["name"] == "Ada Owner"
        assert TestClient(app).post("/v1/auth/signup", json={**body, "email": email.upper()}).status_code == 409
        fresh = TestClient(app)
        assert fresh.post("/v1/auth/login", json={"email": email, "password": "wrong password!"}).status_code == 401
        ok = fresh.post("/v1/auth/login", json={"email": email.upper(), "password": body["password"]})
        assert ok.status_code == 200 and ok.json() == {"needs_onboarding": False}
        assert fresh.get("/v1/me").json()["organization"] == "Acme"
        assert fresh.post("/v1/session", json={"api_key": "rh_x_y"}).status_code in (404, 405)  # no API-key console login
    finally:
        settings.cache_clear()


def test_retry_clears_stale_stop_and_pause(db):
    project, _ = bootstrap("Test", "retry")
    with session() as s:
        job = queue.enqueue(s, project_id=project, kind="unit_test_retry", payload={})
        job.status, job.cancel_requested, job.pause_requested, job.attempts = "failed", True, True, 3
        queue.command(s, job, "retry")
        assert (job.status, job.cancel_requested, job.pause_requested, job.attempts) == ("queued", False, False, 0)
        job.status = "cancelled"  # a build the user stopped can be restarted too
        queue.command(s, job, "retry")
        assert job.status == "queued"


def test_google_sign_in_then_onboarding(db, monkeypatch):
    import time as _time
    import uuid

    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    from rehearsal.api import auth
    from rehearsal.config import settings

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:  # stands in for Google's published signing keys
        def get_signing_key_from_jwt(self, token):
            return type("K", (), {"key": private.public_key()})()

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client.apps.googleusercontent.com")
    monkeypatch.setenv("REHEARSAL_SIGNUP", "open")
    settings.cache_clear()
    monkeypatch.setattr(auth, "_google_keys", Keys())
    sub = uuid.uuid4().hex

    def token(**over):
        claims = {"iss": "https://accounts.google.com", "aud": "test-client.apps.googleusercontent.com", "sub": sub,
                  "email": f"{sub[:8]}@example.test", "email_verified": True, "name": "Grace Tester",
                  "iat": int(_time.time()), "exp": int(_time.time()) + 600, **over}
        return jwt.encode(claims, private, algorithm="RS256")

    try:
        client = TestClient(app)
        assert client.post("/v1/auth/google", json={"credential": token(aud="someone-else")}).status_code == 401
        assert client.post("/v1/auth/google", json={"credential": token(email_verified=False)}).status_code == 401
        r = client.post("/v1/auth/google", json={"credential": token()})
        assert r.status_code == 200 and r.json() == {"needs_onboarding": True}
        assert client.get("/v1/me").json()["needs_onboarding"] is True
        assert client.get("/v1/applications").status_code == 409  # nothing else until a workspace exists
        assert client.post("/v1/onboarding/workspace", json={"organization": "Grace Co"}).status_code == 201
        me = client.get("/v1/me").json()
        assert me["organization"] == "Grace Co" and me["user"]["name"] == "Grace Tester" and me["scopes"] == ["admin"]
        assert client.get("/v1/applications").status_code == 200
        again = TestClient(app).post("/v1/auth/google", json={"credential": token()})
        assert again.json() == {"needs_onboarding": False}  # returning users land in their project
    finally:
        settings.cache_clear()


def _published_world(project: str, scenarios: int = 2) -> str:
    from rehearsal.db.models import Application, Scenario, World, WorldVersion

    with session() as s:
        a = Application(project_id=project, name="shop")
        s.add(a)
        s.flush()
        w = World(project_id=project, application_id=a.id, name="shop")
        s.add(w)
        s.flush()
        wv = WorldVersion(project_id=project, world_id=w.id, version=1, status="published")
        s.add(wv)
        s.flush()
        for i in range(scenarios):
            s.add(Scenario(project_id=project, world_version_id=wv.id, slug=f"job{i}", family="f", split="dev", status="approved"))
        return wv.id


def test_run_is_split_into_shards_that_share_the_episodes(db):
    from sqlalchemy import select, update

    from rehearsal.db.models import Episode, Run
    from rehearsal.worker import evaluate
    from rehearsal.worker.context import JobContext

    project, key = bootstrap("Shard", "shard")
    auth = {"Authorization": f"Bearer {key}"}
    client = TestClient(app)
    prof = client.post("/v1/agent-profiles", headers=auth, json={"name": "baseline"}).json()["id"]
    made = client.post("/v1/evaluations", headers=auth, json={"world_version_id": _published_world(project), "profile_ids": [prof], "repeats": 3}).json()
    assert (made["episodes"], made["shards"]) == (6, 3)  # six episodes: three shards, never more than half
    run_id = made["run_id"]

    with session() as s:  # shards left over from an earlier test run must not be the ones claimed below
        s.execute(update(Job).where(Job.kind == "evaluation", Job.payload["run_id"].astext != run_id).values(status="cancelled"))
    with session() as s:
        a = JobContext(queue.claim(s, "worker-a", ["evaluation"]), "worker-a")
    with session() as s:
        b = JobContext(queue.claim(s, "worker-b", ["evaluation"]), "worker-b")
    first, second = evaluate._claim(a, run_id), evaluate._claim(b, run_id)
    assert first and second and first != second
    assert evaluate._claim(a, run_id) == first  # a restarted shard gets its own episode back, not a new one

    # Shard B fails for good: its episode goes back, and the run is not failed because A is still working.
    with session() as s:
        assert queue.release_shard(s, s.get(Job, b.job_id)) is True
        assert s.get(Episode, second).job_id is None
    with session() as s:
        s.execute(update(Episode).where(Episode.id == first).values(status="finished"))
    assert evaluate._settle(a, run_id) is False  # free episodes remain, so A must claim again
    assert evaluate._claim(a, run_id) is not None

    with session() as s:
        s.execute(update(Episode).where(Episode.run_id == run_id).values(status="finished", job_id=a.job_id))
    assert evaluate._settle(a, run_id) is True
    with session() as s:
        assert s.get(Run, run_id).status == "finished" and s.get(Run, run_id).summary["overall"]["episodes"] == 6

    stopped = client.post(f"/v1/runs/{run_id}/commands", headers=auth, json={"command": "stop"})
    assert stopped.status_code == 200  # reaches every shard that can still stop
    with session() as s:
        assert "queued" not in {j.status for j in queue.run_jobs(s, run_id)}


def test_removed_application_leaves_the_console_and_frees_its_name(db):
    project, key = bootstrap("Rm", "rm")
    auth = {"Authorization": f"Bearer {key}"}
    client = TestClient(app)
    body = {"name": "app1", "source": {"kind": "git", "url": "https://example.test/x"}}
    app_id = client.post("/v1/applications", headers=auth, json=body).json()["id"]
    job_id = client.post("/v1/world-builds", headers=auth, json={"application_id": app_id}).json()["job_id"]
    assert client.delete(f"/v1/applications/{app_id}", headers=auth).json() == {"removed": True, "builds_stopped": 1}
    assert client.get("/v1/applications", headers=auth).json() == [] and client.get("/v1/worlds", headers=auth).json() == []
    with session() as s:
        assert s.get(Job, job_id).status == "cancelled"
    assert client.delete(f"/v1/applications/{app_id}", headers=auth).status_code == 404
    assert client.post("/v1/applications", headers=auth, json=body).status_code == 201  # the name can be used again


def test_sandboxes_of_ended_jobs_are_removed_but_paused_ones_are_kept(db, monkeypatch):
    from rehearsal.runner import runtime
    from rehearsal.worker import main

    removed = []
    monkeypatch.setattr(runtime.WorldInstance, "destroy", lambda self: removed.append(self.record.instance_id))
    manifest = {"name": "w", "services": [{"name": "app", "image": "x", "port": 80}]}
    rec = lambda i: {"instance_id": i, "manifest": manifest, "secrets": {}, "admin_token": "t", "images": {}}
    project, _ = bootstrap("Sweep", "sweep")
    a1, a2, b1 = (f"{n}-{project}" for n in ("a1", "a2", "b1"))  # unique per run: the test database outlives runs
    with session() as s:
        stopped = queue.enqueue(s, project_id=project, kind="unit_test_sweep", payload={})
        stopped.status, stopped.checkpoint = "cancelled", {"instance": rec(a1), "lanes": [rec(a2)], "done": ["seed"]}
        paused = queue.enqueue(s, project_id=project, kind="unit_test_sweep", payload={})
        paused.status, paused.checkpoint = "paused", {"instance": rec(b1)}
        ids = stopped.id, paused.id
    assert main.sweep() >= 2
    assert {a1, a2} <= set(removed) and b1 not in removed
    with session() as s:
        assert s.get(Job, ids[0]).checkpoint == {"done": ["seed"]} and "instance" in s.get(Job, ids[1]).checkpoint


def test_monthly_allowance_caps_every_job_and_refuses_when_used(db, monkeypatch):
    from rehearsal.config import settings

    monkeypatch.setenv("REHEARSAL_MONTHLY_ALLOWANCE_USD", "10")
    settings.cache_clear()
    try:
        _allowance_flow()
    finally:
        monkeypatch.delenv("REHEARSAL_MONTHLY_ALLOWANCE_USD")
        settings.cache_clear()


def _allowance_flow():
    from sqlalchemy import delete, update

    from rehearsal.db.models import ModelSpend

    with session() as s:  # a self-hosted allowance covers the whole server: start from a server with nothing in flight
        s.execute(update(Job).where(Job.status.in_(("queued", "running", "paused"))).values(status="cancelled"))
        s.execute(delete(ModelSpend).where(ModelSpend.month == queue.month_start().strftime("%Y-%m")))
    project, key = bootstrap("Money", "money")
    auth = {"Authorization": f"Bearer {key}"}
    client = TestClient(app)
    with session() as s:
        first = queue.enqueue(s, project_id=project, kind="world_build", payload={}, budget_usd=25.0)
        assert first.budget_usd == 10.0  # never more than the allowance
        queue.record_spend(s, first, 4.0)  # spend goes through the dated ledger, as workers record it
    with session() as s:  # 4 spent and 6 still committed to the running job: nothing left to promise
        try:
            queue.enqueue(s, project_id=project, kind="evaluation", payload={})
            raise AssertionError("allowance was over-committed")
        except queue.AllowanceExhausted:
            pass
        s.get(Job, first.id).status = "failed"  # ended at $4: its unspent budget is free again
    with session() as s:
        assert abs(queue.enqueue(s, project_id=project, kind="evaluation", payload={}).budget_usd - 6.0) < 1e-6
        assert queue.enqueue(s, project_id=project, kind="unit_test_free", payload={}).budget_usd is None  # only model jobs count
    used = client.get("/v1/usage", headers=auth).json()
    assert used["allowance_usd"] == 10.0 and used["spent_usd"] == 4.0 and used["left_usd"] == 0.0
    app_id = client.post("/v1/applications", headers=auth, json={"name": "a", "source": {"kind": "git", "url": "https://example.test/x"}}).json()["id"]
    refused = client.post("/v1/world-builds", headers=auth, json={"application_id": app_id})
    assert refused.status_code == 402 and "allowance" in refused.json()["detail"]
