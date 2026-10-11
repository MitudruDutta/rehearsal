"""One OpenAI-compatible chat client with a provider fallback chain.

A chain is ``provider:model[,provider:model...]``. Rate limits, credit errors,
server errors, and timeouts move to the next entry; the reply records which
provider/model actually answered so traces and evaluations stay attributable.
Provider keys are read server-side only.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx
import openai

from .. import pricing, telemetry

log = logging.getLogger(__name__)

PROVIDERS: dict[str, tuple[str, str]] = {
    "nebius": ("https://api.tokenfactory.nebius.com/v1", "NEBIUS_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GOOGLE_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "anthropic": ("https://api.anthropic.com/v1/", "ANTHROPIC_API_KEY"),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "together": ("https://api.together.xyz/v1", "TOGETHER_API_KEY"),
    "fireworks": ("https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY"),
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),  # NVIDIA's hosted models (build.nvidia.com)
    "litellm": ("https://litellm.vision.aivar.app/v1", "LITELLM_API_KEY"),  # a LiteLLM proxy (Claude, Amazon Nova); LITELLM_BASE_URL overrides
    "modal": ("", "MODAL_PROXY_TOKEN_ID"),  # base from MODAL_BASE_URL; key is "<token id>.<token secret>"
    "local": ("", "REHEARSAL_LOCAL_API_KEY"),  # base from REHEARSAL_LOCAL_BASE_URL (vLLM etc.)
    "custom": ("", "REHEARSAL_CUSTOM_API_KEY"),  # base from REHEARSAL_CUSTOM_BASE_URL
}


class LLMError(Exception):
    def __init__(self, *args: Any, reply: LLMReply | None = None):
        super().__init__(*args)
        self.reply = reply  # Completed response retained for caller usage accounting.


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str
    error: str | None = None  # JSON decoding problem the agent loop reports back


@dataclass
class LLMReply:
    content: str
    tool_calls: list[ToolCall]
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    attempts: list[str] = field(default_factory=list)
    raw_tool_calls: list[dict[str, Any]] = field(default_factory=list)  # provider metadata (e.g. thought signatures)
    cost_source: str = "unknown"  # where the price came from: provider-reported, a price list, or an override

    def assistant_message(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            raw = {r.get("id"): r for r in self.raw_tool_calls}
            msg["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.raw_arguments or "{}"},
                    **({"extra_content": raw[c.id]["extra_content"]} if raw.get(c.id, {}).get("extra_content") else {}),
                }
                for c in self.tool_calls
            ]
        return msg


def parse_chain(chain: str) -> list[tuple[str, str]]:
    entries = []
    for part in chain.split(","):
        part = part.strip()
        if not part:
            continue
        provider, sep, model = part.partition(":")
        if not sep or provider not in PROVIDERS:
            raise LLMError(f"bad model entry {part!r}; expected provider:model with provider in {sorted(PROVIDERS)}")
        entries.append((provider, model))
    if not entries:
        raise LLMError("empty model chain")
    return entries


_clients: dict[str, Any] = {}


def _client(provider: str) -> Any:
    if provider not in _clients:
        base, key_env = PROVIDERS[provider]
        if provider in ("local", "custom"):
            base = os.environ.get(f"REHEARSAL_{provider.upper()}_BASE_URL", "http://127.0.0.1:8001/v1" if provider == "local" else "")
        key = os.environ.get(key_env) or ("local" if provider == "local" else "")
        if provider == "litellm":
            base = os.environ.get("LITELLM_BASE_URL", base)
        if provider == "modal":
            base = os.environ.get("MODAL_BASE_URL", "")
            secret = os.environ.get("MODAL_PROXY_TOKEN_SECRET", "")
            key = f"{key}.{secret}" if key and secret else ""
        if not key or not base:
            raise LLMError(f"{provider} is not configured ({key_env} / base URL missing)")
        # A short connect timeout makes a dead route (for example a broken IPv6 or NAT64 path) fail fast, so the next
        # address of the host (IPv4) is tried, instead of the call hanging for minutes before the fallback chain moves on.
        timeout = httpx.Timeout(180.0, connect=10.0)
        _clients[provider] = telemetry.wrap(openai.OpenAI(base_url=base, api_key=key, timeout=timeout, max_retries=0))
    return _clients[provider]


def _loads(raw: str) -> tuple[dict[str, Any], str | None]:
    if not raw or not raw.strip():
        return {}, None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        # Common model slip: trailing text after a JSON object.
        m = re.match(r"\s*(\{.*\})", raw, re.S)
        if m:
            try:
                value = json.loads(m.group(1))
            except json.JSONDecodeError as exc:
                return {}, f"arguments are not valid JSON: {exc.msg}"
        else:
            return {}, "arguments are not valid JSON"
    if not isinstance(value, dict):
        return {}, "arguments must be a JSON object"
    return value, None


def _for_provider(messages: list[dict[str, Any]], provider: str) -> list[dict[str, Any]]:
    """Adapts replayed assistant tool calls to the provider receiving them.

    Gemini 3 requires the thought signature it issued with each function call;
    calls that came from another provider get Google's documented bypass value.
    Other providers reject the unknown field, so it is removed for them."""
    out = []
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            calls = []
            for c in m["tool_calls"]:
                c = dict(c)
                if provider == "google":
                    sig = (c.get("extra_content") or {}).get("google", {}).get("thought_signature")
                    if not sig:
                        c["extra_content"] = {"google": {"thought_signature": "skip_thought_signature_validator"}}
                else:
                    c.pop("extra_content", None)
                calls.append(c)
            m = {**m, "tool_calls": calls}
        out.append(m)
    return out


BILLING_COOLDOWN_S = 600
_billing_blocked: dict[str, float] = {}  # provider -> time until which it is skipped after a billing refusal


def _is_billing(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(k in text for k in ("payment method", "spend limit", "insufficient credit", "credits cannot", "billing", "quota exceeded for", "insufficient_quota"))


def _body_retry_delay(exc: Exception) -> float | None:
    """Google puts the retry window in the error body (RetryInfo.retryDelay = "23s")."""
    m = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", str(exc))
    return float(m.group(1)) if m else None


def _retry_after(exc: Exception) -> float | None:
    resp = getattr(exc, "response", None)
    if resp is not None:
        value = resp.headers.get("retry-after")
        try:
            return float(value) if value else None
        except ValueError:
            return None
    return None


def _sleep(seconds: float, check: Callable[[], None] | None) -> None:
    if check is None:
        time.sleep(seconds)
        return
    deadline = time.monotonic() + seconds
    while True:
        check()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(1.0, remaining))


def chat(
    chain: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    response_json: bool = False,
    check: Callable[[], None] | None = None,
) -> LLMReply:
    attempts: list[str] = []
    entries = parse_chain(chain)
    for round_ in range(6):
        reply, limited, waits = _try_chain(entries, messages, tools, tool_choice, temperature, max_tokens, response_json, attempts, check=check)
        if reply is not None:
            reply.attempts = attempts
            return reply
        if not limited:
            break
        # Every provider was rate limited: wait for the advertised window, then retry the chain.
        pause = min(90.0, max([w for w in waits if w] or [15.0 * (round_ + 1)]))
        log.info("all providers rate limited; waiting %.0fs (round %d)", pause, round_ + 1)
        _sleep(pause, check)
    raise LLMError("all models in chain failed: " + " | ".join(attempts[-8:]))


def _try_chain(
    entries: list[tuple[str, str]],
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    tool_choice: str | None,
    temperature: float,
    max_tokens: int,
    response_json: bool,
    attempts: list[str],
    check: Callable[[], None] | None = None,
) -> tuple[LLMReply | None, bool, list[float | None]]:
    """One pass over the chain: (reply, every failure was a rate limit/timeout, retry hints)."""
    only_limits = True
    waits: list[float | None] = []
    for provider, model in entries:
        if _billing_blocked.get(provider, 0) > time.time():
            only_limits = False
            continue
        quote = pricing.billing_quote(provider, model) if pricing.require_known_prices.get() else None
        if pricing.require_known_prices.get() and quote is None:
            only_limits = False
            attempts.append(f"{provider}:{model} has no usable price; configure REHEARSAL_PRICING_FILE before spending against a budget")
            continue
        for attempt in range(2):
            if check is not None:
                check()
            try:
                client = _client(provider)
            except LLMError as exc:
                attempts.append(f"{provider}:{model} unavailable: {exc}")
                only_limits = False
                break
            kwargs: dict[str, Any] = {"model": model, "messages": _for_provider(messages, provider), "temperature": temperature, "max_tokens": max_tokens}
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice or "auto"
            if response_json and not tools:
                kwargs["response_format"] = {"type": "json_object"}
            if provider == "openrouter":
                kwargs["extra_body"] = {"usage": {"include": True}}
            try:
                resp = client.chat.completions.create(**kwargs)
            except (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError) as exc:
                if _is_billing(exc):  # a 429 about money is not a rate limit: waiting will not help
                    only_limits = False
                    attempts.append(f"{provider}:{model} billing: {str(exc)[:200]}")
                    _billing_blocked[provider] = time.time() + BILLING_COOLDOWN_S
                    log.warning("%s refused for billing; skipping it for %ds", provider, BILLING_COOLDOWN_S)
                    break
                wait = _retry_after(exc) or _body_retry_delay(exc)
                waits.append(wait)
                attempts.append(f"{provider}:{model} {exc.__class__.__name__}")
                if attempt == 0 and (wait is None or wait <= 10):
                    _sleep(wait if wait is not None else 3, check)
                    continue
                break
            except openai.APIStatusError as exc:  # 400/401/402/403/404: try the next provider
                only_limits = False
                attempts.append(f"{provider}:{model} HTTP {exc.status_code}: {str(exc)[:300]}")
                break
            if not resp.choices:
                only_limits = False
                attempts.append(f"{provider}:{model} returned no choices")
                break
            choice = resp.choices[0].message
            calls = []
            for tc in choice.tool_calls or []:
                args, err = _loads(tc.function.arguments or "")
                calls.append(ToolCall(tc.id or f"call_{len(calls)}", tc.function.name, args, tc.function.arguments or "", err))
            usage = resp.usage
            reported_cost = getattr(usage, "cost", None) if usage else None
            try:
                cost = float(reported_cost) if reported_cost is not None else 0.0
                if not math.isfinite(cost) or cost < 0:
                    raise ValueError("invalid reported cost")
            except (TypeError, ValueError):
                reported_cost, cost = None, 0.0
            source = "provider-reported" if reported_cost is not None else "unknown"
            if reported_cost is None and usage:
                quote = quote or pricing.billing_quote(provider, model)
                if quote:
                    cost = quote.cost(usage.prompt_tokens or 0, usage.completion_tokens or 0)
                    source = f"{quote.source} ({quote.as_of})"
            reply = LLMReply(
                content=choice.content or "",
                tool_calls=calls,
                provider=provider,
                model=model,
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                cost_usd=cost,
                cost_source=source,
                raw_tool_calls=[tc.model_dump(exclude_none=True) for tc in choice.tool_calls or []],
            )
            return reply, False, waits
    return None, only_limits, waits


def chat_json(
    chain: str,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 8192,
    check: Callable[[], None] | None = None,
) -> tuple[Any, LLMReply]:
    """Tolerates fenced JSON; parse failures retain usage in ``LLMError.reply``."""
    reply = chat(chain, messages, temperature=temperature, max_tokens=max_tokens, response_json=True, check=check)
    text = reply.content.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise LLMError(f"model returned no JSON: {reply.content[:300]}", reply=reply)
    try:
        return json.JSONDecoder().raw_decode(text[start:])[0], reply
    except json.JSONDecodeError as exc:
        raise LLMError(f"model returned invalid JSON: {exc}", reply=reply) from exc
