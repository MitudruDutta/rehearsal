"""API discovery: Swagger 2.0 / OpenAPI 3 operations and GraphQL introspection.

Specs only supply interface shapes. Business rules still come from source,
documentation, and validation runs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from ..core.contracts import ToolParam, ToolSpec

SPEC_PATHS = [
    "/swagger.v1.json", "/api/swagger.json", "/swagger.json", "/openapi.json", "/api/openapi.json",
    "/v3/api-docs", "/api/v1/swagger.json", "/swagger/doc.json", "/api/docs/openapi.json", "/docs/openapi.json",
]
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class Operation:
    op_id: str
    method: str
    path: str
    summary: str
    tags: list[str]
    params: list[dict[str, Any]] = field(default_factory=list)  # {name, in, required, schema, description}
    body: dict[str, Any] | None = None  # JSON schema (refs resolved one level deep)

    def brief(self) -> str:
        return f"{self.op_id}: {self.method} {self.path} - {self.summary[:120]}"

    def detail(self) -> dict[str, Any]:
        return {"op_id": self.op_id, "method": self.method, "path": self.path, "summary": self.summary, "params": self.params, "body": self.body}


# libyaml when installed (PyYAML's wheels bundle it): a large description (a few MB of YAML) loads in under a
# second with it, and takes minutes with the pure-Python loader, long enough to stall a build's discovery step.
_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

# An application's API description is untrusted input: bound everything it can make us do.
MAX_SPEC_BYTES = 40_000_000  # the largest description read; real ones are a few MB
MAX_OPERATIONS = 3000  # operations kept from one description
RESOLVE_BUDGET = 2000  # schema nodes one $ref expansion may produce: wide references and YAML alias bombs stay cheap


def parse_spec(text: str) -> dict[str, Any]:
    if len(text) > MAX_SPEC_BYTES:
        raise ValueError(f"API description is larger than {MAX_SPEC_BYTES // 1_000_000} MB")
    text = text.strip()
    return json.loads(text) if text.startswith("{") else yaml.load(text, Loader=_YAML_LOADER)  # noqa: S506 - a safe loader


def _resolve(spec: dict[str, Any], node: Any, hops: int = 0, budget: list[int] | None = None) -> Any:
    """Inlines local $refs. Only ref hops count toward the limit (it stops cycles);
    plain nesting such as requestBody.content.<media>.schema must not truncate the schema. One call produces at most
    RESOLVE_BUDGET nodes, so a wide or self-multiplying schema becomes a plain object instead of exponential work."""
    budget = [RESOLVE_BUDGET] if budget is None else budget
    if isinstance(node, (dict, list)):
        budget[0] -= 1
        if budget[0] < 0:
            return {"type": "object"}
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str) and node["$ref"].startswith("#/"):
            if hops >= 4:
                return {"type": "object"}
            target: Any = spec
            for part in node["$ref"][2:].split("/"):
                target = target.get(part, {}) if isinstance(target, dict) else {}
            return _resolve(spec, target, hops + 1, budget)
        return {k: _resolve(spec, v, hops, budget) for k, v in node.items() if k not in ("example", "examples", "xml")}
    if isinstance(node, list):
        return [_resolve(spec, v, hops, budget) for v in node[:50]]
    return node


def _slugify(text: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", text)
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return (s or "op")[:48] if s[:1].isalpha() else ("op_" + s)[:48]


def operations(spec: dict[str, Any]) -> list[Operation]:
    base = spec.get("basePath", "") if "swagger" in spec else ""
    if not base and spec.get("servers"):
        url = str(spec["servers"][0].get("url", ""))
        base = re.sub(r"^https?://[^/]+", "", url) if url.startswith(("http", "/")) else ""
    ops: list[Operation] = []
    seen: set[str] = set()
    for path, item in (spec.get("paths") or {}).items():
        shared = item.get("parameters", []) if isinstance(item, dict) else []
        for method, op in (item or {}).items():
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"} or not isinstance(op, dict):
                continue
            if len(ops) >= MAX_OPERATIONS:
                return ops
            op_id = base_id = _slugify(op.get("operationId") or f"{method}_{path}")
            n = 2
            while op_id in seen:  # a numbered suffix that fits the 48-character limit; appending and cutting could repeat forever
                op_id = f"{base_id[:48 - len(str(n)) - 1]}_{n}"
                n += 1
            seen.add(op_id)
            params, body = [], None
            for raw in [*shared, *op.get("parameters", [])]:
                p = _resolve(spec, raw)
                loc = p.get("in")
                if loc == "body":
                    body = p.get("schema", {"type": "object"})
                elif loc == "formData":
                    body = body or {"type": "object", "properties": {}}
                    body.setdefault("properties", {})[p["name"]] = {"type": p.get("type", "string")}
                elif loc in ("path", "query"):
                    schema = p.get("schema") or {k: p[k] for k in ("type", "enum", "items", "format") if k in p}
                    params.append({"name": p["name"], "in": loc, "required": bool(p.get("required")) or loc == "path", "schema": schema or {"type": "string"}, "description": (p.get("description") or "")[:200]})
            if "requestBody" in op:
                rb = _resolve(spec, op["requestBody"])
                content = rb.get("content", {})
                media = content.get("application/json") or next(iter(content.values()), {})
                body = media.get("schema", {"type": "object"})
            ops.append(Operation(op_id, method.upper(), (base.rstrip("/") + path) or "/", (op.get("summary") or op.get("description") or "")[:300], op.get("tags", []), params, body))
    return ops


def search(ops: list[Operation], query: str, limit: int = 40) -> str:
    words = [w for w in re.split(r"\W+", query.lower()) if w]
    scored = []
    for op in ops:
        hay = f"{op.op_id} {op.method} {op.path} {op.summary} {' '.join(op.tags)}".lower()
        score = sum(hay.count(w) for w in words)
        if score:
            scored.append((score, op))
    scored.sort(key=lambda x: -x[0])
    return "\n".join(op.brief() for _, op in scored[:limit]) or "(no operations match)"


def _compact_schema(schema: Any, depth: int = 0) -> Any:
    if not isinstance(schema, dict):
        return {"type": "string"}
    out: dict[str, Any] = {}
    for key in ("type", "enum", "format", "description"):
        if key in schema:
            out[key] = schema[key] if key != "description" else str(schema[key])[:150]
    if schema.get("type") == "array" or "items" in schema:
        out["type"] = "array"
        out["items"] = _compact_schema(schema.get("items", {}), depth + 1) if depth < 2 else {}
    if "properties" in schema and depth < 2:
        out["type"] = "object"
        out["properties"] = {k: _compact_schema(v, depth + 1) for k, v in list(schema["properties"].items())[:40]}
    if "type" not in out:
        out["type"] = "object" if "properties" in schema else "string"
    return out


def to_tool(op: Operation, *, name: str, description: str, service: str, roles: list[str], body_fields: list[str] | None = None) -> ToolSpec:
    """Deterministic operation -> tool conversion. ``body_fields`` limits which
    top-level body properties are exposed; nested bodies go through one ``body`` param."""
    params: list[ToolParam] = []
    for p in op.params:
        params.append(ToolParam(name=p["name"], location=p["in"], schema=_compact_schema(p["schema"]), required=p["required"], description=p["description"]))
    if op.body is not None:
        props = op.body.get("properties") if isinstance(op.body, dict) else None
        req = op.body.get("required") if isinstance(op.body, dict) else None
        required = {r for r in req if isinstance(r, str)} if isinstance(req, list) else set()
        taken = {p.name for p in params}
        if props and all(k not in taken for k in props):
            for k, v in props.items():
                if body_fields is not None and k not in body_fields and k not in required:
                    continue
                params.append(ToolParam(name=k, location="body", schema=_compact_schema(v), required=k in required, description=str(v.get("description", ""))[:200] if isinstance(v, dict) else ""))
        else:
            params.append(ToolParam(name="body", location="body", schema=_compact_schema(op.body), required=True, description="JSON request body"))
    path = re.sub(r"\{([^}]+)\}", lambda m: "{" + re.sub(r"[^A-Za-z0-9_]", "_", m.group(1)) + "}", op.path)
    for p in params:
        if p.location == "path":
            p.name = re.sub(r"[^A-Za-z0-9_]", "_", p.name)
    return ToolSpec(name=name, description=description, service=service, method=op.method, path=path, params=params, mutating=op.method in MUTATING, roles=roles)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- GraphQL

INTROSPECTION = """query { __schema { queryType { name } mutationType { name } types { kind name fields { name description args { name type { kind name ofType { kind name ofType { kind name ofType { kind name } } } } } type { kind name ofType { kind name ofType { kind name } } } } inputFields { name type { kind name ofType { kind name ofType { kind name } } } } } } }"""


def _type_str(t: dict[str, Any] | None) -> str:
    if not t:
        return "?"
    if t["kind"] == "NON_NULL":
        return _type_str(t.get("ofType")) + "!"
    if t["kind"] == "LIST":
        return "[" + _type_str(t.get("ofType")) + "]"
    return t.get("name") or "?"


@dataclass
class GraphQLSchema:
    types: dict[str, dict[str, Any]]
    query: str
    mutation: str | None

    @classmethod
    def from_introspection(cls, data: dict[str, Any]) -> "GraphQLSchema":
        s = data["data"]["__schema"]
        return cls({t["name"]: t for t in s["types"] if t.get("name")}, s["queryType"]["name"], (s.get("mutationType") or {}).get("name"))

    def root_fields(self) -> list[tuple[str, dict[str, Any]]]:
        out = []
        for root, kind in ((self.query, "query"), (self.mutation, "mutation")):
            if root and root in self.types:
                out += [(kind, f) for f in self.types[root].get("fields") or []]
        return out

    def search(self, query: str, limit: int = 40) -> str:
        words = [w for w in re.split(r"\W+", query.lower()) if w]
        scored = []
        for kind, f in self.root_fields():
            hay = f"{f['name']} {f.get('description') or ''}".lower()
            score = sum(hay.count(w) for w in words)
            if score:
                args = ", ".join(f"{a['name']}: {_type_str(a['type'])}" for a in f.get("args") or [])
                scored.append((score, f"{kind} {f['name']}({args}): {_type_str(f['type'])} - {(f.get('description') or '')[:100]}"))
        scored.sort(key=lambda x: -x[0])
        return "\n".join(s for _, s in scored[:limit]) or "(no fields match)"

    def describe_type(self, name: str) -> str:
        t = self.types.get(name)
        if not t:
            return f"unknown type {name}"
        fields = t.get("fields") or t.get("inputFields") or []
        lines = [f"{t['kind']} {name}"]
        for f in fields[:80]:
            args = ", ".join(f"{a['name']}: {_type_str(a['type'])}" for a in f.get("args") or [])
            lines.append(f"  {f['name']}{'(' + args + ')' if args else ''}: {_type_str(f['type'])}")
        return "\n".join(lines)
