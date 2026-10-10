"""API guards without an application server, database, or network."""

from contextlib import contextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError

from rehearsal.api import app as api
from rehearsal.api import limits
from rehearsal.api.auth import Principal


@pytest.fixture(autouse=True)
def inline_worker_calls(monkeypatch):
    # Authentication and DB work are mocked here. Avoid event-loop wakeup sockets
    # in restricted environments; these tests exercise request boundaries.
    async def inline(fn, *args, **kwargs):
        return fn(*args, **kwargs)
    monkeypatch.setattr(limits, "run_in_threadpool", inline)
    monkeypatch.setattr(api.asyncio, "to_thread", inline)


async def invoke(monkeypatch, *, authenticated=True, length=None, chunks=(b"x",), path="/v1/applications/missing/source", root_path=""):
    sent, consumed = [], []
    messages = iter(chunks)
    scope = {"type": "http", "method": "POST", "path": path, "root_path": root_path, "headers": [], "state": {}}
    if length is not None:
        scope["headers"] = [(b"content-length", str(length).encode())]
    def authenticate(request):
        if not authenticated:
            raise HTTPException(401, "authentication required")
        return Principal("p", "k", ["admin"])
    monkeypatch.setattr(limits.auth, "principal", authenticate)
    async def receive():
        chunk = next(messages, b"")
        consumed.append(chunk)
        return {"type": "http.request", "body": chunk, "more_body": bool(chunk)}
    async def send(message): sent.append(message)
    async def downstream(scope, receive, send):
        try:
            while (await receive()).get("more_body"):
                pass
        except HTTPException as exc:
            await send({"type": "http.response.start", "status": exc.status_code})
        else:
            await send({"type": "http.response.start", "status": 200})
    await limits.RequestBodyLimit(downstream)(scope, receive, send)
    return sent[0]["status"], consumed, scope


@pytest.mark.asyncio
async def test_lifespan_without_path_passes_through():
    downstream, receive, send = AsyncMock(), AsyncMock(), AsyncMock()
    scope = {"type": "lifespan"}
    await limits.RequestBodyLimit(downstream)(scope, receive, send)
    downstream.assert_awaited_once_with(scope, receive, send)


@pytest.mark.asyncio
async def test_unauthenticated_upload_rejected_before_read(monkeypatch):
    status, consumed, _ = await invoke(monkeypatch, authenticated=False)
    assert status == 401 and consumed == []


@pytest.mark.asyncio
async def test_root_path_upload_authenticates_before_read(monkeypatch):
    status, consumed, _ = await invoke(
        monkeypatch, authenticated=False, root_path="/proxy", path="/proxy/v1/applications/missing/source",
    )
    assert status == 401 and consumed == []


@pytest.mark.asyncio
async def test_oversized_upload_rejected_before_spooling(monkeypatch):
    status, consumed, _ = await invoke(monkeypatch, length=limits.UPLOAD_BODY_LIMIT + 1)
    assert status == 413 and consumed == []


@pytest.mark.asyncio
async def test_chunked_upload_counts_actual_bytes(monkeypatch):
    monkeypatch.setattr(limits, "UPLOAD_BODY_LIMIT", 3)
    status, consumed, _ = await invoke(monkeypatch, chunks=(b"ab", b"cd"))
    assert status == 413 and consumed == [b"ab", b"cd"]


@pytest.mark.asyncio
async def test_small_upload_reuses_authenticated_principal(monkeypatch):
    status, _, scope = await invoke(monkeypatch)
    assert status == 200 and scope["state"]["authenticated_principal"].project_id == "p"


@pytest.mark.asyncio
async def test_webhook_stream_is_bounded_without_auth(monkeypatch):
    monkeypatch.setattr(limits, "WEBHOOK_BODY_LIMIT", 3)
    status, consumed, _ = await invoke(monkeypatch, authenticated=False, chunks=(b"abcd",), path="/v1/billing/webhook")
    assert status == 413


@pytest.mark.asyncio
@pytest.mark.parametrize("length", [None, 4])
async def test_root_path_webhook_body_is_bounded(monkeypatch, length):
    monkeypatch.setattr(limits, "WEBHOOK_BODY_LIMIT", 3)
    status, consumed, _ = await invoke(
        monkeypatch, authenticated=False, length=length, chunks=(b"abcd",),
        root_path="/proxy", path="/proxy/v1/billing/webhook",
    )
    assert status == 413
    assert consumed == ([b"abcd"] if length is None else [])


def test_login_rotation_hits_ip_limit_before_password_verification(monkeypatch):
    monkeypatch.setattr(api, "_attempts", {})
    monkeypatch.setattr(api, "_attempt_deadlines", {})
    monkeypatch.setattr(api, "_attempt_cleanup", 0)
    password = Mock(side_effect=HTTPException(401, "invalid credentials"))
    monkeypatch.setattr(api, "password_login", password)
    request = Request({"type": "http", "method": "POST", "path": "/v1/auth/login", "headers": [], "client": ("same-ip", 1)})
    for n in range(31):
        with pytest.raises(HTTPException) as error:
            api.sign_in(api.LoginIn(email=f"{n}@example.test", password="bad"), Response(), request)
        assert error.value.status_code == (401 if n < 30 else 429)
    assert password.call_count == 30


def test_limiter_expires_inactive_keys(monkeypatch):
    monkeypatch.setattr(api, "_attempts", {"old": [0]})
    monkeypatch.setattr(api, "_attempt_deadlines", {"old": 1})
    monkeypatch.setattr(api, "_attempt_cleanup", 0)
    monkeypatch.setattr(api.time, "time", lambda: 100)
    api._throttle("new", 2, 10, "limited")
    assert "old" not in api._attempts and "old" not in api._attempt_deadlines


@pytest.mark.asyncio
async def test_webhook_does_not_acknowledge_unrelated_integrity_failure(monkeypatch):
    org = NS(id="org")
    @contextmanager
    def transaction():
        yield NS(get=lambda *a: None, add=lambda *a: None, flush=lambda: None, refresh=lambda *a, **kw: None)
    monkeypatch.setattr(api, "session", transaction)
    monkeypatch.setattr(api.billing, "verify_webhook", lambda *a: None)
    monkeypatch.setattr(api.billing, "org_for_event", lambda *a: org)
    monkeypatch.setattr(api.billing, "sync", Mock(side_effect=IntegrityError("credit", {}, Exception("constraint"))))
    request = NS(headers={"webhook-id": "unique"}, body=None)
    async def body(): return b'{"type":"payment.succeeded","data":{}}'
    request.body = body
    with pytest.raises(IntegrityError):
        await api.billing_webhook(request)
