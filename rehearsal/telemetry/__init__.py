"""neatlogs instrumentation.

Spans are created only when ``NEATLOGS_API_KEY`` is set; otherwise every helper
is a no-op so the platform runs identically without telemetry. Every exported
span passes through ``mask`` first: secrets and credentials never leave the
process. Rehearsal's own event store remains the source of truth; traces are
investigation evidence linked by run/episode/job identifiers.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import threading
from typing import Any, Iterator

from ..config import settings

log = logging.getLogger(__name__)
_lock = threading.Lock()
_enabled: bool | None = None

_SCHEME = re.compile(r"(?i)\b(bearer|token|basic)\s+[A-Za-z0-9._~+/=-]{12,}")
_TOKENS = [
    re.compile(r"\bv1\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\brh_[a-z0-9]+_[A-Za-z0-9_-]{20,}"),
]
_KV = re.compile(
    r"(?i)(\"?(?:password|passwd|secret|api_access_token|access_token|refresh_token|api_key|authorization|x-rehearsal-admin)\"?\s*[:=]\s*\"?)[^\"\s,}]+"
)


def redact(text: str) -> str:
    text = text.replace("\x00", "")  # PostgreSQL text and JSONB reject NUL (binary file content in tool output).
    for key, value in sorted(os.environ.items(), key=lambda item: len(item[1]), reverse=True):
        if len(value) >= 8 and key.upper().endswith(("API_KEY", "TOKEN", "SECRET", "PASSWORD")):
            text = text.replace(value, "[REDACTED]")
    text = _SCHEME.sub(lambda m: f"{m.group(1)} [REDACTED]", text)
    for pat in _TOKENS:
        text = pat.sub("[REDACTED]", text)
    return _KV.sub(lambda m: m.group(1) + "[REDACTED]", text)


def _redact_any(value: Any, *, by_key: bool = True) -> Any:
    """Masks secrets: values that look like real credentials always; with by_key, also whatever sits under a
    sensitive key name (password, token, ...)."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if by_key and isinstance(k, str) and (k.lower() in _SENSITIVE_KEYS or k.lower().endswith(("api_key", "access_token", "password", "secret"))) else _redact_any(v, by_key=by_key)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_redact_any(v, by_key=by_key) for v in value)
    return value


_SENSITIVE_KEYS = {"password", "passwd", "authorization", "api_key", "api_access_token", "access_token", "refresh_token", "secret", "x-rehearsal-admin", "admin_token", "secrets", "basic_auth", "token", "sha1"}


def mask(span: dict[str, Any]) -> dict[str, Any]:
    span = _redact_any(span)
    attrs = span.get("attributes")
    if isinstance(attrs, dict) and str(attrs.get("neatlogs.span.kind", "")).lower() == "llm" and "neatlogs.llm.cost_usd" not in attrs:
        usd = _llm_cost(attrs)
        if usd is not None:
            attrs["neatlogs.llm.cost_usd"] = usd  # neatlogs has no price for most open models, so it showed $0
    return span


def _llm_cost(attrs: dict[str, Any]) -> float | None:
    """Prices an LLM span from its model and token counts, with the price list Rehearsal bills from."""
    from .. import pricing
    from ..agents.llm import parse_chain

    model = attrs.get("neatlogs.llm.model_name")
    cfg = settings()
    providers = {m: p for chain in (cfg.model_compiler, cfg.model_agent, cfg.model_participant, cfg.model_improver) if chain for p, m in parse_chain(chain)}
    if not model or model not in providers:
        return None
    try:
        # memory only: neatlogs drops a span whose mask misses its deadline, so this must never wait on the network
        quote = pricing.cached_quote(providers[model], model)
    except Exception:  # noqa: BLE001 - a missing price must never drop a span
        return None
    if quote is None:
        return None
    return round(quote.cost(int(attrs.get("neatlogs.llm.token_count.prompt") or 0), int(attrs.get("neatlogs.llm.token_count.completion") or 0)), 8)


def _warm_prices() -> None:
    """Loads the price lists of the configured providers in the background, so the first model call is priced."""
    from .. import pricing
    from ..agents.llm import parse_chain

    cfg = settings()
    chains = (cfg.model_compiler, cfg.model_agent, cfg.model_participant, cfg.model_improver)
    pricing.warm({p for chain in chains if chain for p, _ in parse_chain(chain)})


def enabled() -> bool:
    global _enabled
    with _lock:
        if _enabled is None:
            key = settings().neatlogs_api_key
            _enabled = False
            if key:
                try:
                    import neatlogs

                    neatlogs.init(api_key=key, endpoint="https://ingest.neatlogs.com", workflow_name="agent-task", mask=mask, tags=["rehearsal"],
                                  # The worker finishes its current job after SIGTERM and then calls shutdown() itself. The SDK's own
                                  # handler would close the exporter mid-job, and later model calls would land as orphan sessions.
                                  register_shutdown_handlers=False)
                    _enabled = True
                    _warm_prices()
                except Exception as exc:  # noqa: BLE001 - telemetry must never break execution
                    log.warning("neatlogs disabled: %s", exc)
        return _enabled


def wrap(client: Any) -> Any:
    if not enabled():
        return client
    import neatlogs

    try:
        return neatlogs.wrap(client)
    except Exception as exc:  # noqa: BLE001
        log.warning("neatlogs wrap failed: %s", exc)
        return client


@contextlib.contextmanager
def span(name: str, kind: str = "CHAIN", *, session_id: str | None = None, **attributes: Any) -> Iterator[Any]:
    """Opens a neatlogs span (WORKFLOW, AGENT, TOOL, GUARDRAIL, CHAIN, ...)."""
    if not enabled():
        yield None
        return
    import neatlogs

    attrs = {f"rehearsal.{k}": (v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in attributes.items() if v is not None}
    with neatlogs.trace(name, kind=kind, session_id=session_id, **attrs) as s:
        if kind == "WORKFLOW":
            s.set_attribute("neatlogs.workflow_name", name)
        yield s


def set_attr(span_obj: Any, key: str, value: Any) -> None:
    if span_obj is None:
        return
    try:
        span_obj.set_attribute(f"rehearsal.{key}", value if isinstance(value, (str, int, float, bool)) else redact(str(value))[:4000])
    except Exception:  # noqa: BLE001
        pass


def flush() -> None:
    if enabled():
        import neatlogs

        neatlogs.flush()


def shutdown() -> None:
    """Drain spans once when the worker exits, including --once and errors."""
    global _enabled
    with _lock:
        if _enabled:
            import neatlogs

            try:
                neatlogs.flush()
            finally:
                neatlogs.shutdown()
                _enabled = None
