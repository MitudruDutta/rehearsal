"""Tool factories for compiler roles. Builder tools act only inside the build
sandbox; nothing here can reach a production system or the platform itself."""

from __future__ import annotations

import json
from typing import Any

from ..core.contracts import WorldManifest
from ..evaluator.probes import Prober, ProbeError
from ..runner.gateway import Gateway, basic_header
from ..runner.runtime import WorldInstance, inspect_image
from .agent import Tool, params
from .apispec import GraphQLSchema, Operation, search
from .repo import Repo

S = {"type": "string"}
I = {"type": "integer"}


def repo_tools(repo: Repo) -> list[Tool]:
    return [
        Tool("list_dir", "List a directory of the application source.", params({"path": S}), lambda a: repo.list_dir(a.get("path", "."))),
        Tool(
            "read_file",
            "Read a source file with line numbers. Use start/end for large files.",
            params({"path": S, "start": I, "end": I}, ["path"]),
            lambda a: repo.read_file(a["path"], int(a.get("start") or 1), int(a["end"]) if a.get("end") else None),
        ),
        Tool("grep", "Regex search across the source; glob filters file names (e.g. *.rb).", params({"pattern": S, "glob": S}, ["pattern"]), lambda a: repo.grep(a["pattern"], a.get("glob") or "*")),
        Tool("find", "Find files by name glob (e.g. *swagger*.json).", params({"name_glob": S}), lambda a: repo.find(a["name_glob"])),
    ]


def image_tools() -> list[Tool]:
    return [Tool("inspect_image", "Show an image's default Cmd, Entrypoint, Env, ExposedPorts, Volumes, User, WorkingDir.", params({"image": S}), lambda a: inspect_image(a["image"]))]


def _http(instance: WorldInstance, a: dict[str, Any]) -> dict[str, Any]:
    headers = dict(a.get("headers") or {})
    if a.get("basic_auth"):
        user, pw = a["basic_auth"]
        headers["Authorization"] = basic_header(user, pw)
    resp = instance.http(a["service"], a.get("method", "GET"), a["path"], headers=headers, json_body=a.get("json"), params=a.get("query"))
    try:
        body: Any = resp.json()
    except ValueError:
        body = resp.text[:6000]
    return {"status": resp.status_code, "body": body}


def live_tools(instance: WorldInstance, prober: Prober, secrets: dict[str, str]) -> list[Tool]:
    def sql(a: dict[str, Any]) -> Any:
        prober.invalidate()
        try:
            return prober.query(a["query"], a.get("params") or {}, a.get("probe"))[:50]
        except ProbeError as exc:
            return f"error: {exc}"

    def exec_cmd(a: dict[str, Any]) -> dict[str, Any]:
        rc, out, err = instance.exec(a["service"], list(a["command"]), user=a.get("user"), timeout=300)
        return {"exit_code": rc, "stdout": out[-6000:], "stderr": err[-3000:]}

    return [
        Tool(
            "http_request",
            "Send an HTTP request to a service inside the sandbox (path relative to the service root). headers/json/query optional; basic_auth is [user, password].",
            params({"service": S, "method": S, "path": S, "headers": {"type": "object"}, "json": {}, "query": {"type": "object"}, "basic_auth": {"type": "array", "items": S}}, ["service", "method", "path"]),
            lambda a: _http(instance, a),
        ),
        Tool(
            "exec_command",
            "Run a command inside a sandbox service container (argv list, no shell unless you call sh -c).",
            params({"service": S, "command": {"type": "array", "items": S}, "user": S}, ["service", "command"]),
            exec_cmd,
        ),
        Tool("sql_query", "Run one read-only SQL statement against the application's state probe (returns up to 50 rows).", params({"query": S, "params": {"type": "object"}, "probe": S}, ["query"]), sql),
        Tool("service_logs", "Tail a service's container logs.", params({"service": S, "tail": I}, ["service"]), lambda a: instance.logs(a["service"], int(a.get("tail") or 120))),
        Tool("list_secrets", "List generated secret names (values are available to steps via {{secret.NAME}}).", params({}, []), lambda a: sorted(secrets)),
        Tool("get_secret", "Read a generated secret value for exploratory requests (never paste it into submitted steps; use {{secret.NAME}}).", params({"name": S}), lambda a: secrets.get(a["name"], "unknown secret")),
    ]


def schema_tools(prober: Prober) -> list[Tool]:
    def tables(_: dict[str, Any]) -> Any:
        prober.invalidate()
        p = prober.probe(None)
        q = {
            "sqlite": "SELECT group_concat(name, ', ') FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'",
            "postgres": "SELECT string_agg(table_name, ', ' ORDER BY table_name) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'",
            "mysql": "SELECT group_concat(table_name ORDER BY table_name SEPARATOR ', ') FROM information_schema.tables WHERE table_schema = DATABASE() AND table_type='BASE TABLE'",
        }[p.kind]
        return prober.query(q)[0][0]

    def describe(a: dict[str, Any]) -> Any:
        prober.invalidate()
        p = prober.probe(None)
        name = a["table"]
        q = {
            "sqlite": "SELECT name || ' ' || type FROM pragma_table_info(:t)",
            "postgres": "SELECT column_name || ' ' || data_type FROM information_schema.columns WHERE table_schema='public' AND table_name = :t ORDER BY ordinal_position",
            "mysql": "SELECT concat(column_name, ' ', column_type) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = :t ORDER BY ordinal_position",
        }[p.kind]
        try:
            rows = prober.query(q, {"t": name})
        except ProbeError as exc:
            return f"error: {exc}"
        return [r[0] for r in rows] or f"no table {name}"

    return [
        Tool("list_tables", "List application database tables.", params({}, []), tables),
        Tool("describe_table", "Columns and types of one table.", params({"table": S}), describe),
    ]


def api_tools(ops: list[Operation] | None, gql: GraphQLSchema | None) -> list[Tool]:
    tools: list[Tool] = []
    if ops:
        index = {o.op_id: o for o in ops}
        tools += [
            Tool("api_search", f"Search the application's REST operations ({len(ops)} total) by keywords.", params({"query": S}), lambda a: search(ops, a["query"])),
            Tool("api_operation", "Full detail (params, body schema) of one REST operation by op_id.", params({"op_id": S}), lambda a: index[a["op_id"]].detail() if a["op_id"] in index else f"unknown op_id {a['op_id']}"),
        ]
    if gql:
        tools += [
            Tool("graphql_search", "Search GraphQL query/mutation root fields by keywords.", params({"query": S}), lambda a: gql.search(a["query"])),
            Tool("graphql_type", "Describe a GraphQL type or input type.", params({"name": S}), lambda a: gql.describe_type(a["name"])),
        ]
    return tools


def role_call_tool(instance: WorldInstance, manifest_fn: Any, variables: dict[str, Any]) -> Tool:
    """Calls the app as a declared role (uses that role's credential)."""

    def call(a: dict[str, Any]) -> Any:
        manifest: WorldManifest = manifest_fn()
        gw = Gateway(instance, manifest, variables)
        headers = gw.credential_headers(a["role"])
        resp = instance.http(a["service"], a.get("method", "GET"), a["path"], headers=headers, json_body=a.get("json"), params=a.get("query"))
        try:
            return {"status": resp.status_code, "body": resp.json()}
        except ValueError:
            return {"status": resp.status_code, "body": resp.text[:4000]}

    return Tool(
        "call_as_role",
        "Send an HTTP request as one of the declared roles (its credential is attached).",
        params({"role": S, "service": S, "method": S, "path": S, "json": {}, "query": {"type": "object"}}, ["role", "service", "method", "path"]),
        call,
    )


def dumps(value: Any) -> str:
    return json.dumps(value, indent=1, default=str)
