"""Fast checks for logic that must not regress: contracts, request building,
read-only SQL guards, and secret redaction. No Docker or network needed."""

import pytest
from pydantic import ValidationError

from rehearsal.core.contracts import (
    ActorSpec,
    CheckSpec,
    GoalVersion,
    ParticipantSpec,
    RoleSpec,
    ScenarioSpec,
    ServiceSpec,
    ToolParam,
    ToolSpec,
    TrajectoryStep,
    WorldManifest,
    dig,
    render_value,
)
from rehearsal.evaluator.probes import ProbeError, params_used, single_statement
from rehearsal.evaluator.oracle import duplicate_effects
from rehearsal.runner.gateway import Gateway
from rehearsal.telemetry import _redact_any, redact


def _world(**extra):
    return WorldManifest(
        name="t",
        services=[ServiceSpec(name="db", image="postgres:16@sha256:x", data_paths=["/var/lib/postgresql/data"]), ServiceSpec(name="app", image="app@sha256:y", port=80, depends_on=["db"])],
        roles=[RoleSpec(name="agent", description="staff", customer_channel=True)],
        tools=[ToolSpec(name="get_order", description="d", service="app", method="GET", path="/orders/{order_id}", params=[ToolParam(name="order_id", location="path", schema={"type": "integer"}), ToolParam(name="expand", location="query", required=False)], mutating=False, roles=["agent"])],
        **extra,
    )


def test_manifest_rejects_dangling_references():
    with pytest.raises(ValidationError):
        WorldManifest(name="t", services=[ServiceSpec(name="app", image="x", port=80, depends_on=["missing"])])
    with pytest.raises(ValidationError):
        ToolSpec(name="t", description="d", service="app", method="GET", path="/x/{id}", mutating=False, roles=[])  # undeclared path param


def test_volumes_from_must_point_at_another_service():
    with pytest.raises(ValidationError):
        WorldManifest(name="t", services=[ServiceSpec(name="app", image="x", port=80, volumes_from="app")])
    with pytest.raises(ValidationError):
        ServiceSpec(name="mig", image="x", oneshot=True, volumes_from="app", data_paths=["/data"])


def test_scenario_cross_checks():
    sc = ScenarioSpec(
        id="s1", title="t", family="f",
        actors=[ActorSpec(id="a", role="agent", instructions="i", can_complete=True)],
        participant=ParticipantSpec(name="C", persona="p", opening_message="hi"),
        goals=[GoalVersion(version=1, instruction="x", checks=["c1"])],
        checks=[CheckSpec(id="c1", description="d", query="SELECT 1")],
        reference=[TrajectoryStep(actor="a", tool="delete_everything")],
    )
    problems = sc.validate_against(_world())
    assert any("unknown tool delete_everything" in p for p in problems)


def test_gateway_builds_requests_and_rejects_bad_args():
    w = _world()
    gw = Gateway(instance=None, manifest=w, variables={})  # type: ignore[arg-type]
    req = gw.build_request(w.tool("get_order"), {"order_id": "42", "expand": "items"})
    assert req["path"] == "/orders/42" and req["query"] == {"expand": "items"}
    with pytest.raises(ValueError, match="unknown arguments"):
        gw.build_request(w.tool("get_order"), {"order_id": 1, "drop_table": True})
    with pytest.raises(ValueError, match="missing required"):
        gw.build_request(w.tool("get_order"), {})
    # path params are URL-encoded so an argument cannot change the route
    assert gw.build_request(w.tool("get_order"), {"order_id": "1/../admin"})["path"] == "/orders/1%2F..%2Fadmin"


def test_gateway_role_authority_and_revocation():
    w = _world()
    gw = Gateway(instance=None, manifest=w, variables={})  # type: ignore[arg-type]
    assert gw.execute("intruder", "get_order", {"order_id": 1}, "op1").status == "REJECTED"
    gw.revoke("agent", "get_order")
    assert gw.execute("agent", "get_order", {"order_id": 1}, "op2").status == "REJECTED"


def test_sql_guards():
    assert single_statement("SELECT 1;") == "SELECT 1"
    with pytest.raises(ProbeError):
        single_statement("SELECT 1; DELETE FROM users")
    with pytest.raises(ProbeError):
        single_statement("\\! rm -rf /")
    assert params_used("SELECT * FROM t WHERE id = :order_id AND x::int = 1") == ["order_id"]


def test_templates_keep_types():
    assert render_value({"n": "{{vars.n}}", "s": "id-{{vars.n}}"}, {"vars": {"n": 5}}) == {"n": 5, "s": "id-5"}
    with pytest.raises(KeyError):
        render_value("{{vars.missing}}", {"vars": {}})


def test_dig_accepts_dotted_and_jsonpath():
    data = {"id": 3, "a": {"b": [{"c": 1}]}}
    assert dig(data, "a.b.0.c") == dig(data, "$.a.b[0].c") == 1
    assert dig(data, "$.id") == 3 and dig(data, "$") == data
    with pytest.raises(KeyError, match="found"):
        dig(data, "$.nope")


def test_duplicate_effects_counts_identical_requests():
    j = [
        {"provider": "payments", "operation": "refund", "request_json": '{"amount": 5, "charge_id": "c"}'},
        {"provider": "payments", "operation": "refund", "request_json": '{"charge_id": "c", "amount": 5}'},
        {"provider": "webhook", "operation": "x", "request_json": "{}"},
        {"provider": "webhook", "operation": "x", "request_json": "{}"},
    ]
    assert duplicate_effects(j) == 1


def test_redaction():
    assert "hunter2" not in redact('{"password": "hunter2"}')
    assert "abcdefghijklmnop" not in redact("Authorization: Bearer abcdefghijklmnop")
    masked = _redact_any({"basic_auth": ["admin", "s3cret-value"], "headers": {"Authorization": "token x"}, "note": "ok"})
    assert masked == {"basic_auth": "[REDACTED]", "headers": {"Authorization": "[REDACTED]"}, "note": "ok"}


def test_redact_drops_nul_bytes_postgres_cannot_store():
    from rehearsal import telemetry

    assert telemetry._redact_any({"out": "a\x00b"}) == {"out": "ab"}


def test_graphql_errors_hidden_in_http_200_replies_count_as_failures():
    from rehearsal.runner.gateway import graphql_failed

    expired = {"errors": [{"message": "Signature has expired"}], "data": {"productCreate": None}}
    payload = {"data": {"productCreate": {"errors": [{"field": "slug", "message": "already exists"}], "product": None}}}
    shopify = {"data": {"productCreate": {"userErrors": [{"message": "Title can't be blank"}]}}}
    assert "Signature has expired" in graphql_failed(expired)
    assert "already exists" in graphql_failed(payload) and "blank" in graphql_failed(shopify)
    assert graphql_failed({"data": {"productCreate": {"errors": [], "product": {"id": "1"}}}}) is None
    partial_read = {"errors": [{"message": "one field denied"}], "data": {"products": [{"id": "1"}], "secret": None}}
    assert graphql_failed(partial_read, mutating=False) is None and graphql_failed(partial_read, mutating=True)


def test_snapshot_paths_survive_moving_the_data_folder(tmp_path):
    from dataclasses import replace
    from pathlib import Path

    from rehearsal.config import settings

    here = replace(settings(), data_dir=tmp_path / "old")
    stored = here.stored_path(tmp_path / "old" / "worlds" / "wv_1" / "snapshot")
    assert stored == "worlds/wv_1/snapshot"
    moved = replace(settings(), data_dir=tmp_path / "new")  # the folder was copied to another machine
    assert moved.data_path(stored) == tmp_path / "new" / "worlds" / "wv_1" / "snapshot"
    assert moved.data_path("/elsewhere/snap") == Path("/elsewhere/snap") and here.stored_path("/elsewhere/snap") == "/elsewhere/snap"


def test_llm_spans_sent_to_tracing_carry_their_cost(monkeypatch):
    from types import SimpleNamespace

    from rehearsal import pricing, telemetry

    monkeypatch.setattr(telemetry, "settings", lambda: SimpleNamespace(model_compiler="nebius:deepseek-ai/DeepSeek-V4.1-Flash", model_agent="", model_participant="", model_improver=""))
    monkeypatch.setattr(pricing, "cached_quote", lambda provider, model: SimpleNamespace(cost=lambda p, c: (p * 0.30 + c * 1.20) / 1e6) if provider == "nebius" else None)
    span = {"attributes": {"tracing.span.kind": "llm", "tracing.llm.model_name": "deepseek-ai/DeepSeek-V4.1-Flash",
                           "tracing.llm.token_count.prompt": 1000, "tracing.llm.token_count.completion": 500}}
    assert abs(telemetry.mask(span)["attributes"]["tracing.llm.cost_usd"] - 0.0009) < 1e-9
    other = {"attributes": {"tracing.span.kind": "llm", "tracing.llm.model_name": "unknown-model"}}
    assert "tracing.llm.cost_usd" not in telemetry.mask(other)["attributes"]


def test_masking_a_span_never_waits_on_the_network(monkeypatch):
    """tracing drops a span whose mask misses its 5-second batch deadline: with no prices in memory the mask must
    return at once (without a cost) and load the price list in the background, never inline."""
    import threading
    import time
    from types import SimpleNamespace

    from rehearsal import pricing, telemetry

    monkeypatch.setattr(telemetry, "settings", lambda: SimpleNamespace(model_compiler="nebius:deepseek-ai/DeepSeek-V4.1-Flash", model_agent="", model_participant="", model_improver=""))
    monkeypatch.setattr(pricing, "_cache", {})
    monkeypatch.setattr(pricing, "_refreshing", set())
    loaded, loader_thread = threading.Event(), {}

    def slow_price_list():
        loader_thread["name"] = threading.current_thread().name
        time.sleep(0.5)  # a price list over a slow network
        loaded.set()
        return {"deepseek-ai/DeepSeek-V4.1-Flash": pricing.Quote("nebius", "deepseek-ai/DeepSeek-V4.1-Flash", 0.30, 1.20, "test")}

    monkeypatch.setitem(pricing.LISTS, "nebius", slow_price_list)
    monkeypatch.setattr(pricing, "_overrides", lambda: {})
    span = {"attributes": {"tracing.span.kind": "llm", "tracing.llm.model_name": "deepseek-ai/DeepSeek-V4.1-Flash",
                           "tracing.llm.token_count.prompt": 1000, "tracing.llm.token_count.completion": 500}}
    started = time.perf_counter()
    first = telemetry.mask(span)
    assert time.perf_counter() - started < 0.2 and "tracing.llm.cost_usd" not in first["attributes"]  # did not wait
    assert loaded.wait(5) and loader_thread["name"] == "price-refresh"  # loaded in the background
    time.sleep(0.05)
    again = {"attributes": dict(span["attributes"])}
    assert abs(telemetry.mask(again)["attributes"]["tracing.llm.cost_usd"] - 0.0009) < 1e-9  # the next span is priced


def test_tool_schemas_in_events_keep_fields_named_password():
    from rehearsal.db.events import _mask

    tools = [{"type": "function", "function": {"name": "create_user", "parameters": {"type": "object", "properties": {"password": {"type": "string"}}}}}]
    out = _mask({"tools": tools, "new": [{"role": "user", "content": "token: abcdefghijklmnopqrstuvwx"}], "password": "hunter22"})
    assert out["tools"][0]["function"]["parameters"]["properties"]["password"] == {"type": "string"}
    assert out["password"] == "[REDACTED]"  # real values are still masked


def test_external_agents_see_the_same_tool_results_as_hosted_agents():
    from rehearsal.db.events import _mask

    result = {"result": {"status": 201, "body": {"token": "AAAAfictional-runner-token", "password": "Fict!onal1"}}}
    assert _mask(result, "external.action.result") == result  # same as the hosted agent's view
    assert _mask(result, "compiler.tool")["result"]["body"]["token"] == "[REDACTED]"  # console events stay masked
    assert "sk-" not in str(_mask({"result": "key sk-proj-abcdefghijklmnopqrstuvwxyz123456"}, "external.action.result"))



def test_rate_limited_write_is_refused_and_not_carried_out():
    from types import SimpleNamespace

    from rehearsal.core.contracts import ServiceSpec, ToolSpec, WorldManifest
    from rehearsal.runner.gateway import Gateway

    sent = []
    manifest = WorldManifest(name="w", services=[ServiceSpec(name="app", image="x", port=80)],
                             tools=[ToolSpec(name="create_post", description="d", service="app", method="POST", path="/posts", mutating=True, roles=[])])
    gw = Gateway(SimpleNamespace(http=lambda *a, **k: sent.append(a)), manifest, {})
    gw.arm_fault("create_post", "rate_limit", 1)
    res = gw._dispatch(manifest.tool("create_post"), {"operation_id": "op1", "role": "staff", "path": "/posts", "json": {}, "query": {}})
    assert res.status == "FAILED" and res.visible["status"] == 429 and "not carried out" in res.visible["error"] and sent == []
