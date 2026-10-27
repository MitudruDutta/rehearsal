"""Rehearsing an agent that runs somewhere else, by its URL.

An agent profile can name the OpenAI-compatible endpoint of the user's own agent (their framework, their prompts, their
model) instead of a model. Each turn, the episode sends that endpoint the conversation and the offered tools, exactly as
it would send a model, and the agent answers with one tool call. Rehearsal pays nothing for those calls.

The URL comes from a user, and the worker that calls it sits inside the server's network, so an address that resolves to a
private, loopback, link-local or otherwise internal network (a cloud metadata service, the database) is refused, when the
profile is created and again before every call. A server of your own can allow private addresses with
REHEARSAL_ALLOW_PRIVATE_AGENT_URLS. The endpoint's API key is stored sealed (encrypted with the server's session secret)
as a workspace credential; the profile keeps only the credential's id.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import socket
import time
from typing import Any, Callable
from urllib.parse import urlparse

from ..config import settings


class EndpointError(Exception):
    pass


def url_problem(url: str) -> str | None:
    """Why an agent URL may not be called, or None."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "give the agent's URL as http(s)://host/path"
    if parsed.username or parsed.password:
        return "put the API key in the key field, not in the URL"
    if settings().allow_private_agent_urls:
        return None
    if parsed.scheme != "https":
        return "the agent's URL must use https"
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        return f"{parsed.hostname} does not resolve"
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if not ip.is_global or ip.is_multicast:
            return f"{parsed.hostname} resolves to a private or internal address ({ip}); the agent must be reachable on the public internet"
    return None


def _fernet() -> Any:
    from cryptography.fernet import Fernet  # a server dependency (through pyjwt[crypto]); the client package never seals keys

    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"agent-endpoint-key:{settings().session_secret}".encode()).digest()))


def seal(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def unseal(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


_clients: dict[str, Any] = {}


def chat_endpoint(url: str, model: str, key: str | None, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None,
                  temperature: float, max_tokens: int, check: Callable[[], None] | None = None, role: str | None = None) -> Any:
    """One turn of the user's agent. Returns an LLMReply, like a model call, priced at nothing."""
    import httpx
    import openai

    from . import llm

    if problem := url_problem(url):
        raise EndpointError(problem)
    if check is not None:
        check()
    cache = hashlib.sha256(f"{url}\0{key or ''}".encode()).hexdigest()
    if cache not in _clients:
        _clients[cache] = openai.OpenAI(base_url=url.rstrip("/"), api_key=key or "none", timeout=httpx.Timeout(180.0, connect=10.0), max_retries=1)
    kwargs: dict[str, Any] = {"model": model or "agent", "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if tools:
        kwargs |= {"tools": tools, "tool_choice": "auto"}
    started = time.perf_counter()
    try:
        resp = _clients[cache].chat.completions.create(**kwargs)
    except openai.APIStatusError as exc:
        raise EndpointError(f"your agent answered HTTP {exc.status_code}: {str(exc)[:300]}") from exc
    except openai.APIError as exc:
        raise EndpointError(f"your agent did not answer: {exc.__class__.__name__}") from exc
    if not resp.choices:
        raise EndpointError("your agent returned no choices")
    choice = resp.choices[0].message
    calls = []
    for tc in choice.tool_calls or []:
        args, err = llm._loads(tc.function.arguments or "")
        calls.append(llm.ToolCall(tc.id or f"call_{len(calls)}", tc.function.name, args, tc.function.arguments or "", err))
    usage = resp.usage
    reply = llm.LLMReply(
        content=choice.content or "", tool_calls=calls, provider="endpoint", model=model or "agent",
        prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0, completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        cost_usd=0.0, cost_source="your endpoint", raw_tool_calls=[tc.model_dump(exclude_none=True) for tc in choice.tool_calls or []],
        thinking=None, latency_ms=int((time.perf_counter() - started) * 1000),
    )
    llm.record_call(role, f"endpoint:{urlparse(url).hostname}", prompt_tokens=reply.prompt_tokens, completion_tokens=reply.completion_tokens,
                    latency_ms=reply.latency_ms)
    return reply
