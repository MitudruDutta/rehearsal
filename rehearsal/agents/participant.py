"""Simulated customer. Its goal and facts come from the versioned scenario; a
model only phrases replies. Free-form prose cannot change ground truth: goal
changes happen only through scheduled scenario events."""

from __future__ import annotations

from typing import Callable

from ..config import settings
from ..core.contracts import ParticipantSpec
from .llm import LLMError, chat

FALLBACK = "Thanks. Please go ahead with what I asked."
SILENT = "NONE"


def reply(spec: ParticipantSpec, goal_instruction: str, history: list[tuple[str, str]], *, mode: str = "llm", check: Callable[[], None] | None = None) -> tuple[str, float, int]:
    """Returns (text, cost_usd, tokens). ``history`` is [(speaker, text)]. Empty text means the customer stays silent."""
    if mode != "llm":
        return FALLBACK, 0.0, 0
    facts = "\n".join(f"- {f}" for f in spec.facts) or "- (none beyond your request)"
    transcript = "\n".join(f"{who}: {text}" for who, text in history[-12:])
    system = (
        f"You are {spec.name}, a customer talking to a company's staff. {spec.persona}\n"
        f"Facts you know:\n{facts}\n"
        f"What you want right now: {goal_instruction}\n"
        "Rules: reply in at most three short sentences. Answer questions only from the facts above; "
        "if you do not know something, say so. Do not introduce new requests or change what you want. "
        "Do not mention being simulated. If the last staff message needs no answer from you (an acknowledgement, a thank-you, "
        f"a promise to follow up), reply with exactly {SILENT} and nothing else: real customers do not answer every message."
    )
    try:
        r = chat(
            settings().model_participant,
            [{"role": "system", "content": system}, {"role": "user", "content": f"Conversation so far:\n{transcript}\n\nWrite your next reply."}],
            check=check,
            temperature=0.4,
            max_tokens=400,
        )
    except LLMError:
        return FALLBACK, 0.0, 0
    text = r.content.strip() or FALLBACK
    if text.strip(" .\"'").upper() == SILENT:
        text = ""  # nothing to say; the caller posts nothing
    return text[:1200], r.cost_usd, r.prompt_tokens + r.completion_tokens
