"""Append-only event log with per-stream ordering.

Events are written in the same transaction as the state change they describe,
so the log and the domain tables cannot silently diverge (the table is the
outbox). A transaction-scoped advisory lock serialises sequence allocation per
stream across workers.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import telemetry
from .models import Event


def emit(
    s: Session,
    *,
    project_id: str,
    stream: str,
    type: str,
    summary: str = "",
    episode_id: str | None = None,
    actor_id: str | None = None,
    goal_version: int | None = None,
    data: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
    visibility: str = "project",
) -> Event:
    s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": stream})
    seq = (s.scalar(select(func.max(Event.sequence)).where(Event.stream == stream)) or 0) + 1
    ev = Event(
        project_id=project_id,
        stream=stream,
        sequence=seq,
        episode_id=episode_id,
        type=type,
        actor_id=actor_id,
        goal_version=goal_version,
        summary=telemetry.redact(summary)[:2000],
        # Command payloads are executable input: masking here changes tool semantics.
        # Their public representations are masked in serialize(), like all events.
        data=(data or {}) if type in {"external.action.submitted", "intervention.requested"} else _mask(data or {}, type),
        evidence_refs=evidence_refs or [],
        visibility=visibility,
    )
    s.add(ev)
    s.flush()
    return ev


AGENT_FACING = {"external.turn", "external.action.result"}  # what a bring-your-own agent receives


def _mask(data: dict[str, Any], type: str = "") -> dict[str, Any]:
    """Masks secrets in event data. Tool definitions are JSON schemas, not values: a parameter named "password" is a
    field description, and masking it by name turns the schema into an invalid one that model providers reject.
    What a bring-your-own agent receives is masked by value only (real credentials), not by key name: a hosted
    agent sees the sandbox's fictional "token" or "password" fields, so an external agent must see them too."""
    masked = telemetry._redact_any({k: v for k, v in (data or {}).items() if k != "tools"}, by_key=type not in AGENT_FACING)
    return {**masked, "tools": data["tools"]} if "tools" in (data or {}) else masked


def serialize(ev: Event) -> dict[str, Any]:
    return {
        "event_id": ev.id,
        "stream": ev.stream,
        "sequence": ev.sequence,
        "episode_id": ev.episode_id,
        "type": ev.type,
        "actor_id": ev.actor_id,
        "goal_version": ev.goal_version,
        "summary": ev.summary,
        "data": _mask(ev.data, ev.type),
        "evidence_refs": ev.evidence_refs,
        "visibility": ev.visibility,
        "created_at": ev.created_at.isoformat(),
    }
