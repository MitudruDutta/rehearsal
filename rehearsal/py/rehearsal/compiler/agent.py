"""Tool loop shared by compiler roles (inspector, builder, scenario designer,
validation investigator). A role finishes only by calling its submit tool and
passing a deterministic validator; validator feedback goes back to the model as
the tool result, so the model repairs its own output with evidence."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from ..redaction import redact, redact_any
from ..agents.llm import LLMError, chat


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[[dict[str, Any]], Any]

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


def params(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required if required is not None else list(props), "additionalProperties": False}


class Rejected(Exception):
    """Raised by a submit validator; the message is returned to the model."""


@dataclass
class AgentRun:
    result: Any = None
    tool_calls: int = 0
    cost_usd: float = 0.0
    tokens: int = 0
    attempts: int = 0
    transcript_tail: list[str] = field(default_factory=list)


class CompilerAgentError(Exception):
    terminal = False  # True: the worker does not start another attempt by itself

    def __init__(self, message: str, run: AgentRun):
        super().__init__(message)
        self.run = run


STUCK_AFTER = 3  # identical rejections in a row before a role stops


RESULT_LIMIT = 14_000
KEEP_FULL_RESULTS = 8


def _trim(messages: list[dict[str, Any]]) -> None:
    """Keeps the newest tool results whole and shortens older ones."""
    tool_idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    for i in tool_idx[:-KEEP_FULL_RESULTS]:
        content = messages[i]["content"]
        if len(content) > 600:
            messages[i]["content"] = content[:500] + "\n...[older result elided]"


def _unstring(args: dict[str, Any], schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """Some models send nested arrays/objects as JSON text ("tools": "[{...}]"); validators expect the value. For a
    field the schema declares as an object or array, text that does not parse is refused with the parse error, so the
    model can fix it instead of resending it; a plain text field may start with a bracket."""
    structured = {k for k, p in ((schema or {}).get("properties") or {}).items() if isinstance(p, dict) and p.get("type") in ("object", "array")}
    out = dict(args)
    for k, v in args.items():
        if isinstance(v, str) and v.lstrip()[:1] in ("[", "{"):
            try:
                out[k] = json.loads(v)
            except json.JSONDecodeError as exc:
                if k not in structured:
                    continue
                # the common slips in long JSON: an object closed with ] (or the reverse), a } left out between the objects
                # of a list, closers missing at the end. The missing } go in before anything is balanced: balancing first
                # would move each one to the end of its list. The first repair that parses is used.
                for repair in (_balance, lambda t: _balance(_reclose(t)), lambda t: _reclose(_balance(t))):
                    try:
                        out[k] = json.loads(repair(v))
                        break
                    except json.JSONDecodeError:
                        pass
                else:
                    near = v[max(0, exc.pos - 80):exc.pos + 20]
                    raise Rejected(f"'{k}' was sent as text that is not valid JSON: {exc.msg} at character {exc.pos}, near ...{near}... "
                                   f"Send '{k}' as a JSON value, not as a string, and check its brackets.") from exc
    return out


def _reclose(text: str, limit: int = 20) -> str:
    """Closes objects a model left open in a list of objects: where the parser meets ``{`` but expects a property name,
    the object before it lacks its ``}``, so one goes before the comma. Each fix moves the error on to the next gap; the
    result is only used when it parses, and the submit validator still checks its shape."""
    for _ in range(limit):
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError as exc:
            comma = text.rfind(",", 0, exc.pos)
            if not exc.msg.startswith("Expecting property name") or not text[exc.pos:].lstrip().startswith("{") or comma < 0:
                return text
            text = text[:comma] + "}" + text[comma:]
    return text


def _balance(text: str) -> str:
    """Inserts the closers a model forgot before a mismatched one, outside strings, and appends any still open. The result is
    only used when it parses, and the submit validator still checks it like any other value."""
    out, stack, in_str, esc = [], [], False, False
    pairs = {"{": "}", "[": "]"}
    for ch in text:
        if in_str:
            esc, in_str = (ch == "\\" and not esc), (in_str if esc or ch != '"' else False)
        elif ch == '"':
            in_str = True
        elif ch in pairs:
            stack.append(pairs[ch])
        elif ch in "]}":
            while stack and stack[-1] != ch and ch in stack:
                out.append(stack.pop())
            if stack and stack[-1] == ch:
                stack.pop()
            else:
                continue  # a closer with nothing open: drop it
        out.append(ch)
    return "".join(out) + "".join(reversed(stack))


def run_agent(
    *,
    role: str,
    chain: str,
    system: str,
    user: str,
    tools: list[Tool],
    submit: Tool,
    log: Callable[[str, str, dict[str, Any]], None],
    max_steps: int = 40,
    max_submits: int = 6,
    temperature: float = 0.2,
    check: Callable[[], None] | None = None,
    add_cost: Callable[[float, int], None] | None = None,
) -> AgentRun:
    run = AgentRun()
    catalog = {t.name: t for t in [*tools, submit]}
    schemas = [t.schema() for t in catalog.values()]
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_reason, repeats = "", 0
    for step in range(max_steps):
        if check:
            check()
        _trim(messages)
        final = step >= max_steps - 3
        if step == max_steps // 2 and run.attempts == 0:
            # the validator's answer is the most useful evidence there is; exploring until the limit wastes the attempt
            messages.append({"role": "user", "content": f"Half of your steps are used. Call {submit.name} now with your best version: the validator replies with exactly what to fix, and you can submit again."})
        if step == max_steps - 3:
            messages.append({"role": "user", "content": f"Step limit reached. Call {submit.name} now with your best result; no other tools are available."})
        try:
            reply = chat(chain, messages, check=check, tools=[submit.schema()] if final else schemas, tool_choice="required" if final else None, temperature=temperature, max_tokens=16_000, role=f"compiler.{role.removesuffix('_repair')}")
        except LLMError as exc:
            raise CompilerAgentError(f"{role}: model unavailable: {exc}", run) from exc
        run.cost_usd += reply.cost_usd
        run.tokens += reply.prompt_tokens + reply.completion_tokens
        if add_cost:
            add_cost(reply.cost_usd, reply.prompt_tokens + reply.completion_tokens)
        messages.append(reply.assistant_message())
        if reply.content.strip():
            log("compiler.note", reply.content.strip()[:400], {"role": role, "model": f"{reply.provider}:{reply.model}"})
        if not reply.tool_calls:
            messages.append({"role": "user", "content": f"Continue using the tools. Finish by calling {submit.name}."})
            continue
        for call in reply.tool_calls:
            if check:
                check()
            run.tool_calls += 1
            tool = catalog.get(call.name)
            if tool is None:
                out: Any = f"error: unknown tool {call.name}"
            elif call.error:
                out = f"error: {call.error}. Send a valid JSON object."
            elif tool is submit:
                run.attempts += 1
                try:
                    run.result = tool.fn(_unstring(call.arguments, tool.parameters))
                    log("compiler.submit.accepted", f"{role} output accepted (attempt {run.attempts})", {"role": role})
                    return run
                except Rejected as exc:
                    key = re.sub(r"\d+", "#", str(exc))[:200]
                    repeats = repeats + 1 if key == re.sub(r"\d+", "#", last_reason)[:200] else 1
                    last_reason = str(exc)
                    if repeats >= STUCK_AFTER:  # more tries would spend budget on the same wall; another attempt would too
                        log("compiler.submit.rejected", str(exc)[:600], {"role": role, "attempt": run.attempts})
                        stuck = CompilerAgentError(f"{role}: the same problem came back {repeats} times in a row; last reason: {exc}", run)
                        stuck.terminal = True
                        raise stuck from exc
                    out = f"REJECTED: {exc}\nFix the problems and call {submit.name} again."
                    log("compiler.submit.rejected", str(exc)[:600], {"role": role, "attempt": run.attempts})
                    if run.attempts >= max_submits:
                        raise CompilerAgentError(f"{role}: output rejected {run.attempts} times; last reason: {exc}", run) from exc
            else:
                try:
                    out = tool.fn(call.arguments)
                except Exception as exc:  # noqa: BLE001 - tool errors are observations for the model
                    out = f"error: {exc.__class__.__name__}: {str(exc)[:2000]}"
            text = out if isinstance(out, str) else json.dumps(out, default=str)
            if tool is not None and tool is not submit and not call.error:
                log("compiler.tool", f"{call.name}({_brief(call.arguments)})", {"role": role, "tool": call.name, "args": _short(call.arguments), "result": redact(text[:600])})
            if len(text) > RESULT_LIMIT:
                text = text[:RESULT_LIMIT] + f"\n...[truncated {len(text) - RESULT_LIMIT} chars; narrow the request]"
            messages.append({"role": "tool", "tool_call_id": call.id, "content": text})
            run.transcript_tail = (run.transcript_tail + [f"{call.name}: {text[:200]}"])[-10:]
    raise CompilerAgentError(f"{role}: step limit reached without an accepted {submit.name}" + (f"; last reason: {last_reason}" if last_reason else ""), run)


def _short(args: dict[str, Any]) -> dict[str, Any]:
    """Redacted arguments with long values clipped, for human-readable event logs."""
    safe = redact_any(args)
    return {k: (v[:160] if isinstance(v, str) else json.dumps(v, default=str)[:160] if isinstance(v, (dict, list)) else v) for k, v in safe.items()}


def _brief(args: dict[str, Any]) -> str:
    text = json.dumps(redact_any(args), default=str)
    return redact(text[:160] + ("..." if len(text) > 160 else ""))
