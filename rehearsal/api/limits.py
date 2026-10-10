"""Reject oversized bodies before multipart parsing can spool them to disk."""

from fastapi import HTTPException, Request
from starlette._utils import get_route_path
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import auth

UPLOAD_BODY_LIMIT = 501 * 1024 * 1024
WEBHOOK_BODY_LIMIT = 1 << 20

class RequestBodyLimit:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = get_route_path(scope).rstrip("/") if scope["type"] == "http" else ""
        upload = (scope["type"] == "http" and scope.get("method") == "POST"
                  and path.startswith("/v1/applications/") and path.endswith("/source"))
        webhook = scope["type"] == "http" and path == "/v1/billing/webhook"
        if not upload and not webhook:
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        if upload:
            try:
                # Authenticate before reading any file bytes. The route reuses this principal.
                p = await run_in_threadpool(auth.principal, request)
                scope.setdefault("state", {})["authenticated_principal"] = p
            except HTTPException as exc:
                await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)
                return
        limit = UPLOAD_BODY_LIMIT if upload else WEBHOOK_BODY_LIMIT  # file cap plus multipart framing
        length = request.headers.get("content-length")
        if length is not None:
            try:
                size = int(length)
                if size < 0:
                    raise ValueError
            except ValueError:
                await JSONResponse({"detail": "invalid content length"}, status_code=400)(scope, receive, send)
                return
            if size > limit:
                await JSONResponse({"detail": "payload too large"}, status_code=413)(scope, receive, send)
                return
        consumed = 0

        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    raise HTTPException(413, "payload too large")
            return message

        await self.app(scope, bounded_receive, send)
