"""LLM control checks and usage retention, without providers or real sleeps."""

from types import SimpleNamespace as NS

import httpx
import openai
import pytest

from rehearsal.agents import llm


class Stopped(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def isolated_client(monkeypatch):
    monkeypatch.setattr(llm, "_billing_blocked", {})
    monkeypatch.setattr(llm, "_client", lambda _: pytest.fail("unexpected provider access"))


@pytest.fixture
def clock(monkeypatch):
    state = NS(now=0.0, sleeps=[])

    def sleep(seconds):
        state.sleeps.append(seconds)
        state.now += seconds

    monkeypatch.setattr(llm.time, "monotonic", lambda: state.now)
    monkeypatch.setattr(llm.time, "sleep", sleep)
    return state


def response(content="ok"):
    return NS(
        choices=[NS(message=NS(content=content, tool_calls=[]))],
        usage=NS(prompt_tokens=11, completion_tokens=7, cost=0.25),
    )


def client(create):
    return NS(chat=NS(completions=NS(create=create)))


def rate_limit(wait=None):
    resp = httpx.Response(
        429, headers={"retry-after": str(wait)} if wait is not None else {},
        request=httpx.Request("POST", "https://provider.invalid/v1/chat/completions"),
    )
    return openai.RateLimitError("rate limited", response=resp, body=None)


@pytest.mark.parametrize("error_type", [Stopped, llm.LLMError])
def test_check_prevents_initial_attempt(monkeypatch, error_type):
    error = error_type("stop")

    def check():
        raise error

    with pytest.raises(error_type) as caught:
        llm.chat("openai:test", [], check=check)
    assert caught.value is error


@pytest.mark.parametrize("failure", ["unavailable", "status"])
def test_check_before_fallback(monkeypatch, failure):
    events = []

    def create(**kwargs):
        resp = httpx.Response(403, request=httpx.Request("POST", "https://provider.invalid"))
        raise openai.PermissionDeniedError("denied", response=resp, body=None)

    def get_client(provider):
        events.append(provider)
        if failure == "unavailable":
            raise llm.LLMError("unavailable")
        return client(create)

    def check():
        events.append("check")
        if events.count("check") == 2:
            raise Stopped("stop")

    monkeypatch.setattr(llm, "_client", get_client)
    with pytest.raises(Stopped):
        llm.chat("openai:first,groq:second", [], check=check)
    assert events == ["check", "openai", "check"]


@pytest.mark.parametrize("wait", [None, 0.4, 2.5, 20])
def test_retry_sleep_interruptible(monkeypatch, clock, wait):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        raise rate_limit(wait)

    def check():
        if clock.now > 0:
            raise Stopped("stop")

    monkeypatch.setattr(llm, "_client", lambda _: client(create))
    with pytest.raises(Stopped):
        llm.chat("openai:test", [], check=check)
    assert len(calls) == 1
    assert clock.sleeps == [0.4 if wait == 0.4 else 1.0]


@pytest.mark.parametrize("wait", [None, 2.5, 20])
def test_retries_preserve_wait_and_check_each_attempt(monkeypatch, clock, wait):
    events = []
    checks = []

    def create(**kwargs):
        events.append((clock.now, len(checks)))
        if len(events) == 1:
            raise rate_limit(wait)
        return response()

    def check():
        checks.append(clock.now)

    monkeypatch.setattr(llm, "_client", lambda _: client(create))
    reply = llm.chat("openai:test", [], check=check)
    delay = 3 if wait is None else wait
    assert clock.now == delay
    assert max(clock.sleeps) <= 1
    assert len(events) == 2
    assert checks[events[0][1] - 1] == 0
    assert checks[events[1][1] - 1] == delay
    assert reply.attempts == ["openai:test RateLimitError"]
    assert (reply.prompt_tokens, reply.completion_tokens, reply.cost_usd) == (11, 7, 0.25)


def test_default_sleep_unchanged(monkeypatch, clock):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise rate_limit()
        return response()

    monkeypatch.setattr(llm, "_client", lambda _: client(create))
    assert llm.chat("openai:test", []).content == "ok"
    assert clock.sleeps == [3]
    assert calls[0] == calls[1] == {
        "model": "test", "messages": [], "temperature": 0.2, "max_tokens": 4096,
    }


@pytest.mark.parametrize("content", ["no object", '{"broken":'])
def test_json_error_retains_complete_reply(monkeypatch, content):
    reply = llm.LLMReply(content, [], "openai", "test", 11, 7, 0.25, ["prior attempt"])
    check = lambda: None

    def chat(chain, messages, **kwargs):
        assert kwargs["check"] is check
        assert kwargs["response_json"] is True
        return reply

    monkeypatch.setattr(llm, "chat", chat)
    with pytest.raises(llm.LLMError, match="model returned") as caught:
        llm.chat_json("openai:test", [], check=check)
    assert caught.value.reply is reply
    assert (caught.value.reply.prompt_tokens, caught.value.reply.completion_tokens) == (11, 7)
    assert caught.value.reply.cost_usd == 0.25
    assert caught.value.reply.attempts == ["prior attempt"]
    assert isinstance(caught.value.__cause__, ValueError) == content.startswith("{")


def test_json_success_and_control_forwarding(monkeypatch):
    checks = []
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return response('```json\n{"ok": true}\n```')

    monkeypatch.setattr(llm, "_client", lambda _: client(create))
    data, reply = llm.chat_json("openai:test", [], check=lambda: checks.append("check"))
    assert data == {"ok": True}
    assert reply.cost_usd == 0.25
    assert checks == ["check"]
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert llm.LLMError("unavailable").reply is None
