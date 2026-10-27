"""Secret masking for everything Rehearsal stores or shows: event summaries, recorded actions and messages, compiler
logs, tool results, and exports. Values that look like real credentials are always masked; whatever sits under a
sensitive key name (password, token, ...) is masked too unless a caller opts out."""

from __future__ import annotations

import os
import re
from typing import Any

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
SENSITIVE_KEYS = {"password", "passwd", "authorization", "api_key", "api_access_token", "access_token", "refresh_token", "secret",
                  "x-rehearsal-admin", "admin_token", "secrets", "basic_auth", "token", "sha1"}


def redact(text: str) -> str:
    text = text.replace("\x00", "")  # PostgreSQL text and JSONB reject NUL (binary file content in tool output).
    for key, value in sorted(os.environ.items(), key=lambda item: len(item[1]), reverse=True):
        if len(value) >= 8 and key.upper().endswith(("API_KEY", "TOKEN", "SECRET", "PASSWORD")):
            text = text.replace(value, "[REDACTED]")
    text = _SCHEME.sub(lambda m: f"{m.group(1)} [REDACTED]", text)
    for pat in _TOKENS:
        text = pat.sub("[REDACTED]", text)
    return _KV.sub(lambda m: m.group(1) + "[REDACTED]", text)


def redact_any(value: Any, *, by_key: bool = True) -> Any:
    """Masks secrets in any JSON-like value: credential-looking strings always; with by_key, also every value under a
    sensitive key name."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if by_key and isinstance(k, str) and (k.lower() in SENSITIVE_KEYS or k.lower().endswith(("api_key", "access_token", "password", "secret")))
                    else redact_any(v, by_key=by_key)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redact_any(v, by_key=by_key) for v in value)
    return value
