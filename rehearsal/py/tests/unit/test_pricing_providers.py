"""Prices for the vendor and host providers, derived from OpenRouter's listings (no network)."""

from rehearsal import pricing
from rehearsal.agents.llm import PROVIDERS
from rehearsal.config import settings
from rehearsal.pricing import Quote

LISTING = {
    "anthropic/claude-haiku-4.5": Quote("openrouter", "anthropic/claude-haiku-4.5", 1.0, 5.0, "openrouter price list"),
    "openai/gpt-oss-120b": Quote("openrouter", "openai/gpt-oss-120b", 0.1, 0.5, "openrouter price list"),
}
ROWS = {"openai/gpt-oss-120b": [{"host": "Groq", "input_per_m": 0.15, "output_per_m": 0.6}, {"host": "Cerebras", "input_per_m": 0.35, "output_per_m": 0.75}]}


def test_vendor_price_matches_dated_snapshot():
    q = pricing._derived("anthropic", "claude-haiku-4-5-20251001", LISTING, ROWS.get)
    assert (q.provider, q.input_per_m, q.output_per_m) == ("anthropic", 1.0, 5.0)


def test_vendor_price_never_borrows_another_vendors_model():
    assert pricing._derived("openai", "claude-haiku-4-5", LISTING, ROWS.get) is None


def test_host_price_is_that_hosts_row():
    q = pricing._derived("cerebras", "openai/gpt-oss-120b", LISTING, ROWS.get)
    assert (q.input_per_m, q.output_per_m) == (0.35, 0.75)
    assert pricing._derived("together", "openai/gpt-oss-120b", LISTING, ROWS.get) is None


def test_every_provider_has_a_price_source():
    assert all(pricing.price_source(name) for name in PROVIDERS)
    assert set(pricing.VENDORS) | set(pricing.HOSTS) <= set(PROVIDERS)


def test_empty_chain_setting_means_the_default(monkeypatch):
    monkeypatch.setenv("REHEARSAL_ENV_FILE", "/dev/null")
    for role in ("COMPILER", "AGENT", "PARTICIPANT", "IMPROVER", "REASONER"):
        monkeypatch.setenv(f"REHEARSAL_MODEL_{role}", "")
    settings.cache_clear()
    s = settings()
    settings.cache_clear()
    assert s.model_compiler.startswith("nebius:nvidia/nemotron-3-super") and "Nemotron-3-Ultra" in s.model_compiler
    assert s.model_participant.startswith("nebius:nvidia/NVIDIA-Nemotron-3-Nano") and s.model_participant.endswith("#nothink")
    assert s.model_reasoner.startswith("nebius:nvidia/Nemotron-3-Ultra") and s.model_improver == s.model_reasoner
