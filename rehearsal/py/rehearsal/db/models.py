"""Control-plane schema. Every project-owned row carries ``project_id`` and every
API lookup filters on it. World versions and approved scenarios are immutable."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True)}


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("org"))
    name: Mapped[str] = mapped_column(String(200))
    owner_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    owner_email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)  # set by self-serve sign-up
    plan_override: Mapped[str | None] = mapped_column(String(20), nullable=True)  # set by an operator admin; wins over billing
    limits_override: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")  # admin: custom plan limits
    billing: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")  # Dodo customer and subscription, as last synced
    created_device: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # browser that created it (free-plan abuse)
    created_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)


class PlanCredit(Base):
    """Builds or episodes added to one month of a workspace's plan: a paid top-up, or a grant by an operator admin."""

    __tablename__ = "plan_credits"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("crd"))
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # builds | episodes
    quantity: Mapped[int] = mapped_column(Integer)
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM (UTC)
    ref: Mapped[str] = mapped_column(String(120), unique=True)  # dodo:<payment_id> or admin:<id>: applying twice is impossible
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=now)


class BillingEvent(Base):
    """Received Dodo webhooks (deduplicated by webhook-id) and admin plan changes: the billing audit trail."""

    __tablename__ = "billing_events"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    type: Mapped[str] = mapped_column(String(80))
    org_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    actor: Mapped[str | None] = mapped_column(String(320), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("prj"))
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=now)


class User(Base):
    """A person who signs in to the console (Google, or email sign-up on self-hosted servers)."""

    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("usr"))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    picture_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(300), nullable=True)  # scrypt; None for Google-only accounts
    created_at: Mapped[datetime] = mapped_column(default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id"),)
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mem"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="owner")  # owner | admin | member
    created_at: Mapped[datetime] = mapped_column(default=now)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("key"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    prefix: Mapped[str] = mapped_column(String(40), unique=True)
    hash: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list[Any]] = mapped_column(JSONB, default=lambda: ["admin"])
    created_at: Mapped[datetime] = mapped_column(default=now)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class CliLogin(Base):
    """A terminal asking to sign in (`rehearsal login`). A signed-in owner approves it in the console; the terminal
    then collects a new API key with its device code. The key is created at that moment and never stored readable."""

    __tablename__ = "cli_logins"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cli"))
    user_code: Mapped[str] = mapped_column(String(16), unique=True)  # shown in the terminal and the browser
    device_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 of the terminal's secret device code
    client: Mapped[str] = mapped_column(String(200), default="")  # user@host of the terminal
    requested_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | approved | denied | claimed
    project_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    api_key_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    expires_at: Mapped[datetime] = mapped_column()


class Credential(Base):
    """A reference to a secret (environment variable name on the runner) or an
    encrypted value. Values are never returned by the API."""

    __tablename__ = "credentials"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cred"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))  # model_provider | application | training
    env_var: Mapped[str | None] = mapped_column(String(200), nullable=True)
    encrypted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    __table_args__ = (UniqueConstraint("project_id", "name"),)


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("app"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    connection_mode: Mapped[str] = mapped_column(String(40), default="source")
    source: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # kind git|local_path|upload
    images: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    policies: Mapped[str] = mapped_column(Text, default="")  # owner-approved policy text
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=now)
    removed_at: Mapped[datetime | None] = mapped_column(nullable=True)  # hidden from the console; its run history stays
    __table_args__ = (UniqueConstraint("project_id", "name"),)


class World(Base):
    __tablename__ = "worlds"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("wld"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=now)


class WorldVersion(Base):
    __tablename__ = "world_versions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("wv"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    world_id: Mapped[str] = mapped_column(ForeignKey("worlds.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|published|failed
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    private: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # secrets, seed vars: never exported
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    build_job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
    __table_args__ = (UniqueConstraint("world_id", "version"),)


class Scenario(Base):
    __tablename__ = "scenarios"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("scn"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    world_version_id: Mapped[str] = mapped_column(ForeignKey("world_versions.id"), index=True)
    slug: Mapped[str] = mapped_column(String(60))
    family: Mapped[str] = mapped_column(String(120))
    split: Mapped[str] = mapped_column(String(10))
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed|validated|approved|rejected
    validation: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    snapshot_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    __table_args__ = (UniqueConstraint("world_version_id", "slug"),)


class AgentProfileRow(Base):
    __tablename__ = "agent_profiles"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("prof"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    parent_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[str] = mapped_column(String(40), default="user")  # user|improver
    rationale: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=now)
    __table_args__ = (UniqueConstraint("project_id", "name", "version"),)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("run"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="evaluation")
    world_version_id: Mapped[str] = mapped_column(ForeignKey("world_versions.id"), index=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Episode(Base):
    __tablename__ = "episodes"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ep"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("scenarios.id"))
    profile_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|finished|error
    job_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)  # the evaluation shard that claimed it
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # resumable engine state
    instance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    oracle: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    reward: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    termination: Mapped[str | None] = mapped_column(String(60), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("act"))
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(60))
    tool: Mapped[str] = mapped_column(String(80))
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    operation_id: Mapped[str] = mapped_column(String(60), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    goal_version: Mapped[int] = mapped_column(Integer)
    observed_goal_version: Mapped[int] = mapped_column(Integer)
    mutating: Mapped[bool] = mapped_column(Boolean, default=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # private: full request
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # private: what the app returned
    visible_result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # what the agent saw
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    fault: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    __table_args__ = (UniqueConstraint("episode_id", "seq"),)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("msg"))
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    sender: Mapped[str] = mapped_column(String(60))
    recipient: Mapped[str] = mapped_column(String(60))
    channel: Mapped[str] = mapped_column(String(20))  # bus|customer|notification
    text: Mapped[str] = mapped_column(Text)
    goal_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Event(Base):
    """Append-only, ordered event log; the SSE feed and the UI read only this."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    stream: Mapped[str] = mapped_column(String(60))  # run_x | job_x
    sequence: Mapped[int] = mapped_column(Integer)
    episode_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    type: Mapped[str] = mapped_column(String(60))
    actor_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    goal_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    evidence_refs: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    visibility: Mapped[str] = mapped_column(String(20), default="project")
    created_at: Mapped[datetime] = mapped_column(default=now)
    __table_args__ = (UniqueConstraint("stream", "sequence"), Index("events_stream_id", "stream", "id"))


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("job"))
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|paused|succeeded|failed|cancelled
    priority: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    lease_owner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pause_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    not_before: Mapped[datetime | None] = mapped_column(nullable=True)  # not claimed before this time (free plan: quiet hours)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tokens: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    __table_args__ = (Index("jobs_claim", "status", "priority", "created_at"),)


class ModelSpend(Base):
    """Usage booked when recorded, rather than in the month the job was created."""

    __tablename__ = "model_spend"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("spn"))
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    __table_args__ = (UniqueConstraint("job_id", "month"),)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("art"))
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # world_bundle|dataset|adapter|report|source_upload|log
    name: Mapped[str] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(BigInteger)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=now)


class TrainingJob(Base):
    __tablename__ = "training_jobs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("trn"))
    project_id: Mapped[str] = mapped_column(String(40), index=True)
    world_version_id: Mapped[str] = mapped_column(ForeignKey("world_versions.id"))
    base_model: Mapped[str] = mapped_column(String(200))
    method: Mapped[str] = mapped_column(String(40), default="expert_iteration")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    rounds: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
