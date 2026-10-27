"""Emulated external dependencies plus the world's edge proxy.

One process per world instance. Applications reach it at ``http://providers:9000``
(payments/email/shipping HTTP contracts and ``/sink/{name}`` for webhooks) and at
``providers:2525`` for SMTP. Every effect lands in an append-only journal keyed by
``Idempotency-Key`` (or Message-ID for SMTP) so the evaluator can count real effects.

``/__svc/{service}/...`` forwards host-side gateway traffic into the isolated
world network and ``/__admin/journal`` exposes the journal; both require the
per-instance admin token. Applications never receive that token.

Fidelity: these are small contracts inspired by common payment/email/shipping
APIs, not reproductions of any provider.
"""

from __future__ import annotations

import asyncio
import email
import email.policy
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

DATA = Path(os.environ.get("RH_PROVIDER_DATA", "/data"))
ADMIN_TOKEN = os.environ.get("RH_ADMIN_TOKEN", "")
SERVICES: dict[str, str] = json.loads(os.environ.get("RH_SERVICES", "{}"))  # name -> base url

DATA.mkdir(parents=True, exist_ok=True)
_lock = threading.Lock()
_db = sqlite3.connect(DATA / "providers.db", check_same_thread=False)
_db.execute(
    """CREATE TABLE IF NOT EXISTS effects (
        id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        operation TEXT NOT NULL,
        idempotency_key TEXT,
        reference TEXT,
        amount INTEGER,
        status TEXT NOT NULL,
        request_json TEXT NOT NULL,
        response_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )"""
)
_db.execute(
    "CREATE UNIQUE INDEX IF NOT EXISTS effects_idem ON effects(provider, operation, idempotency_key) "
    "WHERE idempotency_key IS NOT NULL"
)
_db.commit()

SMTP_PORT = int(os.environ.get("RH_SMTP_PORT", "2525"))


async def _smtp_session(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Minimal SMTP receiver: enough of RFC 5321 for application mailers."""

    def send(line: str) -> None:
        writer.write((line + "\r\n").encode())

    mail_from, rcpt = "", []
    send("220 providers Rehearsal SMTP sink")
    await writer.drain()
    try:
        while line := await reader.readline():
            cmd = line.decode(errors="replace").strip()
            verb = cmd[:4].upper()
            if verb in ("HELO", "EHLO"):
                send("250-providers" if verb == "EHLO" else "250 providers")
                if verb == "EHLO":
                    send("250-8BITMIME")
                    send("250 SIZE 10485760")
            elif verb == "MAIL":
                mail_from, rcpt = cmd.partition(":")[2].strip(" <>"), []
                send("250 OK")
            elif verb == "RCPT":
                rcpt.append(cmd.partition(":")[2].strip(" <>"))
                send("250 OK")
            elif verb == "DATA":
                send("354 End data with <CR><LF>.<CR><LF>")
                await writer.drain()
                chunks: list[bytes] = []
                while (data := await reader.readline()) not in (b".\r\n", b".\n", b""):
                    chunks.append(data[1:] if data.startswith(b"..") else data)
                msg = email.message_from_bytes(b"".join(chunks), policy=email.policy.default)
                body = msg.get_body(preferencelist=("plain", "html"))
                text = body.get_content() if body is not None else ""
                message_id = (msg.get("Message-ID") or f"<{uuid.uuid4().hex}@sink>").strip()
                _record(
                    "smtp",
                    "send",
                    message_id,
                    {"from": mail_from, "to": rcpt, "subject": str(msg.get("Subject", "")), "body": text[:4000]},
                    {"id": f"smtp_{uuid.uuid4().hex[:16]}", "status": "accepted", "to": rcpt},
                    reference=message_id,
                )
                send("250 OK queued")
            elif verb == "QUIT":
                send("221 Bye")
                await writer.drain()
                break
            elif verb in ("RSET", "NOOP"):
                mail_from, rcpt = ("", []) if verb == "RSET" else (mail_from, rcpt)
                send("250 OK")
            else:
                send("502 Command not implemented")
            await writer.drain()
    finally:
        writer.close()


async def _lifespan(_app: FastAPI):
    server = await asyncio.start_server(_smtp_session, "0.0.0.0", SMTP_PORT)
    try:
        yield
    finally:
        server.close()


app = FastAPI(title="Rehearsal emulated providers", lifespan=_lifespan)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record(
    provider: str,
    operation: str,
    key: str | None,
    request: dict[str, Any],
    response: dict[str, Any],
    *,
    reference: str | None = None,
    amount: int | None = None,
    status: str = "succeeded",
) -> dict[str, Any]:
    """Writes one effect, or returns the stored response for a repeated key."""
    with _lock:
        if key:
            row = _db.execute(
                "SELECT response_json FROM effects WHERE provider=? AND operation=? AND idempotency_key=?",
                (provider, operation, key),
            ).fetchone()
            if row:
                return json.loads(row[0])
        _db.execute(
            "INSERT INTO effects VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                response["id"],
                provider,
                operation,
                key,
                reference,
                amount,
                status,
                json.dumps(request, sort_keys=True),
                json.dumps(response, sort_keys=True),
                _now(),
            ),
        )
        _db.commit()
    return response


def _find(provider: str, operation: str, **where: Any) -> list[dict[str, Any]]:
    sql = "SELECT response_json FROM effects WHERE provider=? AND operation=?"
    args: list[Any] = [provider, operation]
    for k, v in where.items():
        sql += f" AND {k}=?"
        args.append(v)
    with _lock:
        return [json.loads(r[0]) for r in _db.execute(sql + " ORDER BY created_at", args).fetchall()]


# --------------------------------------------------------------------------- payments


class ChargeIn(BaseModel):
    amount: int = Field(gt=0)
    currency: str = "usd"
    reference: str


class RefundIn(BaseModel):
    charge_id: str
    amount: int = Field(gt=0)
    reason: str = ""


@app.post("/payments/charges", status_code=201)
def create_charge(body: ChargeIn, idempotency_key: str | None = Header(None)) -> dict[str, Any]:
    resp = {"id": f"ch_{uuid.uuid4().hex[:16]}", "object": "charge", "status": "succeeded", **body.model_dump()}
    return _record("payments", "charge", idempotency_key, body.model_dump(), resp, reference=body.reference, amount=body.amount)


@app.post("/payments/refunds", status_code=201)
def create_refund(body: RefundIn, idempotency_key: str | None = Header(None)) -> dict[str, Any]:
    with _lock:
        row = _db.execute(
            "SELECT response_json FROM effects WHERE provider='payments' AND operation='charge' AND id=?",
            (body.charge_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "charge not found")
    charge = json.loads(row[0])
    if idempotency_key:
        prior = _find("payments", "refund", idempotency_key=idempotency_key)
        if prior:
            return prior[0]
    refunded = sum(r["amount"] for r in _find("payments", "refund", reference=charge["reference"]))
    if refunded + body.amount > charge["amount"]:
        raise HTTPException(409, f"refund exceeds charge: already refunded {refunded} of {charge['amount']}")
    resp = {
        "id": f"re_{uuid.uuid4().hex[:16]}",
        "object": "refund",
        "status": "succeeded",
        "charge_id": body.charge_id,
        "amount": body.amount,
        "reason": body.reason,
    }
    return _record("payments", "refund", idempotency_key, body.model_dump(), resp, reference=charge["reference"], amount=body.amount)


@app.get("/payments/refunds")
def list_refunds(charge_id: str) -> list[dict[str, Any]]:
    return [r for r in _find("payments", "refund") if r["charge_id"] == charge_id]


# --------------------------------------------------------------------------- email


class EmailIn(BaseModel):
    to: str
    subject: str
    body: str
    reference: str | None = None


@app.post("/email/messages", status_code=201)
def send_email(body: EmailIn, idempotency_key: str | None = Header(None)) -> dict[str, Any]:
    resp = {"id": f"em_{uuid.uuid4().hex[:16]}", "object": "email", "status": "queued", "to": body.to}
    return _record("email", "send", idempotency_key, body.model_dump(), resp, reference=body.reference)


# --------------------------------------------------------------------------- shipping


class ShipmentIn(BaseModel):
    reference: str
    address: str
    items: list[str]


@app.post("/shipping/shipments", status_code=201)
def create_shipment(body: ShipmentIn, idempotency_key: str | None = Header(None)) -> dict[str, Any]:
    resp = {"id": f"sh_{uuid.uuid4().hex[:16]}", "object": "shipment", "status": "label_created", **body.model_dump()}
    return _record("shipping", "create", idempotency_key, body.model_dump(), resp, reference=body.reference)


@app.post("/shipping/shipments/{shipment_id}/cancel")
def cancel_shipment(shipment_id: str, idempotency_key: str | None = Header(None)) -> dict[str, Any]:
    created = [r for r in _find("shipping", "create") if r["id"] == shipment_id]
    if not created:
        raise HTTPException(404, "shipment not found")
    if _find("shipping", "cancel", reference=created[0]["reference"]):
        raise HTTPException(409, "shipment already cancelled")
    resp = {"id": f"sc_{uuid.uuid4().hex[:16]}", "object": "shipment_cancellation", "shipment_id": shipment_id, "status": "cancelled"}
    return _record("shipping", "cancel", idempotency_key, {"shipment_id": shipment_id}, resp, reference=created[0]["reference"])


# --------------------------------------------------------------------------- webhooks


@app.api_route("/sink/{name}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def webhook_sink(name: str, request: Request) -> dict[str, Any]:
    raw = (await request.body()).decode(errors="replace")[:8000]
    try:
        payload: Any = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        payload = raw
    resp = {"id": f"wh_{uuid.uuid4().hex[:16]}", "status": "received"}
    return _record("webhook", name, None, {"method": request.method, "payload": payload}, resp)


# --------------------------------------------------------------------------- privileged surface


def _admin(token: str | None) -> None:
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(403, "admin token required")


@app.get("/__health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/__admin/journal")
def journal(x_rehearsal_admin: str | None = Header(None)) -> list[dict[str, Any]]:
    _admin(x_rehearsal_admin)
    cols = ["id", "provider", "operation", "idempotency_key", "reference", "amount", "status", "request_json", "response_json", "created_at"]
    with _lock:
        rows = _db.execute(f"SELECT {','.join(cols)} FROM effects ORDER BY created_at, id").fetchall()
    return [dict(zip(cols, r)) for r in rows]


_HOP = {"host", "content-length", "connection", "x-rehearsal-admin", "accept-encoding", "transfer-encoding"}
_client = httpx.AsyncClient(timeout=30.0)


@app.api_route("/__svc/{service}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(service: str, path: str, request: Request) -> Response:
    _admin(request.headers.get("x-rehearsal-admin"))
    base = SERVICES.get(service)
    if base is None:
        raise HTTPException(404, f"unknown service {service}")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP}
    try:
        upstream = await _client.request(
            request.method,
            f"{base}/{path}",
            params=list(request.query_params.multi_items()),
            content=await request.body(),
            headers=headers,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"upstream {service} unreachable: {exc.__class__.__name__}") from exc
    passthrough = {k: v for k, v in upstream.headers.items() if k.lower() in {"content-type", "location"}}
    return Response(upstream.content, status_code=upstream.status_code, headers=passthrough)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("RH_HOST", "0.0.0.0"), port=int(os.environ.get("RH_PORT", "9000")), log_level="warning")
