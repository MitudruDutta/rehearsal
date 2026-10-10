"""Browser sign-in for the CLI (`rehearsal login`): the server flow, its permissions, and the CLI against a live server."""

import hashlib
import re
import socket
import threading
import time
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from rehearsal.api import app as app_module
from rehearsal.api.app import app
from rehearsal.api.auth import COOKIE, bootstrap, user_cookie
from rehearsal.db.models import ApiKey, CliLogin, Membership, Project, User, now
from rehearsal.db.session import session


@pytest.fixture(autouse=True)
def fresh_throttle(monkeypatch):
    monkeypatch.setattr(app_module, "_attempts", {})  # every test starts with an empty per-address rate limit


def _console(role: str = "owner") -> tuple[TestClient, str, str]:
    """A signed-in console user of a new workspace. Returns (browser, project_id, org name)."""
    name = f"Login {uuid.uuid4().hex[:6]}"
    project, _ = bootstrap(name, "cli")
    with session() as s:
        user = User(email=f"{uuid.uuid4().hex[:8]}@example.test", name="Tester")
        s.add(user)
        s.flush()
        s.add(Membership(user_id=user.id, org_id=s.get(Project, project).org_id, role=role))
        uid = user.id
    return TestClient(app, cookies={COOKIE: user_cookie(uid, project)}), project, name


def _start(client: str = "dev@laptop") -> dict:
    r = TestClient(app).post("/v1/cli/logins", json={"client": client})
    assert r.status_code == 201, r.text
    return r.json()


def _poll(device_code: str) -> dict:
    r = TestClient(app).post("/v1/cli/logins/poll", json={"device_code": device_code})
    assert r.status_code == 200, r.text
    return r.json()


def test_approved_terminal_collects_a_working_key_exactly_once(db):
    browser, project, org = _console()
    start = _start("dev@laptop")
    assert re.fullmatch(r"[BCDFGHJKLMNPQRSTVWXZ]{4}-[BCDFGHJKLMNPQRSTVWXZ]{4}", start["user_code"])
    assert start["verification_url"].endswith(f"/app/cli-login/?code={start['user_code']}")
    assert start["expires_in"] == 600 and start["interval"] == 2
    assert _poll(start["device_code"]) == {"status": "pending"}

    info = browser.get(f"/v1/cli/logins/{start['user_code'].lower()}").json()  # codes are case-insensitive
    assert info["client"] == "dev@laptop" and info["workspace"] == org and info["can_approve"] is True and info["status"] == "pending"
    assert info["requested_ip"]  # the approval page shows where the request came from
    assert browser.post(f"/v1/cli/logins/{start['user_code']}/approve").json() == {"status": "approved"}

    got = _poll(start["device_code"])
    assert got["status"] == "approved" and got["workspace"] == org and got["api_key"].startswith("rh_")
    me = TestClient(app).get("/v1/me", headers={"Authorization": f"Bearer {got['api_key']}"}).json()
    assert me["organization"] == org and sorted(me["scopes"]) == ["evaluator", "write"]  # "Build and evaluate", in the approver's workspace
    assert _poll(start["device_code"]) == {"status": "claimed"}  # a second collection gets nothing

    with session() as s:
        row = s.scalars(select(CliLogin).where(CliLogin.user_code == start["user_code"])).one()
        key = s.get(ApiKey, row.api_key_id)
        assert row.status == "claimed" and key.project_id == project and key.name == "CLI: dev@laptop"
        # neither the device code nor the key is stored readable
        assert row.device_hash == hashlib.sha256(start["device_code"].encode()).hexdigest()
        assert start["device_code"] not in str(vars(row)) and got["api_key"].split("_", 2)[2] not in key.hash


def test_denied_terminal_gets_no_key(db):
    browser, project, _ = _console()
    start = _start()
    with session() as s:
        keys_before = len(s.scalars(select(ApiKey).where(ApiKey.project_id == project)).all())
    assert browser.post(f"/v1/cli/logins/{start['user_code']}/deny").json() == {"status": "denied"}
    assert _poll(start["device_code"]) == {"status": "denied"}
    assert browser.post(f"/v1/cli/logins/{start['user_code']}/approve").status_code == 409  # a decision is final
    with session() as s:
        assert len(s.scalars(select(ApiKey).where(ApiKey.project_id == project)).all()) == keys_before


def test_expired_requests_cannot_be_approved_or_collected(db):
    browser, _, _ = _console()
    start = _start()
    with session() as s:
        s.scalars(select(CliLogin).where(CliLogin.user_code == start["user_code"])).one().expires_at = now() - timedelta(seconds=1)
    assert _poll(start["device_code"]) == {"status": "expired"}
    assert browser.get(f"/v1/cli/logins/{start['user_code']}").status_code == 410
    assert browser.post(f"/v1/cli/logins/{start['user_code']}/approve").status_code == 410


def test_only_signed_in_owners_and_admins_can_approve(db):
    start = _start()
    member, _, _ = _console(role="member")
    assert member.get(f"/v1/cli/logins/{start['user_code']}").json()["can_approve"] is False
    assert member.post(f"/v1/cli/logins/{start['user_code']}/approve").status_code == 403

    _, admin_key = bootstrap(f"Keys {uuid.uuid4().hex[:6]}", "cli")  # an API key is not a person: it cannot approve
    api = TestClient(app, headers={"Authorization": f"Bearer {admin_key}"})
    assert api.get(f"/v1/cli/logins/{start['user_code']}").status_code == 403
    assert api.post(f"/v1/cli/logins/{start['user_code']}/approve").status_code == 403
    assert TestClient(app).post(f"/v1/cli/logins/{start['user_code']}/approve").status_code == 401  # nor can anyone signed out
    assert _poll(start["device_code"]) == {"status": "pending"}


def test_unknown_codes_and_input_limits(db):
    browser, _, _ = _console()
    assert browser.get("/v1/cli/logins/BBBB-BBBB").status_code == 404
    assert browser.post("/v1/cli/logins/BBBB-BBBB/approve").status_code == 404
    assert TestClient(app).post("/v1/cli/logins/poll", json={"device_code": "x" * 40}).status_code == 404
    assert TestClient(app).post("/v1/cli/logins/poll", json={"device_code": "short"}).status_code == 422
    assert TestClient(app).post("/v1/cli/logins", json={"client": "x" * 201}).status_code == 422


def test_sign_in_requests_are_rate_limited_per_address(db):
    client = TestClient(app)
    assert all(client.post("/v1/cli/logins", json={}).status_code == 201 for _ in range(20))
    assert client.post("/v1/cli/logins", json={}).status_code == 429


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(db):
    import uvicorn

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="none"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_rehearsal_login_signs_in_through_the_browser(live_server, tmp_path, monkeypatch, capsys):
    """The real CLI against a running server: it opens the approval page (here the "browser" approves it at once),
    polls, saves the key for this user only, and `whoami` then works."""
    import webbrowser

    from rehearsal.sdk import cli

    browser, _, org = _console()
    opened = []

    def approve_in_browser(url: str) -> bool:
        opened.append(url)
        code = url.rsplit("code=", 1)[1]
        assert browser.post(f"/v1/cli/logins/{code}/approve").status_code == 200
        return True

    monkeypatch.setattr(webbrowser, "open", approve_in_browser)
    monkeypatch.setenv("REHEARSAL_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.delenv("REHEARSAL_API_KEY", raising=False)
    monkeypatch.delenv("REHEARSAL_URL", raising=False)

    cli.main(["login", "--url", live_server])
    out = capsys.readouterr().out
    assert opened and opened[0].startswith(f"{live_server}/app/cli-login/?code=")
    assert "Confirmation code:" in out and f"Signed in to {org}" in out
    assert (tmp_path / "config.json").stat().st_mode & 0o777 == 0o600

    cli.main(["whoami"])
    who = capsys.readouterr().out
    assert live_server in who and org in who and "write, evaluator" in who


def test_rehearsal_login_reports_a_denied_sign_in(live_server, tmp_path, monkeypatch, capsys):
    import webbrowser

    from rehearsal.sdk import cli

    browser, _, _ = _console()
    monkeypatch.setattr(webbrowser, "open", lambda url: browser.post(f"/v1/cli/logins/{url.rsplit('code=', 1)[1]}/deny").status_code == 200)
    monkeypatch.setenv("REHEARSAL_CONFIG", str(tmp_path / "config.json"))
    with pytest.raises(SystemExit, match="denied"):
        cli.main(["login", "--url", live_server])
    assert not (tmp_path / "config.json").exists()  # nothing saved
