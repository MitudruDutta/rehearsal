"""Typed contracts shared by the compiler, runner, evaluator, API, and SDK.

A world is ``(runtime, state, actions, observations, reset, events, verifier,
provenance)``. ``WorldManifest`` covers runtime/state/actions/reset; a
``ScenarioSpec`` covers one job inside that world (events, checks, reference and
negative trajectories). Both are immutable once a world version is published.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SLUG = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
TEMPLATE = re.compile(r"\{\{\s*([a-z_]+)\.([A-Za-z0-9_]+)\s*\}\}")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _slug(value: str) -> str:
    if not SLUG.match(value):
        raise ValueError(f"{value!r} must match {SLUG.pattern}")
    return value


# --------------------------------------------------------------------------- runtime


class BuildSpec(Strict):
    context: str = "."  # relative to the application source root
    dockerfile: str | None = None  # relative to context
    dockerfile_inline: str | None = None  # generated overlay when the repo has none

    @field_validator("context", "dockerfile")
    @classmethod
    def _relative(cls, v: str | None) -> str | None:
        if v is not None and (v.startswith("/") or ".." in v.split("/")):
            raise ValueError("build paths must stay inside the source tree")
        return v


class HealthSpec(Strict):
    http_path: str | None = None  # GET must return < 500
    command: list[str] | None = None  # exec inside the container must exit 0
    timeout_s: int = Field(default=240, ge=5, le=1800)


class ServiceSpec(Strict):
    name: str
    build: BuildSpec | None = None
    image: str | None = None  # pin with @sha256 digest
    port: int | None = Field(default=None, ge=1, le=65535)
    command: list[str] | None = None
    entrypoint: list[str] | None = None
    user: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    health: HealthSpec = Field(default_factory=HealthSpec)
    data_paths: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    oneshot: bool = False  # runs to completion (e.g. migrations) before dependents start
    volumes_from: str | None = None  # mount another service's data volumes (shared state, e.g. migrations)

    @field_validator("name")
    @classmethod
    def _slug_name(cls, v: str) -> str:
        return _slug(v)

    @model_validator(mode="after")
    def _source(self) -> "ServiceSpec":
        if (self.build is None) == (self.image is None):
            raise ValueError("exactly one of build or image is required")
        for p in self.data_paths:
            if not p.startswith("/") or p == "/":
                raise ValueError("data_paths must be absolute container directories other than /")
        if self.oneshot and self.port:
            raise ValueError("oneshot services do not expose ports")
        if self.volumes_from and self.data_paths:
            raise ValueError("a service with volumes_from uses that service's data paths; leave data_paths empty")
        return self


class DependencySpec(Strict):
    kind: Literal["payments", "email", "shipping", "smtp", "webhook"]
    service: str
    env_var: str
    notes: str = ""


class StateProbe(Strict):
    """Privileged, read-only access to application state, used only by the oracle."""

    name: str = "app"
    kind: Literal["sqlite", "postgres", "mysql"]
    service: str
    path: str | None = None  # sqlite: absolute container path under a data path
    database: str | None = None  # postgres/mysql
    user: str | None = None
    password: str | None = None  # may be a {{secret.x}} template

    @model_validator(mode="after")
    def _fields(self) -> "StateProbe":
        if self.kind == "sqlite" and not self.path:
            raise ValueError("sqlite probe needs path")
        if self.kind in ("postgres", "mysql") and not (self.database and self.user):
            raise ValueError(f"{self.kind} probe needs database and user")
        return self


class SeedStep(Strict):
    kind: Literal["http", "exec"] = "http"
    service: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    path: str = "/"
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: Any | None = None
    command: list[str] | None = None
    user: str | None = None  # exec: container user
    basic_auth: list[str] | None = None  # [username, password] templates for HTTP Basic
    save: dict[str, str] = Field(default_factory=dict)  # var -> dotted JSON path; exec: last JSON line, or "$stdout" for the last line
    expect_status: list[int] = Field(default_factory=lambda: [200, 201, 204])
    note: str = ""


class CredentialSpec(Strict):
    header: str = "Authorization"
    template: str | None = None  # e.g. "Bearer {{vars.support_token}}"
    basic: list[str] | None = None  # [username, password] templates for HTTP Basic

    @model_validator(mode="after")
    def _one(self) -> "CredentialSpec":
        if (self.template is None) == (self.basic is None):
            raise ValueError("credential needs exactly one of template or basic")
        if self.basic is not None and len(self.basic) != 2:
            raise ValueError("basic credential needs [username, password]")
        return self


class RoleSpec(Strict):
    name: str
    description: str
    credential: CredentialSpec | None = None
    customer_channel: bool = False

    @field_validator("name")
    @classmethod
    def _slug_name(cls, v: str) -> str:
        return _slug(v)


JSON_TYPES = {"string", "number", "integer", "boolean", "object", "array", "null"}


# JSON-schema keywords kept in tool parameter schemas, each with the value shape providers accept
_SCHEMA_KEYS: dict[str, Any] = {
    "description": str, "format": str, "pattern": str, "title": str,
    "minimum": (int, float), "maximum": (int, float), "minLength": int, "maxLength": int, "minItems": int, "maxItems": int,
    "enum": list, "required": list, "default": object, "additionalProperties": bool,
}


def clean_schema(schema: Any) -> dict[str, Any]:
    """Keeps only well-formed JSON-schema keywords in a tool parameter schema. Worlds compiled before the
    API-spec resolver fix stored truncated values such as {"type": {"type": "object"}} or
    {"format": {"type": "object"}}, which model providers reject for the whole tool list."""
    if not isinstance(schema, dict):
        return {}
    out: dict[str, Any] = {}
    t = schema.get("type")
    if isinstance(t, str) and t in JSON_TYPES or isinstance(t, list) and t and all(x in JSON_TYPES for x in t):
        out["type"] = t
    for key, kind in _SCHEMA_KEYS.items():
        if key not in schema:
            continue
        v = schema[key]
        if kind is object or kind is bool and isinstance(v, bool) or kind is not bool and isinstance(v, kind) and not isinstance(v, bool):
            out[key] = v
    if isinstance(out.get("description"), str) and out["description"].startswith("{'type'"):
        out.pop("description")
    if "required" in out and not all(isinstance(x, str) for x in out["required"]):
        out.pop("required")
    if isinstance(schema.get("properties"), dict):
        out["properties"] = {k: clean_schema(v) for k, v in schema["properties"].items()}
    if "items" in schema:
        out["items"] = clean_schema(schema["items"])
    if out.get("type") == "array" and "items" not in out:
        out["items"] = {}
    return out


class ToolParam(Strict):
    name: str
    location: Literal["path", "query", "body", "variables"]
    schema_: dict[str, Any] = Field(default_factory=lambda: {"type": "string"}, alias="schema")
    required: bool = True
    description: str = ""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @field_validator("schema_", mode="before")
    @classmethod
    def _valid_schema(cls, v: Any) -> dict[str, Any]:
        return clean_schema(v)

    @field_validator("description", mode="before")
    @classmethod
    def _real_description(cls, v: Any) -> str:
        return "" if isinstance(v, str) and v.startswith("{'type'") else v


class ToolSpec(Strict):
    name: str
    description: str
    service: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    params: list[ToolParam] = Field(default_factory=list)
    mutating: bool
    idempotent: bool = False  # set only after validation proves Idempotency-Key replay is safe
    roles: list[str]
    graphql: str | None = None  # GraphQL document; params with location "variables" fill its variables

    @field_validator("name")
    @classmethod
    def _slug_name(cls, v: str) -> str:
        return _slug(v)

    @model_validator(mode="after")
    def _path_params(self) -> "ToolSpec":
        declared = {p.name for p in self.params if p.location == "path"}
        used = set(re.findall(r"\{([A-Za-z0-9_]+)\}", self.path))
        if declared != used:
            raise ValueError(f"tool {self.name}: path params {sorted(used)} != declared {sorted(declared)}")
        has_vars = any(p.location == "variables" for p in self.params)
        if self.graphql is None and has_vars:
            raise ValueError(f"tool {self.name}: variables params need a graphql document")
        if self.graphql is not None and (self.method != "POST" or any(p.location == "body" for p in self.params)):
            raise ValueError(f"tool {self.name}: graphql tools use POST and variables params, not body params")
        return self

    def json_schema(self) -> dict[str, Any]:
        props = {p.name: {**p.schema_, "description": p.description} for p in self.params}
        return {
            "type": "object",
            "properties": props,
            "required": [p.name for p in self.params if p.required],
            "additionalProperties": False,
        }


class CapabilityReport(Strict):
    resettable: bool = False
    deterministic_reset: bool = False
    idempotent_tools: list[str] = Field(default_factory=list)
    clock_control: bool = False
    tool_coverage: dict[str, int] = Field(default_factory=dict)  # mutating tool -> validated scenarios using it
    gaps: list[str] = Field(default_factory=list)


class WorldManifest(Strict):
    schema_version: Literal[1] = 1
    name: str
    description: str = ""
    services: list[ServiceSpec]
    dependencies: list[DependencySpec] = Field(default_factory=list)
    secrets: list[str] = Field(default_factory=list)
    state_probes: list[StateProbe] = Field(default_factory=list)
    seed: list[SeedStep] = Field(default_factory=list)
    roles: list[RoleSpec] = Field(default_factory=list)
    tools: list[ToolSpec] = Field(default_factory=list)
    capabilities: CapabilityReport = Field(default_factory=CapabilityReport)

    @model_validator(mode="after")
    def _references(self) -> "WorldManifest":
        services = {s.name for s in self.services}
        if len(services) != len(self.services):
            raise ValueError("duplicate service names")
        roles = {r.name for r in self.roles}
        names = [t.name for t in self.tools]
        if len(set(names)) != len(names):
            raise ValueError("duplicate tool names")
        for t in self.tools:
            if t.service not in services:
                raise ValueError(f"tool {t.name} references unknown service {t.service}")
            unknown = set(t.roles) - roles
            if unknown:
                raise ValueError(f"tool {t.name} references unknown roles {sorted(unknown)}")
        for svc in self.services:
            unknown = set(svc.depends_on) - services
            if unknown:
                raise ValueError(f"service {svc.name} depends on unknown {sorted(unknown)}")
            if svc.volumes_from and (svc.volumes_from not in services or svc.volumes_from == svc.name):
                raise ValueError(f"service {svc.name} volumes_from must name another service")
            target = next((x for x in self.services if x.name == svc.volumes_from), None)
            if target is not None and target.volumes_from:
                raise ValueError(f"service {svc.name}: volumes_from cannot chain through {target.name}")
        for step in self.seed:
            if step.service not in services:
                raise ValueError(f"seed step references unknown service {step.service}")
        probe_names = [p.name for p in self.state_probes]
        if len(set(probe_names)) != len(probe_names):
            raise ValueError("duplicate state probe names")
        for probe in self.state_probes:
            svc = next((s for s in self.services if s.name == probe.service), None)
            if svc is None:
                raise ValueError(f"state probe references unknown service {probe.service}")
            if probe.kind == "sqlite" and not any(probe.path.startswith(d.rstrip("/") + "/") for d in svc.data_paths):
                raise ValueError(f"state probe {probe.path} is not inside a declared data path of {svc.name}")
        for d in self.dependencies:
            if d.service not in services:
                raise ValueError(f"dependency references unknown service {d.service}")
        return self

    def tool(self, name: str) -> ToolSpec | None:
        return next((t for t in self.tools if t.name == name), None)

    def role(self, name: str) -> RoleSpec | None:
        return next((r for r in self.roles if r.name == name), None)


# --------------------------------------------------------------------------- scenarios

CompareOp = Literal["==", "!=", ">", ">=", "<", "<="]


class CheckSpec(Strict):
    """One read-only SQL check. ``source="app"`` runs against a state probe of the
    application (its own SQL dialect); ``source="effects"`` runs SQLite SQL over the
    emulated-dependency journal table ``effects``. The query must return one row
    with one column. Named parameters (``:order_id``) bind seed variables."""

    id: str
    description: str
    source: Literal["app", "effects"] = "app"
    probe: str | None = None  # state probe name; defaults to the first probe
    query: str
    op: CompareOp = "=="
    value: Any = 1

    @field_validator("id")
    @classmethod
    def _slug_id(cls, v: str) -> str:
        return _slug(v)


class GoalVersion(Strict):
    version: int = Field(ge=1)
    instruction: str  # what the participant wants, in their words
    checks: list[str]  # check ids that must all pass when this is the latest goal


class Trigger(Strict):
    kind: Literal["at_step", "after_tool", "after_customer_reply"]
    step: int | None = None
    tool: str | None = None
    actor: str | None = None
    occurrence: int = 1

    @model_validator(mode="after")
    def _fields(self) -> "Trigger":
        if self.kind == "at_step" and self.step is None:
            raise ValueError("at_step trigger needs step")
        if self.kind == "after_tool" and not self.tool:
            raise ValueError("after_tool trigger needs tool")
        return self


class EventAction(Strict):
    kind: Literal["customer_message", "goal_change", "fault", "revoke_tool", "grant_tool"]
    text: str | None = None
    goal_version: int | None = None
    tool: str | None = None
    fault_mode: Literal["drop_response", "error", "timeout_before", "rate_limit"] | None = None
    count: int = 1
    role: str | None = None

    @model_validator(mode="after")
    def _fields(self) -> "EventAction":
        need = {
            "customer_message": ["text"],
            "goal_change": ["goal_version", "text"],
            "fault": ["tool", "fault_mode"],
            "revoke_tool": ["tool", "role"],
            "grant_tool": ["tool", "role"],
        }[self.kind]
        missing = [f for f in need if getattr(self, f) is None]
        if missing:
            raise ValueError(f"{self.kind} event needs {missing}")
        return self


class ScheduledEvent(Strict):
    id: str
    trigger: Trigger
    actions: list[EventAction]


class ActorSpec(Strict):
    id: str
    role: str
    instructions: str
    can_complete: bool = False

    @field_validator("id")
    @classmethod
    def _slug_id(cls, v: str) -> str:
        return _slug(v)


class ParticipantSpec(Strict):
    """The simulated customer. ``channel="bus"`` exchanges messages through
    Rehearsal's recorded message bus; ``channel="app"`` makes the participant use
    the application's own customer-facing tools under its own role."""

    name: str
    persona: str
    facts: list[str] = Field(default_factory=list)
    opening_message: str
    channel: Literal["bus", "app"] = "bus"
    role: str | None = None
    send_tool: str | None = None
    send_args: dict[str, Any] = Field(default_factory=dict)
    send_param: str = "content"
    read_tool: str | None = None
    read_args: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _channel(self) -> "ParticipantSpec":
        if self.channel == "app" and not (self.role and self.send_tool):
            raise ValueError("app-channel participant needs role and send_tool")
        return self


class TrajectoryStep(Strict):
    actor: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class NegativeTrajectory(Strict):
    name: str
    description: str
    steps: list[TrajectoryStep]


BUILTIN_TOOLS = ("send_message", "reply_to_customer", "complete", "retry_operation", "wait")


class ScenarioSpec(Strict):
    id: str
    title: str
    family: str
    split: Literal["train", "dev", "holdout"] = "train"
    setup: list[SeedStep] = Field(default_factory=list)
    actors: list[ActorSpec]
    participant: ParticipantSpec
    goals: list[GoalVersion]
    constraints: list[str] = Field(default_factory=list)  # hard-constraint check ids
    checks: list[CheckSpec]
    events: list[ScheduledEvent] = Field(default_factory=list)
    reference: list[TrajectoryStep]
    negatives: list[NegativeTrajectory] = Field(default_factory=list)
    max_steps: int = 40
    max_customer_contacts: int = 3
    contact_tools: list[str] = Field(default_factory=list)  # app tools that count as contacting the customer
    stress: str = ""  # what the job attacks (changed_request, unknown_outcome, social_engineering, ...); see compiler.stress

    @field_validator("id")
    @classmethod
    def _slug_id(cls, v: str) -> str:
        return _slug(v)

    @model_validator(mode="after")
    def _references(self) -> "ScenarioSpec":
        check_ids = {c.id for c in self.checks}
        if len(check_ids) != len(self.checks):
            raise ValueError("duplicate check ids")
        versions = [g.version for g in self.goals]
        if versions != list(range(1, len(versions) + 1)):
            raise ValueError("goal versions must be 1..n in order")
        for g in self.goals:
            if not g.checks:
                raise ValueError(f"goal v{g.version} has no checks")
            missing = set(g.checks) - check_ids
            if missing:
                raise ValueError(f"goal v{g.version} references unknown checks {sorted(missing)}")
        missing = set(self.constraints) - check_ids
        if missing:
            raise ValueError(f"constraints reference unknown checks {sorted(missing)}")
        actors = {a.id for a in self.actors}
        if len(actors) != len(self.actors):
            raise ValueError("duplicate actor ids")
        if not any(a.can_complete for a in self.actors):
            raise ValueError("at least one actor must be able to complete the episode")
        for e in self.events:
            for a in e.actions:
                if a.kind == "goal_change" and a.goal_version not in versions:
                    raise ValueError(f"event {e.id} changes to unknown goal v{a.goal_version}")
        for step in [*self.reference, *(s for n in self.negatives for s in n.steps)]:
            if step.actor not in actors:
                raise ValueError(f"trajectory step references unknown actor {step.actor}")
        return self

    def validate_against(self, world: WorldManifest) -> list[str]:
        """Cross-checks a scenario against the world it runs in."""
        problems: list[str] = []
        roles = {r.name for r in world.roles}
        tools = {t.name for t in world.tools} | set(BUILTIN_TOOLS)
        for a in self.actors:
            if a.role not in roles:
                problems.append(f"actor {a.id} has unknown role {a.role}")
        actor_role = {a.id: a.role for a in self.actors}
        for step in [*self.reference, *(s for n in self.negatives for s in n.steps)]:
            if step.tool not in tools:
                problems.append(f"trajectory uses unknown tool {step.tool}")
                continue
            spec = world.tool(step.tool)
            if spec and actor_role.get(step.actor) not in spec.roles:
                problems.append(f"actor {step.actor} ({actor_role.get(step.actor)}) cannot use {step.tool}")
        for e in self.events:
            for a in e.actions:
                if a.tool and a.tool not in tools:
                    problems.append(f"event {e.id} references unknown tool {a.tool}")
                if a.role and a.role not in roles:
                    problems.append(f"event {e.id} references unknown role {a.role}")
            if e.trigger.tool and e.trigger.tool not in tools:
                problems.append(f"event {e.id} trigger references unknown tool {e.trigger.tool}")
        if not any(world.role(actor_role[a.id]) and world.role(actor_role[a.id]).customer_channel for a in self.actors):
            problems.append("no actor has a customer channel, so the participant cannot be reached")
        p = self.participant
        if p.channel == "app":
            if p.role not in roles:
                problems.append(f"participant role {p.role} is unknown")
            for name in (p.send_tool, p.read_tool):
                spec = world.tool(name) if name else None
                if name and spec is None:
                    problems.append(f"participant tool {name} is unknown")
                elif spec and p.role not in spec.roles:
                    problems.append(f"participant role {p.role} cannot use {name}")
        for t in self.contact_tools:
            if world.tool(t) is None:
                problems.append(f"contact tool {t} is unknown")
        probes = {pr.name for pr in world.state_probes}
        for c in self.checks:
            if c.source == "app" and not probes:
                problems.append(f"check {c.id} needs a state probe but the world has none")
            if c.probe and c.probe not in probes:
                problems.append(f"check {c.id} references unknown probe {c.probe}")
        return problems


# --------------------------------------------------------------------------- execution records

ActionStatus = Literal[
    "PROPOSED", "AUTHORIZED", "RUNNING", "SUCCEEDED", "FAILED", "UNKNOWN", "SUPERSEDED", "REJECTED"
]


class OracleResult(BaseModel):
    goal_version: int
    goal_satisfied: bool
    hard_constraint_violations: list[str]
    check_results: list[dict[str, Any]]
    rejected_attempts: int = 0
    unnecessary_interruptions: int = 0
    duplicate_effects: int = 0
    recovery_result: Literal["recovered", "not_recovered", "not_applicable"] = "not_applicable"
    elapsed_ms: int = 0
    model_cost_usd: float = 0.0
    tokens: int = 0
    environment_error: str | None = None
    claimed_complete: bool = False
    false_completion: bool = False

    @property
    def reward(self) -> int:
        if self.hard_constraint_violations:
            return -1
        return 1 if self.goal_satisfied and not self.environment_error else 0


class AgentProfile(BaseModel):
    name: str
    version: int = 1
    driver: Literal["llm", "external"] = "llm"  # external: actions arrive through the API
    system_prompt: str = ""
    tool_guidance: dict[str, str] = Field(default_factory=dict)
    model: str | None = None  # fallback chain; None uses REHEARSAL_MODEL_AGENT
    temperature: float = 0.2
    max_turns_per_actor: int = 25


DEFAULT_AGENT_PROMPT = (
    "You are {actor_id}, working as {role} inside a company application. "
    "Use only the tools provided. Read tool results carefully; never invent IDs or outcomes. "
    "Your assignment: {instructions}"
)


def render_template(text: str, scopes: dict[str, dict[str, Any]]) -> str:
    """Replaces ``{{scope.key}}`` placeholders; unknown placeholders raise KeyError."""

    def sub(m: re.Match[str]) -> str:
        scope, key = m.group(1), m.group(2)
        if scope not in scopes or key not in scopes[scope]:
            raise KeyError(f"{{{{{scope}.{key}}}}} is not defined")
        return str(scopes[scope][key])

    return TEMPLATE.sub(sub, text)


def render_value(value: Any, scopes: dict[str, dict[str, Any]]) -> Any:
    if isinstance(value, str):
        m = TEMPLATE.fullmatch(value.strip())
        if m:  # a bare placeholder keeps the variable's type (ints stay ints)
            scope, key = m.group(1), m.group(2)
            if scope not in scopes or key not in scopes[scope]:
                raise KeyError(f"{{{{{scope}.{key}}}}} is not defined")
            return scopes[scope][key]
        return render_template(value, scopes)
    if isinstance(value, list):
        return [render_value(v, scopes) for v in value]
    if isinstance(value, dict):
        return {k: render_value(v, scopes) for k, v in value.items()}
    return value


def dig(data: Any, dotted: str) -> Any:
    """Reads ``a.b.0.c`` (or JSONPath-style ``$.a.b[0].c``) from nested JSON; raises KeyError when absent."""
    path = re.sub(r"\[(\d+)\]", r".\1", dotted.strip()).lstrip("$").lstrip(".")
    cur = data
    for part in path.split(".") if path else []:
        try:
            cur = cur[int(part)] if isinstance(cur, list) else cur[part]
        except (KeyError, IndexError, ValueError, TypeError):
            have = list(cur)[:20] if isinstance(cur, dict) else f"a list of {len(cur)}" if isinstance(cur, list) else type(cur).__name__
            raise KeyError(f"{dotted!r}: no {part!r} (found {have})") from None
    return cur
