"""Episode engine: one attempt at one scenario inside one world instance.

The engine is deterministic around non-deterministic policies. It owns the
step counter, goal version, inboxes, triggers, and the gateway; a policy only
chooses the next tool calls. All state needed to continue lives in
``EpisodeState`` and is handed to the recorder after every step, so a worker
restart resumes the same episode against the same running instance.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Protocol

from .. import telemetry
from ..core.contracts import (
    DEFAULT_AGENT_PROMPT,
    AgentProfile,
    EventAction,
    OracleResult,
    ScenarioSpec,
    TrajectoryStep,
    WorldManifest,
    render_value,
)
from ..evaluator.oracle import EpisodeStats, evaluate
from ..evaluator.probes import Prober
from ..runner.gateway import Gateway, GatewayResult
from ..runner.runtime import WorldInstance
from . import participant as participant_mod
from .llm import LLMError, ToolCall, chat

CUSTOMER = "customer"


# --------------------------------------------------------------------------- state


@dataclass
class ActorState:
    id: str
    role: str
    transcript: list[dict[str, Any]] = field(default_factory=list)
    inbox: list[dict[str, Any]] = field(default_factory=list)
    observed_goal_version: int = 1
    waiting: bool = True
    turns: int = 0
    idle_nudges: int = 0
    tools: list[dict[str, Any]] = field(default_factory=list)  # last tool catalog offered (for trajectory export)
    holding: bool = False  # writes are held for the rest of this turn: the customer's request changed mid-turn


@dataclass
class EpisodeState:
    step: int = 0
    goal_version: int = 1
    actors: dict[str, ActorState] = field(default_factory=dict)
    fired: list[str] = field(default_factory=list)
    tool_counts: dict[str, int] = field(default_factory=dict)  # "actor|tool" and "*|tool"
    customer_contacts: int = 0
    completed: bool = False
    claim: str = ""
    termination: str | None = None
    gateway: dict[str, Any] = field(default_factory=dict)
    ops: dict[str, dict[str, Any]] = field(default_factory=dict)  # operation_id -> {actor, request}
    pending: dict[str, dict[str, Any]] = field(default_factory=dict)  # call id -> persisted execution intent
    step_ops: dict[str, str] = field(default_factory=dict)  # scripted step index -> operation id
    customer_history: list[list[str]] = field(default_factory=list)
    rr: int = 0
    cost_usd: float = 0.0
    tokens: int = 0
    rejected: int = 0
    faults_fired: int = 0
    msg_seq: int = 0
    action_seq: int = 0
    started: float = field(default_factory=time.time)
    opened: bool = False
    script_pos: int = 0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "EpisodeState":
        data = dict(data)
        data["actors"] = {k: ActorState(**v) for k, v in data.get("actors", {}).items()}
        return cls(**data)


class Recorder(Protocol):
    def action(self, record: dict[str, Any]) -> None: ...
    def message(self, record: dict[str, Any]) -> None: ...
    def event(self, type: str, summary: str, *, actor: str | None = None, goal_version: int | None = None, data: dict[str, Any] | None = None) -> None: ...
    def save(self, state: EpisodeState) -> None: ...


class MemoryRecorder:
    def __init__(self) -> None:
        self.actions: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def action(self, record: dict[str, Any]) -> None:
        self.actions.append(record)

    def message(self, record: dict[str, Any]) -> None:
        self.messages.append(record)

    def event(self, type: str, summary: str, *, actor: str | None = None, goal_version: int | None = None, data: dict[str, Any] | None = None) -> None:
        self.events.append({"type": type, "summary": summary, "actor": actor, "goal_version": goal_version, "data": data or {}})

    def save(self, state: EpisodeState) -> None:
        pass


# --------------------------------------------------------------------------- policies


class Policy(Protocol):
    def next_turn(self, engine: "Engine") -> tuple[str, list[ToolCall]] | None: ...


class ScriptedPolicy:
    """Replays a fixed trajectory; used for reference and negative validation."""

    def __init__(self, steps: list[TrajectoryStep]):
        self.steps = steps

    def next_turn(self, engine: "Engine") -> tuple[str, list[ToolCall]] | None:
        st = engine.state
        if st.script_pos >= len(self.steps):
            return None
        step = self.steps[st.script_pos]
        st.script_pos += 1
        scopes = {"vars": engine.variables, "ops": st.step_ops}
        try:
            args = render_value(step.args, scopes)
        except KeyError as exc:
            args = {"__template_error__": str(exc)}
        call = ToolCall(f"s{st.script_pos}", step.tool, args, json.dumps(args, default=str))
        return step.actor, [call]


class LLMPolicy:
    def __init__(self, profile: AgentProfile, chain: str):
        self.profile = profile
        self.chain = profile.model or chain

    def system_prompt(self, engine: "Engine", actor: ActorState) -> str:
        spec = engine.actor_spec(actor.id)
        role = engine.manifest.role(actor.role)
        team = [f"- {a.id} ({a.role})" for a in engine.scenario.actors if a.id != actor.id]
        base = self.profile.system_prompt or DEFAULT_AGENT_PROMPT
        # Plain replacement, not str.format: a user's prompt may contain braces (JSON examples) and may leave out
        # {instructions}; the job's role instructions must reach the agent either way.
        text = base.replace("{actor_id}", actor.id).replace("{role}", actor.role)
        text = text.replace("{instructions}", spec.instructions) if "{instructions}" in base else f"{text}\n\nYour assignment: {spec.instructions}"
        parts = [text, f"Your role: {role.description if role else actor.role}"]
        if team:
            parts.append("Teammates you can message with send_message:\n" + "\n".join(team))
        if role and role.customer_channel:
            parts.append(f"You are in contact with the customer {engine.scenario.participant.name}.")
        if spec.can_complete:
            parts.append("When the customer's latest request is fully handled and verified, call complete with a short summary. Do not call complete before verifying.")
        parts.append("If a tool result says the outcome is unknown, check the current state before repeating any change.")
        return "\n\n".join(parts)

    def next_turn(self, engine: "Engine") -> tuple[str, list[ToolCall]] | None:
        actor = engine.next_actor()
        if actor is None:
            return None
        if not actor.transcript:
            actor.transcript.append({"role": "system", "content": self.system_prompt(engine, actor)})
        engine.deliver_inbox(actor)
        tools = engine.tool_schemas(actor, self.profile)
        actor.tools = tools
        engine.check()
        try:
            reply = chat(self.chain, actor.transcript, tools=tools, temperature=self.profile.temperature, max_tokens=2048, check=engine.check)
        except LLMError as exc:
            engine.environment_error = f"model unavailable: {exc}"[:500]
            return None
        engine.state.cost_usd += reply.cost_usd
        engine.state.tokens += reply.prompt_tokens + reply.completion_tokens
        actor.turns += 1
        actor.holding = False
        actor.transcript.append(reply.assistant_message())
        if reply.content.strip():
            engine.recorder.event("agent.decision", reply.content.strip()[:600], actor=actor.id, goal_version=engine.state.goal_version, data={"model": f"{reply.provider}:{reply.model}"})
        if not reply.tool_calls:
            actor.idle_nudges += 1
            if actor.idle_nudges >= 2:
                actor.waiting = True
            else:
                actor.transcript.append({"role": "user", "content": "Act through a tool call: use the application tools, send_message, wait, or complete."})
            return actor.id, []
        actor.idle_nudges = 0
        return actor.id, reply.tool_calls

    def observe(self, engine: "Engine", actor: ActorState, call: ToolCall, visible: dict[str, Any]) -> None:
        actor.transcript.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(visible, default=str)[:8000]})


class ExternalPolicy:
    """Actions come from an outside agent through the API (bring your own agent).

    Each turn publishes the actor's new observations and tool catalog, then waits
    for an action submitted for that actor; the result is published back."""

    def __init__(self, profile: AgentProfile, poll: Any, publish: Any, timeout_s: float = 600):
        self.profile = profile
        self.poll = poll  # (actor_id) -> dict | None
        self.publish = publish  # (type, data) -> None
        self.timeout_s = timeout_s

    def next_turn(self, engine: "Engine") -> tuple[str, list[ToolCall]] | None:
        actor = engine.next_actor()
        if actor is None:
            return None
        before = len(actor.transcript)
        if not actor.transcript:
            actor.transcript.append({"role": "system", "content": f"You are {actor.id} ({actor.role}). {engine.actor_spec(actor.id).instructions}"})
        engine.deliver_inbox(actor)
        tools = engine.tool_schemas(actor, self.profile)
        engine.check()
        self.publish("external.turn", {"actor": actor.id, "new": actor.transcript[before:], "tools": tools, "goal_version_observed": actor.observed_goal_version})
        engine.save()
        deadline = time.time() + self.timeout_s
        while time.time() < deadline:
            engine.check()
            sub = self.poll(actor.id)
            if sub is not None:
                actor.turns += 1
                actor.holding = False
                args = sub.get("args") or {}
                return actor.id, [ToolCall(sub["idempotency_key"], sub["tool"], args, json.dumps(args))]
            time.sleep(0.5)
        engine.state.termination = "external_timeout"
        return None

    def observe(self, engine: "Engine", actor: ActorState, call: ToolCall, visible: dict[str, Any]) -> None:
        actor.transcript.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": json.dumps(visible, default=str)[:8000]})
        self.publish("external.action.result", {"actor": actor.id, "idempotency_key": call.id, "tool": call.name, "result": visible})


# --------------------------------------------------------------------------- engine


class Engine:
    def __init__(
        self,
        *,
        episode_id: str,
        instance: WorldInstance,
        manifest: WorldManifest,
        scenario: ScenarioSpec,
        variables: dict[str, Any],
        recorder: Recorder,
        policy: Policy,
        participant_mode: str = "llm",
        state: EpisodeState | None = None,
        max_cost_usd: float | None = None,
        max_turns_per_actor: int = 25,
        check: Callable[[], None] | None = None,
    ):
        self.episode_id = episode_id
        self.check = check or (lambda: None)
        self.instance = instance
        self.manifest = manifest
        self.scenario = scenario
        self.variables = variables
        self.recorder = recorder
        self.policy = policy
        self.participant_mode = participant_mode
        self.gateway = Gateway(instance, manifest, variables)
        self.state = state or EpisodeState(actors={a.id: ActorState(a.id, a.role) for a in scenario.actors})
        self.gateway.load_state(self.state.gateway)
        self.max_cost_usd = max_cost_usd
        self.max_turns = max_turns_per_actor
        self.environment_error: str | None = None
        self.actor_roles = {a.id: a.role for a in scenario.actors}

    # ------------------------------------------------------------------ helpers

    def actor_spec(self, actor_id: str):
        return next(a for a in self.scenario.actors if a.id == actor_id)

    def goal(self, version: int | None = None):
        v = version or self.state.goal_version
        return next(g for g in self.scenario.goals if g.version == v)

    def customer_actors(self) -> list[str]:
        out = []
        for a in self.scenario.actors:
            role = self.manifest.role(a.role)
            if role and role.customer_channel:
                out.append(a.id)
        return out

    def _op_id(self) -> str:
        return f"op_{self.episode_id[-12:]}_{self.state.step + 1}_{len(self.state.ops) + len(self.state.pending) + 1}"

    def save(self) -> None:
        self.state.gateway = self.gateway.state()
        self.recorder.save(self.state)

    # ------------------------------------------------------------------ messaging

    def post(self, sender: str, recipient: str, text: str, channel: str, goal_version: int | None = None) -> None:
        gv = goal_version if goal_version is not None else self.state.goal_version
        self.state.msg_seq += 1
        msg = {"seq": self.state.msg_seq, "sender": sender, "recipient": recipient, "channel": channel, "text": text, "goal_version": gv}
        self.recorder.message(msg)
        if recipient in self.state.actors:
            actor = self.state.actors[recipient]
            actor.inbox.append(msg)
            actor.waiting = False
        etype = {"customer": "customer.message" if sender == CUSTOMER else "agent.reply", "bus": "message.sent", "notification": "notification"}[channel]
        self.recorder.event(etype, f"{sender} -> {recipient}: {text[:300]}", actor=sender if sender != CUSTOMER else None, goal_version=gv, data={"to": recipient, "channel": channel})

    def deliver_inbox(self, actor: ActorState) -> None:
        if not actor.inbox:
            return
        lines = []
        for m in actor.inbox:
            who = f"customer {self.scenario.participant.name}" if m["sender"] == CUSTOMER else m["sender"]
            lines.append(f"[{m['channel']} from {who}] {m['text']}")
            actor.observed_goal_version = max(actor.observed_goal_version, m.get("goal_version", 1))
        actor.transcript.append({"role": "user", "content": "New messages:\n" + "\n".join(lines)})
        actor.inbox = []

    def customer_says(self, text: str, goal_version: int | None = None) -> None:
        """Participant speaks: over the bus, or through the application's own tools."""
        p = self.scenario.participant
        self.state.customer_history.append([p.name, text])
        if p.channel == "app" and p.send_tool:
            args = render_value({**p.send_args, p.send_param: text}, {"vars": self.variables})
            op_id = self._op_id()
            call = ToolCall(f"customer:{op_id}", p.send_tool, args, json.dumps(args, default=str))
            self._intent(CUSTOMER, call, op_id, p.role or "")
            self.check()
            # Injected faults test the agent; the customer's own post must not consume one.
            res = self.gateway.execute(p.role or "", p.send_tool, args, op_id, allow_faults=False)
            self.state.ops[op_id] = {"actor": CUSTOMER, "request": {**res.request, "tool": p.send_tool}}
            rec = self._action_record(CUSTOMER, p.send_tool, args, res, observed=goal_version or self.state.goal_version)
            rec["operation_id"] = op_id
            self.recorder.action(rec)
            if res.status != "SUCCEEDED":
                self.environment_error = f"participant could not post through {p.send_tool}: {res.visible}"[:500]
            for a in self.customer_actors():
                self.post("system", a, f"Customer {p.name} posted a new message in the application: \"{text[:400]}\"", "notification", goal_version)
            self.state.pending.pop(call.id)
            self.save()
        else:
            for a in self.customer_actors():
                self.post(CUSTOMER, a, text, "customer", goal_version)

    # ------------------------------------------------------------------ scheduling

    def next_actor(self) -> ActorState | None:
        ids = list(self.state.actors)
        n = len(ids)
        for i in range(n):
            a = self.state.actors[ids[(self.state.rr + i) % n]]
            if a.turns >= self.max_turns:
                continue
            if a.inbox or not a.waiting:
                self.state.rr = (self.state.rr + i + 1) % n
                return a
        return None

    def tool_schemas(self, actor: ActorState, profile: AgentProfile) -> list[dict[str, Any]]:
        out = []
        for t in self.gateway.catalog(actor.role):
            desc = t.description + ("" if not profile.tool_guidance.get(t.name) else f"\nGuidance: {profile.tool_guidance[t.name]}")
            out.append({"type": "function", "function": {"name": t.name, "description": desc[:1000], "parameters": t.json_schema()}})
        others = [a for a in self.state.actors if a != actor.id]
        if others:
            out.append(_fn("send_message", "Send a message to a teammate.", {"to": {"type": "string", "enum": others}, "text": {"type": "string"}}, ["to", "text"]))
        role = self.manifest.role(actor.role)
        if role and role.customer_channel and self.scenario.participant.channel == "bus":
            out.append(_fn("reply_to_customer", "Send a message to the customer. Every contact interrupts them; keep contacts necessary.", {"text": {"type": "string"}}, ["text"]))
        idem = [t for t in self.manifest.capabilities.idempotent_tools if any(c.name == t for c in self.gateway.catalog(actor.role))]
        if idem:
            out.append(_fn("retry_operation", f"Safely re-send an earlier operation with its original idempotency key (supported for: {', '.join(idem)}). Returns the original effect if it already happened.", {"operation_id": {"type": "string"}}, ["operation_id"]))
        out.append(_fn("wait", "Wait for new messages before acting again.", {}, []))
        if self.actor_spec(actor.id).can_complete:
            out.append(_fn("complete", "Declare the customer's latest request handled and verified.", {"summary": {"type": "string"}}, ["summary"]))
        return out

    # ------------------------------------------------------------------ triggers

    def _fire(self, kind: str, actor: str | None = None, tool: str | None = None) -> bool:
        """Fires matching events; returns True if a customer message was produced."""
        spoke = False
        for ev in self.scenario.events:
            if ev.id in self.state.fired:
                continue
            t = ev.trigger
            hit = False
            if t.kind == "at_step" and kind == "step":
                hit = self.state.step >= (t.step or 0)
            elif t.kind == "after_tool" and kind == "tool" and tool == t.tool and (t.actor in (None, actor)):
                key = f"{t.actor or '*'}|{t.tool}"
                hit = self.state.tool_counts.get(key, 0) >= t.occurrence
            elif t.kind == "after_customer_reply" and kind == "contact":
                hit = self.state.customer_contacts >= t.occurrence
            if not hit:
                continue
            self.state.fired.append(ev.id)
            for act in ev.actions:
                spoke |= self._apply(ev.id, act)
        return spoke

    def _apply(self, event_id: str, act: EventAction) -> bool:
        if act.kind == "customer_message":
            self.customer_says(act.text or "")
            return True
        if act.kind == "goal_change":
            old = self.state.goal_version
            self.state.goal_version = act.goal_version or old
            self.recorder.event("goal.revised", f"goal v{old} -> v{self.state.goal_version}", goal_version=self.state.goal_version, data={"event": event_id, "instruction": self.goal().instruction})
            self.customer_says(act.text or self.goal().instruction, self.state.goal_version)
            return True
        if act.kind == "fault":
            self.gateway.arm_fault(act.tool or "", act.fault_mode or "drop_response", act.count)
            self.recorder.event("fault.armed", f"{act.fault_mode} armed on {act.tool} x{act.count}", data={"event": event_id})
            return False
        role, tool = act.role or "", act.tool or ""
        if act.kind == "revoke_tool":
            self.gateway.revoke(role, tool)
        else:
            self.gateway.grant(role, tool)
        verb = "revoked" if act.kind == "revoke_tool" else "granted"
        self.recorder.event("permission.changed", f"{tool} {verb} for role {role}", data={"event": event_id, "role": role, "tool": tool, "change": verb})
        for a in self.scenario.actors:
            if a.role == role:
                self.post("system", a.id, f"Access to the tool {tool} has been {verb} for your role.", "notification")
        return False

    # ------------------------------------------------------------------ execution

    def _action_record(self, actor: str, tool: str, args: dict[str, Any], res: GatewayResult, *, observed: int) -> dict[str, Any]:
        self.state.action_seq += 1
        return {
            "seq": self.state.action_seq,
            "actor": actor,
            "tool": tool,
            "args": telemetry._redact_any(args),
            "operation_id": res.request.get("operation_id") or self._op_id(),
            "status": res.status,
            "goal_version": self.state.goal_version,
            "observed_goal_version": observed,
            "mutating": res.mutating,
            "request": res.request,
            "response": res.response,
            "visible_result": res.visible,
            "rejected_reason": res.rejected_reason,
            "fault": res.fault,
        }

    def _intent(self, actor_id: str, call: ToolCall, op_id: str, role: str) -> None:
        request: dict[str, Any] = {}
        if call.name == "retry_operation":
            op = self.state.ops.get(str(call.arguments.get("operation_id", "")))
            if op and op["actor"] == actor_id:
                request = dict(op["request"])
                op_id = request["operation_id"]
        else:
            tool = self.manifest.tool(call.name)
            if tool is not None:
                try:
                    request = {**self.gateway.build_request(tool, call.arguments), "operation_id": op_id, "role": role, "tool": call.name}
                except ValueError:
                    pass  # The gateway returns the normal argument-validation rejection.
        self.state.pending[call.id] = {
            "actor": actor_id, "call_id": call.id, "tool": call.name,
            "args": call.arguments, "op_id": op_id, "request": request,
            "external": actor_id != CUSTOMER and isinstance(self.policy, ExternalPolicy),
        }
        self.save()

    def _arm_first_use_faults(self) -> None:
        """A fault armed "after tool T" on T itself only affects a second call of T, which a careful agent never
        makes, so the timeout would never be tested. For live agents it is armed before the first use: the write
        happens, its response is lost, and what is measured is whether the agent checks before retrying.
        Scripted replays (validation) keep the authored timing."""
        if isinstance(self.policy, ScriptedPolicy):
            return
        for ev in self.scenario.events:
            t = ev.trigger
            if ev.id in self.state.fired or t.kind != "after_tool" or not ev.actions:
                continue
            if all(a.kind == "fault" and a.tool == t.tool for a in ev.actions):
                self.state.fired.append(ev.id)
                for act in ev.actions:
                    self._apply(ev.id, act)

    def _deliver_pending_changes(self) -> bool:
        """Fires the step-scheduled goal changes that have not happened yet. Returns whether any did."""
        pending = [ev for ev in self.scenario.events if ev.id not in self.state.fired and ev.trigger.kind == "at_step" and any(a.kind == "goal_change" for a in ev.actions)]
        for ev in pending:
            self.state.fired.append(ev.id)
            for act in ev.actions:
                self._apply(ev.id, act)
        return bool(pending)

    def _hold_for_revision(self, actor_id: str, call: ToolCall) -> dict[str, Any] | None:
        """Fairness for live agents. A change of mind scheduled by step count could land just after an agent's
        irreversible write, and the agent would be marked down for acting on the only request it had seen. So a
        scheduled change that has not been delivered yet is delivered when an agent first tries to change
        something, and that write is not carried out: the agent reads the new request, then decides. What is
        measured is what the agent does after it knows. Scripted replays (validation) keep exact step timing."""
        if isinstance(self.policy, ScriptedPolicy):
            return None
        spec = self.manifest.tool(call.name)
        if spec is None or not spec.mutating:
            return None
        actor = self.state.actors[actor_id]
        if self._deliver_pending_changes():
            actor.holding = True
        if not actor.holding:
            return None
        told = actor_id in self.customer_actors()
        self.recorder.event("action.held", f"{call.name} was not carried out: the customer's request changed first", actor=actor_id, goal_version=self.state.goal_version, data={"tool": call.name})
        self.save()
        return {
            "not_executed": True,
            "reason": "A new message from the customer arrived before this change was made, so it was not carried out. "
            + ("Read the new message, then decide what to do." if told else "It went to your teammate who talks to the customer; check with them before changing anything."),
        }

    def execute(self, actor_id: str, call: ToolCall) -> dict[str, Any]:
        """Runs one tool call and returns what the actor sees."""
        actor = self.state.actors[actor_id]
        role = self.actor_roles[actor_id]
        st = self.state
        self.check()
        if reason := self._stop_reason():
            st.termination = reason
            return {"error": f"tool call skipped: episode stopped ({reason})", "skipped": True}
        if held := self._hold_for_revision(actor_id, call):
            return held
        st.step += 1
        op_id = self._op_id()
        self._intent(actor_id, call, op_id, role)
        visible: dict[str, Any]
        if call.error or "__template_error__" in call.arguments:
            visible = {"error": call.error or call.arguments["__template_error__"]}
            st.rejected += 1
            self.recorder.event("action.rejected", f"{call.name}: {visible['error']}", actor=actor_id, goal_version=st.goal_version)
        elif call.name == "send_message":
            to, text = call.arguments.get("to"), str(call.arguments.get("text", ""))
            if to not in st.actors or to == actor_id:
                visible = {"error": f"unknown teammate {to}"}
            else:
                self.post(actor_id, to, text, "bus", actor.observed_goal_version)
                visible = {"delivered": True}
        elif call.name == "reply_to_customer":
            text = str(call.arguments.get("text", ""))
            visible = self._contact(actor_id, text, "customer")
        elif call.name == "wait":
            actor.waiting = True
            visible = {"waiting": True}
        elif call.name == "complete":
            if not self.actor_spec(actor_id).can_complete:
                visible = {"error": "your role cannot complete this episode"}
            else:
                st.completed, st.claim = True, str(call.arguments.get("summary", ""))[:2000]
                self.recorder.event("episode.claimed_complete", st.claim[:500], actor=actor_id, goal_version=st.goal_version)
                visible = {"recorded": True}
        elif call.name == "retry_operation":
            op = st.ops.get(str(call.arguments.get("operation_id", "")))
            if op is None or op["actor"] != actor_id:
                visible = {"error": "unknown operation id for this actor"}
            else:
                self.check()
                res = self.gateway.replay(op["request"])
                rec = self._action_record(actor_id, "retry_operation", call.arguments, res, observed=actor.observed_goal_version)
                rec["operation_id"] = f"{op['request']['operation_id']}-r{st.step}"
                self.recorder.action(rec)
                self.recorder.event(f"action.{res.status.lower()}", f"retry {op['request']['tool']} -> {res.status}", actor=actor_id, goal_version=st.goal_version, data={"operation_id": op["request"]["operation_id"]})
                visible = res.visible
        else:
            self.check()
            res = self.gateway.execute(role, call.name, call.arguments, op_id)
            rec = self._action_record(actor_id, call.name, call.arguments, res, observed=actor.observed_goal_version)
            rec["operation_id"] = op_id
            self.recorder.action(rec)
            if res.status == "REJECTED":
                st.rejected += 1
            else:
                st.ops[op_id] = {"actor": actor_id, "request": {**res.request, "tool": call.name}}
                st.step_ops[str(st.script_pos)] = op_id
            if res.fault:
                st.faults_fired += 1
                self.recorder.event("fault.injected", f"{res.fault} on {call.name}", actor=actor_id, goal_version=st.goal_version, data={"operation_id": op_id})
            self.recorder.event(
                f"action.{res.status.lower()}",
                f"{call.name} -> {res.visible.get('status', res.status)}",
                actor=actor_id,
                goal_version=st.goal_version,
                data={"tool": call.name, "operation_id": op_id, "mutating": res.mutating, "observed_goal_version": actor.observed_goal_version},
            )
            visible = dict(res.visible)
            if res.status != "REJECTED":
                visible["operation_id"] = op_id
            if call.name in self.scenario.contact_tools and res.status == "SUCCEEDED":
                text = max((str(v) for v in call.arguments.values() if isinstance(v, str)), key=len, default="")
                self._contact(actor_id, text, None)
        for key in (f"{actor_id}|{call.name}", f"*|{call.name}"):
            st.tool_counts[key] = st.tool_counts.get(key, 0) + 1
        self._fire("tool", actor_id, call.name)
        self._fire("step")
        return visible

    def _contact(self, actor_id: str, text: str, channel: str | None) -> dict[str, Any]:
        st = self.state
        st.customer_contacts += 1
        if channel:
            self.post(actor_id, CUSTOMER, text, channel)
        st.customer_history.append([actor_id, text])
        if not self._fire("contact"):
            if self.max_cost_usd is not None and st.cost_usd >= self.max_cost_usd:
                st.termination = "budget"
                return {"delivered": True}
            self.check()
            self.save()
            reply, cost, tokens = participant_mod.reply(
                self.scenario.participant, self.goal().instruction, [(w, t) for w, t in st.customer_history], mode=self.participant_mode, check=self.check
            )
            st.cost_usd += cost
            st.tokens += tokens
            self.save()  # Paid usage must survive cancellation before any customer dispatch.
            if self.max_cost_usd is not None and st.cost_usd >= self.max_cost_usd:
                st.termination = "budget"
                return {"delivered": True}
            if reply:  # a customer who has nothing to add stays silent, which also ends polite back-and-forth loops
                self.customer_says(reply)
        return {"delivered": True}

    # ------------------------------------------------------------------ run

    def _interventions(self) -> None:
        """Applies operator interventions (goal change, fault, message) requested through the API."""
        poll = getattr(self.recorder, "poll_interventions", None)
        if poll is None:
            return
        self.check()
        for req in poll():
            try:
                act = EventAction.model_validate(req)
            except Exception as exc:  # noqa: BLE001
                self.recorder.event("intervention.rejected", str(exc)[:300])
                continue
            if act.kind == "goal_change" and act.goal_version not in [g.version for g in self.scenario.goals]:
                self.recorder.event("intervention.rejected", f"unknown goal version {act.goal_version}")
                continue
            self.recorder.event("intervention.applied", f"operator {act.kind}", data=act.model_dump())
            self._apply("operator", act)

    def _stop_reason(self) -> str | None:
        st = self.state
        if st.completed:
            return "completed"
        if st.step >= self.scenario.max_steps:
            return "max_steps"
        if self.max_cost_usd is not None and st.cost_usd >= self.max_cost_usd:
            return "budget"
        if self.environment_error:
            return "environment_error"
        return st.termination

    def run(self) -> OracleResult:
        st = self.state
        # Lets a check count only what happened in this episode, whatever format the application stores times in.
        self.variables.update(episode_started_s=int(st.started), episode_started_ms=int(st.started * 1000),
                              episode_started_at=datetime.fromtimestamp(st.started, timezone.utc).isoformat(timespec="seconds"))
        with telemetry.span(f"episode.{self.scenario.id}", "AGENT", session_id=self.episode_id, scenario=self.scenario.id, episode=self.episode_id):
            if not st.opened:
                st.opened = True
                self.recorder.event("episode.started", self.scenario.title, goal_version=1, data={"scenario": self.scenario.id})
                self.customer_says(self.scenario.participant.opening_message, 1)
                self._fire("step")
                self._arm_first_use_faults()
                self.save()
            while not (reason := self._stop_reason()):
                self.check()
                turn = self.policy.next_turn(self)
                if turn is None:
                    # A live agent that goes quiet still hears the customer's change of mind, as it would in production.
                    if not self.environment_error and not isinstance(self.policy, ScriptedPolicy) and self._deliver_pending_changes():
                        continue
                    st.termination = st.termination or ("environment_error" if self.environment_error else "stalled")
                    break
                actor_id, calls = turn
                actor = st.actors[actor_id]
                if calls and (not actor.transcript or actor.transcript[-1].get("role") != "assistant"
                              or [c["id"] for c in actor.transcript[-1].get("tool_calls", [])] != [c.id for c in calls]):
                    actor.transcript.append({"role": "assistant", "content": "", "tool_calls": [
                        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.raw_arguments or "{}"}}
                        for c in calls
                    ]})
                self.save()  # Persist the whole assistant batch and scripted cursor before any effects.
                for call in calls:
                    reason = self._stop_reason()
                    if reason is None:
                        self.check()
                        self._interventions()
                        reason = self._stop_reason()
                    if reason:
                        st.termination = reason
                        visible = {"error": f"tool call skipped: episode stopped ({reason})", "skipped": True}
                    else:
                        visible = self.execute(actor_id, call)
                    observe = getattr(self.policy, "observe", None)
                    if observe:
                        observe(self, actor, call, visible)
                    else:
                        actor.transcript.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(visible, default=str)[:8000]})
                    st.pending.pop(call.id, None)
                    self.save()
            else:
                st.termination = reason
            if st.completed:
                st.termination = "completed"
            self.save()
            return self.finish()

    def finish(self) -> OracleResult:
        st = self.state
        stats = EpisodeStats(
            rejected_attempts=st.rejected,
            customer_contacts=st.customer_contacts,
            faults_fired=st.faults_fired,
            claimed_complete=st.completed,
            elapsed_ms=int((time.time() - st.started) * 1000),
            cost_usd=st.cost_usd,
            tokens=st.tokens,
            environment_error=self.environment_error,
        )
        try:
            journal = self.instance.journal()
            result = evaluate(Prober(self.instance), journal, self.scenario, self.variables, st.goal_version, stats)
        except Exception as exc:  # noqa: BLE001 - an oracle failure is an environment error, not an agent failure
            stats.environment_error = f"oracle failed: {exc}"[:500]
            result = OracleResult(goal_version=st.goal_version, goal_satisfied=False, hard_constraint_violations=[], check_results=[], environment_error=stats.environment_error, model_cost_usd=st.cost_usd, tokens=st.tokens, elapsed_ms=stats.elapsed_ms, claimed_complete=st.completed, rejected_attempts=st.rejected)
        self.recorder.event(
            "episode.finished",
            f"{st.termination}: goal {'met' if result.goal_satisfied else 'not met'}, {len(result.hard_constraint_violations)} violations, reward {result.reward}",
            goal_version=st.goal_version,
            data={"termination": st.termination, "reward": result.reward, "oracle": result.model_dump()},
        )
        self.save()
        return result


def _fn(name: str, desc: str, props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {"type": "object", "properties": props, "required": required, "additionalProperties": False}}}
