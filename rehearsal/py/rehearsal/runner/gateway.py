"""Action gateway: the only path from an actor to the application.

It checks role authority immediately before dispatch, validates arguments
against the tool contract, attaches the role's credential and an
``Idempotency-Key`` equal to the operation id, applies armed faults, and
returns only what a real client would observe. The full request/response is
kept privately for the oracle and audit; the agent never sees dropped
responses or other roles' credentials.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from ..redaction import redact_any
from ..core.contracts import ToolSpec, WorldManifest, render_template
from .runtime import WorldInstance

VISIBLE_LIMIT = 6000


@dataclass
class GatewayResult:
    status: str  # SUCCEEDED | FAILED | UNKNOWN | REJECTED
    visible: dict[str, Any]
    request: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)
    rejected_reason: str | None = None
    fault: str | None = None
    mutating: bool = False


def without_traces(value: Any) -> Any:
    """A response body without server stack traces (a debug-mode GraphQL server attaches one to every error). They are
    long and say nothing a caller can act on, and they push the actual message out of any length limit."""
    if isinstance(value, dict):
        return {k: without_traces(v) for k, v in value.items() if k.lower() not in ("stacktrace", "traceback", "backtrace", "trace")}
    if isinstance(value, list):
        return [without_traces(v) for v in value]
    return value


def graphql_failed(body: Any, *, mutating: bool = True) -> str | None:
    """Why a GraphQL reply failed, or None. GraphQL answers HTTP 200 even when nothing happened: errors arrive in a
    top-level "errors" list (often with "data": {"field": null}, for example an expired token), or inside the mutation
    payload ("errors" / "userErrors", as Saleor and Shopify do). Treating those as success hides the real cause."""
    if not isinstance(body, dict):
        return None
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    if body.get("errors") and (mutating or not any(v is not None for v in data.values())):
        return json.dumps(without_traces(body["errors"]), default=str)[:1500]
    for payload in data.values():
        if isinstance(payload, dict):
            for key in ("errors", "userErrors"):
                if payload.get(key):
                    return json.dumps(without_traces(payload[key]), default=str)[:1500]
    return None


def basic_header(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def _truncate(value: Any) -> Any:
    text = json.dumps(value, default=str)
    if len(text) <= VISIBLE_LIMIT:
        return value
    return {"truncated": True, "preview": text[:VISIBLE_LIMIT]}


def _coerce(value: Any, schema: dict[str, Any]) -> Any:
    kind = schema.get("type")
    try:
        if kind == "integer" and isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        if kind == "number" and isinstance(value, str):
            return float(value)
        if kind == "boolean" and isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        if kind == "string" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    except ValueError:
        return value
    return value


class Gateway:
    def __init__(self, instance: WorldInstance, manifest: WorldManifest, variables: dict[str, Any]):
        self.instance = instance
        self.manifest = manifest
        self.variables = variables
        self.revoked: set[tuple[str, str]] = set()
        self.granted: set[tuple[str, str]] = set()
        self.faults: dict[str, list[str]] = {}

    # ------------------------------------------------------------------ permissions

    def allowed(self, role: str, tool: ToolSpec) -> bool:
        if (role, tool.name) in self.revoked:
            return False
        return role in tool.roles or (role, tool.name) in self.granted

    def catalog(self, role: str) -> list[ToolSpec]:
        return [t for t in self.manifest.tools if self.allowed(role, t)]

    def revoke(self, role: str, tool: str) -> None:
        self.granted.discard((role, tool))
        self.revoked.add((role, tool))

    def grant(self, role: str, tool: str) -> None:
        self.revoked.discard((role, tool))
        self.granted.add((role, tool))

    def arm_fault(self, tool: str, mode: str, count: int = 1) -> None:
        self.faults.setdefault(tool, []).extend([mode] * count)

    def state(self) -> dict[str, Any]:
        return {"revoked": sorted(self.revoked), "granted": sorted(self.granted), "faults": self.faults}

    def load_state(self, data: dict[str, Any]) -> None:
        self.revoked = {tuple(x) for x in data.get("revoked", [])}  # type: ignore[misc]
        self.granted = {tuple(x) for x in data.get("granted", [])}  # type: ignore[misc]
        self.faults = {k: list(v) for k, v in data.get("faults", {}).items()}

    # ------------------------------------------------------------------ request building

    def credential_headers(self, role: str) -> dict[str, str]:
        spec = self.manifest.role(role)
        if spec is None or spec.credential is None:
            return {}
        scopes = {"vars": self.variables, "secret": self.instance.record.secrets}
        if spec.credential.basic:
            user, pw = (render_template(x, scopes) for x in spec.credential.basic)
            return {"Authorization": basic_header(user, pw)}
        return {spec.credential.header: render_template(spec.credential.template or "", scopes)}

    def build_request(self, tool: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
        params = {p.name: p for p in tool.params}
        unknown = sorted(set(args) - set(params))
        if unknown:
            raise ValueError(f"unknown arguments {unknown}; allowed: {sorted(params)}")
        missing = [p.name for p in tool.params if p.required and args.get(p.name) in (None, "")]
        if missing:
            raise ValueError(f"missing required arguments {missing}")
        path = tool.path
        query: dict[str, Any] = {}
        body: dict[str, Any] = {}
        variables: dict[str, Any] = {}
        for name, raw in args.items():
            p = params[name]
            value = _coerce(raw, p.schema_)
            if p.location == "path":
                path = path.replace("{" + name + "}", quote(str(value), safe=""))
            elif p.location == "query":
                query[name] = value
            elif p.location == "variables":
                variables[name] = value
            else:
                body[name] = value
        if tool.graphql is not None:
            json_body: Any = {"query": tool.graphql, "variables": variables}
        elif list(body) == ["body"] and isinstance(body["body"], (dict, list)):
            json_body = body["body"]  # a single "body" param carries the whole document
        else:
            json_body = body or None
        return {"method": tool.method, "service": tool.service, "path": path, "query": query, "json": json_body}

    # ------------------------------------------------------------------ dispatch

    def execute(self, role: str, tool_name: str, args: dict[str, Any], operation_id: str, *, allow_faults: bool = True) -> GatewayResult:
        tool = self.manifest.tool(tool_name)
        if tool is None:
            return GatewayResult("REJECTED", {"error": f"unknown tool {tool_name}"}, rejected_reason="unknown tool")
        if not self.allowed(role, tool):
            reason = f"role {role} is not permitted to use {tool_name}"
            return GatewayResult("REJECTED", {"error": reason}, rejected_reason=reason, mutating=tool.mutating)
        try:
            request = self.build_request(tool, args)
        except ValueError as exc:
            return GatewayResult("REJECTED", {"error": str(exc)}, rejected_reason=str(exc), mutating=tool.mutating)
        request["operation_id"] = operation_id
        request["role"] = role
        return self._dispatch(tool, request, allow_faults=allow_faults)

    def replay(self, request: dict[str, Any]) -> GatewayResult:
        """Re-sends a stored request with its original Idempotency-Key."""
        tool = self.manifest.tool(request.get("tool", ""))
        if tool is None or tool.name not in self.manifest.capabilities.idempotent_tools:
            return GatewayResult("REJECTED", {"error": "operation cannot be retried safely"}, rejected_reason="not idempotent")
        if not self.allowed(request["role"], tool):
            return GatewayResult("REJECTED", {"error": "permission no longer granted"}, rejected_reason="revoked")
        return self._dispatch(tool, request, allow_faults=False)

    def _dispatch(self, tool: ToolSpec, request: dict[str, Any], *, allow_faults: bool = True) -> GatewayResult:
        request = {**request, "tool": tool.name}
        headers = {**self.credential_headers(request["role"]), "Accept": "application/json"}
        if tool.mutating:
            headers["Idempotency-Key"] = request["operation_id"]
        fault = None
        if allow_faults and self.faults.get(tool.name):
            fault = self.faults[tool.name].pop(0)
        if fault == "timeout_before":
            return GatewayResult(
                "UNKNOWN",
                {"error": "request timed out; the outcome is unknown", "operation_id": request["operation_id"]},
                request=request,
                fault=fault,
                mutating=tool.mutating,
            )
        if fault == "error":
            return GatewayResult(
                "FAILED", {"status": 503, "error": "service temporarily unavailable"}, request=request, fault=fault, mutating=tool.mutating
            )
        if fault == "rate_limit":  # refused before it reached the application: nothing happened, retrying later is right
            return GatewayResult(
                "FAILED", {"status": 429, "error": "too many requests; this call was not carried out. Retry after 2 seconds.", "retry_after_s": 2},
                request=request, fault=fault, mutating=tool.mutating,
            )
        try:
            resp = self.instance.http(
                tool.service, tool.method, request["path"], headers=headers, json_body=request["json"], params=request["query"] or None
            )
        except httpx.HTTPError as exc:
            return GatewayResult(
                "UNKNOWN",
                {"error": f"network error ({exc.__class__.__name__}); the outcome is unknown", "operation_id": request["operation_id"]},
                request=request,
                mutating=tool.mutating,
            )
        try:
            body: Any = resp.json()
        except (json.JSONDecodeError, ValueError):
            body = resp.text[:VISIBLE_LIMIT]
        response = {"status": resp.status_code, "body": body}
        if fault == "drop_response":
            return GatewayResult(
                "UNKNOWN",
                {"error": "request timed out; the outcome is unknown", "operation_id": request["operation_id"]},
                request=request,
                response=response,
                fault=fault,
                mutating=tool.mutating,
            )
        ok = 200 <= resp.status_code < 300 and not (tool.graphql is not None and graphql_failed(body, mutating=tool.mutating))
        visible = {"status": resp.status_code, "body": _truncate(redact_any(body))}
        return GatewayResult("SUCCEEDED" if ok else "FAILED", visible, request=request, response=response, mutating=tool.mutating)
