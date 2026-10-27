"""Authorization, build confinement, redaction, and packaged resource regressions.

No application server, database, Docker, or network is needed.
"""

import json
from importlib.resources import files
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import yaml
from fastapi import HTTPException, Request

from rehearsal import pricing
from rehearsal.redaction import redact, redact_any
from rehearsal.agents import llm
from rehearsal.api import auth
from rehearsal.core.contracts import BuildSpec, ServiceSpec
from rehearsal.runner import runtime
from rehearsal.sdk.examples import _catalog


PRIVATE_PATHS = [
    "/v1/world-versions/world/scenarios",
    "/v1/scenarios/scenario",
    "/v1/episodes/episode",
    "/v1/runs/run/episodes",
    "/v1/jobs/job/events",
    "/v1/runs/run/events",
    "/v1/streams/run/events/page",
    "/v1/artifacts",
    "/v1/artifacts/artifact/download",
]


def request(method, path):
    return Request({"type": "http", "method": method, "path": path, "headers": []})


@pytest.mark.parametrize("path", ["/v1/api-keys", "/v1/api-keys/", "/v1/credentials"])
@pytest.mark.parametrize("scopes", [["read"], ["write"], ["evaluator"]])
def test_non_admin_cannot_mint_keys_or_register_credentials(path, scopes):
    principal = auth.Principal("project", "key", scopes)
    with pytest.raises(HTTPException) as error:
        auth.authorize(request("POST", path), principal)
    assert error.value.status_code == 403


def test_admin_can_mint_keys():
    principal = auth.Principal("project", "key", ["admin"])
    assert auth.authorize(request("POST", "/v1/api-keys"), principal) is principal


@pytest.mark.parametrize("scopes", [[], ["unknown"], ["admin", "unknown"]])
def test_create_key_rejects_empty_or_invalid_scopes_before_persistence(scopes):
    session = Mock()
    with pytest.raises(HTTPException) as error:
        auth.create_key(session, "project", "test key", scopes)
    assert error.value.status_code == 422
    session.add.assert_not_called()
    session.flush.assert_not_called()


@pytest.mark.parametrize("scopes, expected", [(None, ["admin"]), (["read"], ["read"])])
def test_create_key_preserves_default_and_explicit_scopes(scopes, expected):
    session = Mock()
    auth.create_key(session, "project", "test key", scopes)
    key = session.add.call_args.args[0]
    assert key.scopes == expected
    session.flush.assert_called_once_with()


@pytest.mark.parametrize("path", PRIVATE_PATHS)
@pytest.mark.parametrize("scopes", [["read"], ["write"], ["agent"]])
def test_private_evaluator_reads_reject_other_scopes(path, scopes):
    principal = auth.Principal("project", "key", scopes)
    with pytest.raises(HTTPException) as error:
        auth.authorize(request("GET", path), principal)
    assert error.value.status_code == 403


@pytest.mark.parametrize("path", PRIVATE_PATHS)
@pytest.mark.parametrize("scopes", [["evaluator"], ["admin"]])
def test_private_evaluator_reads_allow_evaluator_or_admin(path, scopes):
    principal = auth.Principal("project", "key", scopes)
    assert auth.authorize(request("GET", path), principal) is principal


@pytest.mark.parametrize("scopes", [["evaluator"], ["write"]])
def test_private_evaluator_mutations_require_both_scopes(scopes):
    principal = auth.Principal("project", "key", scopes)
    with pytest.raises(HTTPException) as error:
        auth.authorize(request("POST", "/v1/scenarios/scenario/approve"), principal)
    assert error.value.status_code == 403


def test_private_evaluator_mutation_allows_evaluator_with_write():
    principal = auth.Principal("project", "key", ["evaluator", "write"])
    assert auth.authorize(request("POST", "/v1/scenarios/scenario/approve"), principal) is principal


@pytest.mark.parametrize("method, path", [
    ("GET", "/v1/episodes/episode/observation"),
    ("POST", "/v1/episodes/episode/actions"),
    ("GET", "/v1/episodes/episode/actions/action"),
])
def test_agent_observation_and_action_access_remains_allowed(method, path):
    principal = auth.Principal("project", "key", ["agent"])
    assert auth.authorize(request(method, path), principal) is principal


@pytest.fixture
def docker_run(monkeypatch):
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="built\n", stderr=""))
    monkeypatch.setattr(runtime, "_run", run)
    return run


def test_build_context_rejects_symlink_to_source_prefix_sibling(tmp_path, docker_run):
    source = tmp_path / "source"
    source.mkdir()
    sibling = tmp_path / "source-sibling"
    sibling.mkdir()
    (source / "linked").symlink_to(sibling, target_is_directory=True)
    service = ServiceSpec(name="app", build=BuildSpec(context="linked"))
    with pytest.raises(runtime.RuntimeError_, match="build context escapes"):
        runtime.build_service_image(service, source, "test")
    docker_run.assert_not_called()


@pytest.mark.parametrize("target_location", ["source", "source-sibling"])
@pytest.mark.parametrize("dockerfile", [None, "Dockerfile"])
def test_dockerfile_symlink_cannot_escape_build_context(tmp_path, docker_run, target_location, dockerfile):
    source = tmp_path / "source"
    context = source / "build"
    context.mkdir(parents=True)
    target = tmp_path / target_location / "outside.Dockerfile"
    target.parent.mkdir(exist_ok=True)
    target.write_text("FROM scratch\n")
    (context / "Dockerfile").symlink_to(target)
    service = ServiceSpec(name="app", build=BuildSpec(context="build", dockerfile=dockerfile))
    with pytest.raises(runtime.RuntimeError_, match="Dockerfile escapes"):
        runtime.build_service_image(service, source, "test")
    docker_run.assert_not_called()


@pytest.mark.parametrize("linked", [False, True])
@pytest.mark.parametrize("implicit", [False, True])
def test_build_accepts_dockerfile_confined_to_context(tmp_path, docker_run, linked, implicit):
    context = tmp_path / "source"
    context.mkdir()
    target = context / ("actual.Dockerfile" if linked else "Dockerfile")
    target.write_text("FROM scratch\n")
    dockerfile = target
    if linked:
        dockerfile = context / "Dockerfile"
        dockerfile.symlink_to(target)
    service = ServiceSpec(name="app", build=BuildSpec(dockerfile=None if implicit else dockerfile.name))
    assert runtime.build_service_image(service, context, "test") == ("rh-img-test-app", "built\n")
    docker_run.assert_called_once_with(
        ["docker", "build", "-t", "rh-img-test-app", "-f", str(target), str(context)],
        timeout=3600, check=False,
    )


@pytest.mark.parametrize("name", [
    "NEBIUS_API_KEY", "REHEARSAL_SESSION_SECRET", "KAGGLE_API_TOKEN", "DATABASE_PASSWORD",
])
def test_redacts_exact_configured_secret_in_free_text(monkeypatch, name):
    value = "synthetic.credential+with/punctuation=987654"
    monkeypatch.setenv(name, value)
    assert redact(f"upstream failure ({value})") == "upstream failure ([REDACTED])"


def test_redacts_overlapping_configured_secrets_longest_first(monkeypatch):
    monkeypatch.setenv("TEST_SHORT_TOKEN", "synthetic-overlap")
    monkeypatch.setenv("TEST_LONG_TOKEN", "synthetic-overlap-with-suffix")
    assert redact("synthetic-overlap-with-suffix synthetic-overlap") == "[REDACTED] [REDACTED]"


@pytest.mark.parametrize("token", [
    "v1." + "A" * 32 + "." + "B" * 32,
    "v1." + "aB_9-" * 8 + "." + "cD_0-" * 8,
])
def test_redacts_bare_nebius_shaped_token(token):
    assert redact(f"upstream failure ({token})") == "upstream failure ([REDACTED])"


def test_nested_values_redact_configured_and_sensitive_credentials(monkeypatch):
    value = "synthetic-nested-provider-credential"
    monkeypatch.setenv("NEBIUS_API_KEY", value)
    assert redact_any({"attributes": {
        "nebius_api_key": "unconfigured-sensitive-value",
        "session_secret": "another-unconfigured-sensitive-value",
        "messages": [f"upstream returned {value}", (value, "public message")],
    }}) == {"attributes": {
        "nebius_api_key": "[REDACTED]",
        "session_secret": "[REDACTED]",
        "messages": ["upstream returned [REDACTED]", ("[REDACTED]", "public message")],
    }}


def test_packaged_catalog_loads_outside_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    catalog = yaml.safe_load(files("rehearsal").joinpath("assets/catalog.yaml").read_text())
    applications = catalog["applications"]
    assert applications
    assert _catalog() == {entry["name"]: entry for entry in applications}


def test_packaged_compose_loads_outside_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    compose = yaml.safe_load(files("rehearsal").joinpath("assets/compose.yaml").read_text())
    postgres = compose["services"]["postgres"]
    assert postgres["image"].startswith("postgres:")
    assert postgres["healthcheck"]["test"]
    assert "rehearsal-pg" in compose["volumes"]


@pytest.fixture
def offline_pricing(tmp_path, monkeypatch):
    monkeypatch.setattr(pricing, "_cache", {})
    monkeypatch.setenv("REHEARSAL_PRICING_FILE", str(tmp_path / "pricing.yaml"))
    monkeypatch.setenv("REHEARSAL_PRICES", "{}")
    get = Mock(side_effect=httpx.ConnectError("offline test fixture"))
    monkeypatch.setattr(pricing.httpx, "get", get)
    monkeypatch.setattr(llm, "_billing_blocked", {})
    monkeypatch.setattr(llm, "_client", Mock(side_effect=AssertionError("unexpected provider access")))
    return get


@pytest.fixture
def priced_reply(offline_pricing, monkeypatch):
    def reply(cost=None):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=[]))],
            usage=SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=500_000, cost=cost),
        )
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=Mock(return_value=response),
        )))
        monkeypatch.setattr(llm, "_client", lambda provider: client)
        return llm.chat("openrouter:fixture-model", [])
    return reply


@pytest.mark.parametrize("provider", ["nebius", "openrouter"])
def test_serving_provider_price_precedes_configured_override(offline_pricing, monkeypatch, provider):
    published = pricing.Quote(provider, "fixture-model", 2, 6, "provider price list")
    listing = Mock(return_value={"fixture-model": published})
    monkeypatch.setitem(pricing.LISTS, provider, listing)
    monkeypatch.setenv("REHEARSAL_PRICES", json.dumps({f"{provider}:fixture-model": [99, 99]}))
    assert pricing.billing_quote(provider, "fixture-model") is published
    listing.assert_called_once_with()
    offline_pricing.assert_not_called()


@pytest.mark.parametrize("missing", [False, True])
def test_missing_model_uses_configured_override(offline_pricing, monkeypatch, missing):
    listing = {} if missing else {
        "other-model": pricing.Quote("openrouter", "other-model", 99, 99, "provider price list"),
    }
    monkeypatch.setitem(pricing.LISTS, "openrouter", lambda: listing)
    monkeypatch.setenv("REHEARSAL_PRICES", '{"openrouter:fixture-model": [2, 6]}')
    quote = pricing.billing_quote("openrouter", "fixture-model")
    assert (quote.input_per_m, quote.output_per_m, quote.source) == (2, 6, "REHEARSAL_PRICES")
    offline_pricing.assert_not_called()


def test_environment_prices_precede_yaml(offline_pricing, monkeypatch, tmp_path):
    (tmp_path / "pricing.yaml").write_text(yaml.safe_dump({
        "groq:fixture-model": {"input_per_m": 99, "output_per_m": 99, "source": "file source"},
        "groq:file-only": {"input_per_m": 3, "output_per_m": 9, "source": "file source"},
    }))
    monkeypatch.setenv("REHEARSAL_PRICES", '{"groq:fixture-model": [2, 6]}')
    quote = pricing.billing_quote("groq", "fixture-model")
    assert (quote.input_per_m, quote.output_per_m, quote.source) == (2, 6, "REHEARSAL_PRICES")
    file_quote = pricing.billing_quote("groq", "file-only")
    assert (file_quote.input_per_m, file_quote.output_per_m, file_quote.source) == (3, 9, "file source")
    offline_pricing.assert_not_called()


@pytest.mark.parametrize("cost", [0.0, 0.375])
def test_provider_reported_cost_precedes_price_lookup(priced_reply, monkeypatch, cost):
    lookup = Mock(return_value=pricing.Quote("openrouter", "fixture-model", 2, 6, "provider price list"))
    monkeypatch.setattr(pricing, "billing_quote", lookup)
    reply = priced_reply(cost)
    assert reply.cost_usd == cost
    assert reply.cost_source == "provider-reported"
    lookup.assert_not_called()


def test_offline_price_source_falls_back_to_configured_price(offline_pricing, priced_reply, monkeypatch):
    monkeypatch.setenv("REHEARSAL_PRICES", '{"openrouter:fixture-model": [2, 6]}')
    reply = priced_reply()
    assert reply.cost_usd == pytest.approx(5.0)
    assert reply.cost_source.startswith("REHEARSAL_PRICES")
    assert (reply.prompt_tokens, reply.completion_tokens) == (1_000_000, 500_000)
    offline_pricing.assert_called_once()
    assert pricing.billing_quote("openrouter", "fixture-model").source == "REHEARSAL_PRICES"
    offline_pricing.assert_called_once()


def test_offline_unknown_price_keeps_tokens_without_market_billing(offline_pricing, priced_reply, monkeypatch):
    monkeypatch.setenv("REHEARSAL_PRICES", '{"nebius:fixture-model": [2, 6]}')
    market = Mock(return_value={"input_per_m": {"min": 2}, "output_per_m": {"min": 6}})
    monkeypatch.setattr(pricing, "market", market)
    reply = priced_reply()
    assert reply.cost_usd == 0.0
    assert reply.cost_source == "unknown"
    assert (reply.prompt_tokens, reply.completion_tokens) == (1_000_000, 500_000)
    assert pricing.billing_quote("openrouter", "fixture-model") is None
    offline_pricing.assert_called_once()
    market.assert_not_called()
