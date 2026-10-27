"""Model price catalog built from several independent sources.

A call is charged at, in order of preference:

1. the cost the provider returned for that request (OpenRouter ``usage.cost``);
2. the serving provider's own published price list (Nebius, OpenRouter and
   LiteLLM proxies expose per-token prices on their model endpoints);
3. a price from ``pricing.yaml`` (or ``REHEARSAL_PRICES``); each entry names its
   source and date;
4. for vendors called on their own API (OpenAI, Anthropic, Google, Mistral, xAI,
   DeepSeek), the vendor's price as OpenRouter's catalogue lists it; for hosts of
   open models (Groq, Together, Fireworks, Cerebras), that host's own price from
   OpenRouter's listing of each model's hosts. Neither publishes a
   machine-readable price list of its own.

Separately, ``market()`` reports what *other* hosts charge for the same open
model (from OpenRouter's per-model endpoint listing). It is for planning and
comparison only; nothing is billed at a market price. When no source knows a
price, cost is reported as unknown rather than invented; tokens are always kept.
"""

from __future__ import annotations

import json
import math
import logging
import os
import re
import statistics
import threading
import time
from dataclasses import asdict, dataclass
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import httpx
import yaml

log = logging.getLogger(__name__)
TTL_S = 6 * 3600
_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}
require_known_prices: ContextVar[bool] = ContextVar("require_known_prices", default=False)


@dataclass
class Quote:
    provider: str
    model: str
    input_per_m: float
    output_per_m: float
    source: str  # human-readable origin, e.g. "nebius price list"
    url: str = ""
    as_of: str = ""

    def __post_init__(self) -> None:
        if any(not math.isfinite(v) or v < 0 for v in (self.input_per_m, self.output_per_m)):
            raise ValueError("model prices must be finite and non-negative")

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * self.input_per_m + completion_tokens * self.output_per_m) / 1e6


def _norm(model: str) -> str:
    """deepseek-ai/DeepSeek-V4.1-Flash and deepseek/deepseek-v4.1-flash -> deepseekv41flash."""
    return re.sub(r"[^a-z0-9]", "", model.split("/")[-1].lower().split(":")[0])


def _cached(key: str, loader: Any) -> Any:
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < TTL_S:
            return hit[1]
    try:
        value = loader()
    except Exception as exc:  # noqa: BLE001 - a missing source must not break model calls
        log.info("price source %s unavailable: %s", key, exc)
        value = hit[1] if hit else None  # retain the last published price during an outage
        with _lock:
            _cache[key] = (time.time() - TTL_S + 30, value)  # retry failed sources soon
        return value
    with _lock:
        _cache[key] = (time.time() if value else time.time() - TTL_S + 30, value)
    return value


def _today() -> str:
    return time.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- sources


def _nebius_list() -> dict[str, Quote]:
    key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        return {}
    url = "https://api.tokenfactory.nebius.com/v1/models?verbose=true"
    data = httpx.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=20).json()
    out = {}
    for m in data.get("data", []):
        p = m.get("pricing") or {}
        if p.get("prompt") is not None and p.get("completion") is not None:
            out[m["id"]] = Quote("nebius", m["id"], float(p["prompt"]) * 1e6, float(p["completion"]) * 1e6, "nebius price list", url, _today())
    return out


def _openrouter_list() -> dict[str, Quote]:
    url = "https://openrouter.ai/api/v1/models"
    data = httpx.get(url, timeout=20).json()
    out = {}
    for m in data.get("data", []):
        p = m.get("pricing") or {}
        try:
            out[m["id"]] = Quote("openrouter", m["id"], float(p["prompt"]) * 1e6, float(p["completion"]) * 1e6, "openrouter price list", url, _today())
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _litellm_list() -> dict[str, Quote]:
    """A LiteLLM proxy publishes the per-token price it charges each key (GET /model/info)."""
    key = os.environ.get("LITELLM_API_KEY")
    if not key:
        return {}
    url = os.environ.get("LITELLM_BASE_URL", "https://litellm.vision.aivar.app/v1").removesuffix("/").removesuffix("/v1") + "/model/info"
    out = {}
    for m in httpx.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=20).json().get("data", []):
        info = m.get("model_info") or {}
        if info.get("input_cost_per_token") is not None and info.get("output_cost_per_token") is not None:
            out[m["model_name"]] = Quote("litellm", m["model_name"], float(info["input_cost_per_token"]) * 1e6, float(info["output_cost_per_token"]) * 1e6,
                                         "litellm proxy price list", url, _today())
    return out


def _overrides() -> dict[str, Quote]:
    """pricing.yaml: {"provider:model": {input_per_m, output_per_m, source, url, as_of}}."""
    out: dict[str, Quote] = {}
    path = Path(os.environ.get("REHEARSAL_PRICING_FILE", "pricing.yaml"))
    entries: dict[str, Any] = {}
    if path.is_file():
        entries.update(yaml.safe_load(path.read_text()) or {})
    try:
        for k, v in json.loads(os.environ.get("REHEARSAL_PRICES", "{}")).items():
            entries[k] = {"input_per_m": v[0], "output_per_m": v[1], "source": "REHEARSAL_PRICES"} if isinstance(v, list) else v
    except json.JSONDecodeError:
        pass
    for key, v in entries.items():
        provider, _, model = key.partition(":")
        out[key] = Quote(provider, model, float(v["input_per_m"]), float(v["output_per_m"]), v.get("source", "pricing override"), v.get("url", ""), str(v.get("as_of", "")))
    return out


LISTS = {"nebius": _nebius_list, "openrouter": _openrouter_list, "litellm": _litellm_list}
# Vendors called on their own API, and their prefix in OpenRouter model ids (which lists them at the vendor's price).
VENDORS = {"openai": "openai", "anthropic": "anthropic", "google": "google", "mistral": "mistralai", "xai": "x-ai", "deepseek": "deepseek"}
# Hosts of open models, and their name in OpenRouter's listing of a model's hosts (which shows each host's price).
HOSTS = {"groq": "Groq", "together": "Together", "fireworks": "Fireworks", "cerebras": "Cerebras"}


def price_source(provider: str) -> str:
    """Where this provider's prices come from, in words (the configuration reference prints it)."""
    if provider in LISTS:
        return "its own price list"
    if provider in VENDORS:
        return "the vendor's price, as OpenRouter lists it"
    if provider in HOSTS:
        return "this host's price, from OpenRouter's host listing"
    return "`pricing.yaml` or `REHEARSAL_PRICES`"


def _openrouter_match(model: str, vendor: str | None = None, listing: dict[str, Quote] | None = None) -> str | None:
    """A model's OpenRouter id: claude-haiku-4-5, or a dated snapshot of it, is anthropic/claude-haiku-4.5."""
    if listing is None:
        listing = _cached("openrouter", _openrouter_list) or {}
    target = _norm(re.sub(r"-\d{8}$", "", model))
    return next((mid for mid in listing if (vendor is None or mid.split("/")[0] == vendor) and _norm(mid) == target), None)


def _endpoint_rows(match: str) -> list[dict[str, Any]]:
    """What each host on OpenRouter charges for one model."""

    def load() -> list[dict[str, Any]]:
        data = httpx.get(f"https://openrouter.ai/api/v1/models/{match}/endpoints", timeout=20).json().get("data", {})
        rows = []
        for e in data.get("endpoints", []):
            p = e.get("pricing") or {}
            try:
                rows.append({"host": e.get("provider_name"), "input_per_m": float(p["prompt"]) * 1e6, "output_per_m": float(p["completion"]) * 1e6})
            except (KeyError, TypeError, ValueError):
                continue
        return rows

    return _cached(f"endpoints:{match}", load) or []


def _derived(provider: str, model: str, listing: dict[str, Quote], rows_for: Any) -> Quote | None:
    """The price of a vendor's or a host's model from OpenRouter's listings (see the module docstring, item 4)."""
    if provider in VENDORS:
        match = _openrouter_match(model, VENDORS[provider], listing)
        q = listing.get(match) if match else None
        return Quote(provider, model, q.input_per_m, q.output_per_m, f"{provider} price, as listed by openrouter", f"https://openrouter.ai/{match}", q.as_of) if q else None
    if provider in HOSTS:
        match = _openrouter_match(model, None, listing)
        host = HOSTS[provider].lower()
        row = next((r for r in (rows_for(match) if match else []) if (r.get("host") or "").lower().startswith(host)), None)
        if row:
            return Quote(provider, model, row["input_per_m"], row["output_per_m"], f"{HOSTS[provider]} price, from openrouter's host listing", f"https://openrouter.ai/{match}", _today())
    return None


# --------------------------------------------------------------------------- lookups


def billing_quote(provider: str, model: str) -> Quote | None:
    """The price the serving provider charges for this model, or None."""
    if provider in LISTS:
        quote = (_cached(provider, LISTS[provider]) or {}).get(model)
        if quote is not None:
            return quote
    override = (_cached("overrides", _overrides) or {}).get(f"{provider}:{model}")
    if override is not None or (provider not in VENDORS and provider not in HOSTS):
        return override
    return _derived(provider, model, _cached("openrouter", _openrouter_list) or {}, _endpoint_rows)


def market(model: str) -> dict[str, Any] | None:
    """What hosts on OpenRouter charge for the same model (planning reference only)."""
    match = _openrouter_match(model)
    if match is None:
        return None
    rows = _endpoint_rows(match)
    if not rows:
        return None
    blended = sorted(r["input_per_m"] * 0.75 + r["output_per_m"] * 0.25 for r in rows)  # assumes 3:1 input:output tokens
    return {
        "model": match,
        "hosts": len(rows),
        "input_per_m": {"min": min(r["input_per_m"] for r in rows), "median": statistics.median(r["input_per_m"] for r in rows), "max": max(r["input_per_m"] for r in rows)},
        "output_per_m": {"min": min(r["output_per_m"] for r in rows), "median": statistics.median(r["output_per_m"] for r in rows), "max": max(r["output_per_m"] for r in rows)},
        "blended_per_m": {"min": blended[0], "median": statistics.median(blended), "max": blended[-1]},
        "source": "openrouter endpoints listing",
        "as_of": _today(),
    }


def report(chains: dict[str, str]) -> list[dict[str, Any]]:
    """Billing quote and market range for every model in the configured chains."""
    rows = []
    for purpose, chain in chains.items():
        for entry in [e.strip() for e in chain.split(",") if e.strip()]:
            provider, _, model = entry.partition(":")
            q = billing_quote(provider, model)
            rows.append({"purpose": purpose, "provider": provider, "model": model, "billing": asdict(q) if q else None, "market": market(model)})
    return rows
