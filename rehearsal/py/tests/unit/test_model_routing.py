"""Model chains: the per-entry reasoning switch, per-role routing in the World Compiler, and per-role usage."""

from types import SimpleNamespace

import pytest

from rehearsal.agents import llm
from rehearsal.compiler import pipeline


def test_reasoning_switch_is_parsed_per_entry():
    assert llm.parse_chain("nebius:nvidia/a#think, nebius:nvidia/b#nothink ,groq:c") == [
        ("nebius", "nvidia/a", True), ("nebius", "nvidia/b", False), ("groq", "c", None)]
    with pytest.raises(llm.LLMError, match="#think or #nothink"):
        llm.parse_chain("nebius:nvidia/a#deep")
    with pytest.raises(llm.LLMError, match="bad model entry"):
        llm.parse_chain("nebius:#think")


class FakeClient:
    def __init__(self, calls):
        self.calls = calls
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content="ok", tool_calls=None)
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


@pytest.fixture
def fake(monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "_client", lambda provider: FakeClient(calls))
    monkeypatch.setattr(llm.pricing, "billing_quote", lambda provider, model: None)
    return calls


def test_thinking_switch_is_sent_only_to_the_flagged_entry(fake):
    llm.chat("nebius:nvidia/n#nothink", [{"role": "user", "content": "hi"}])
    llm.chat("groq:openai/gpt-oss-20b", [{"role": "user", "content": "hi"}])
    assert fake[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert "extra_body" not in fake[1]  # another provider never receives a parameter it may reject


def test_usage_is_collected_per_role_while_a_job_runs(fake):
    acc: dict = {}
    token = llm.usage.set(acc)
    try:
        llm.chat("nebius:nvidia/n#nothink", [{"role": "user", "content": "a"}], role="customer")
        llm.chat("nebius:nvidia/n#nothink", [{"role": "user", "content": "b"}], role="customer")
        llm.chat("nebius:nvidia/s#think", [{"role": "user", "content": "c"}], role="agent")
        llm.chat("nebius:nvidia/s", [{"role": "user", "content": "d"}])  # no role: not counted
    finally:
        llm.usage.reset(token)
    assert acc["customer"]["calls"] == 2 and acc["customer"]["prompt_tokens"] == 20
    assert acc["customer"]["models"] == {"nebius:nvidia/n#nothink": 2}
    assert acc["agent"]["models"] == {"nebius:nvidia/s#think": 1} and set(acc) == {"customer", "agent"}


def test_hard_compiler_roles_run_on_the_reasoner_chain(monkeypatch, tmp_path):
    used = {}

    def run_agent(*, chain, role, **kwargs):
        used[role] = chain
        return SimpleNamespace(result={"ok": True})

    monkeypatch.setattr(pipeline, "run_agent", run_agent)
    c = pipeline.Compiler(app=pipeline.AppInput("app", tmp_path), checkpoint={}, workdir=tmp_path, chain="nebius:super", reasoner="nebius:ultra",
                          log=lambda *a: None, save=lambda ck: None, heartbeat=lambda: None, add_cost=lambda usd, tokens=0: None)
    submit = SimpleNamespace(name="submit", description="", parameters={}, fn=lambda args: args)
    for role in ("inspector", "builder", "scenario_designer", "validation_investigator", "builder_repair"):
        c.agent(role=role, system="", user="", tools=[], submit=submit)
    assert used == {"inspector": "nebius:super", "builder": "nebius:super", "scenario_designer": "nebius:ultra",
                    "validation_investigator": "nebius:ultra", "builder_repair": "nebius:ultra"}


def test_usage_from_several_jobs_adds_up_per_role():
    a = {"agent": {"calls": 2, "prompt_tokens": 10, "completion_tokens": 4, "cost_usd": 0.001, "latency_ms": 900, "models": {"nebius:m#nothink": 2}}}
    b = {"agent": {"calls": 1, "prompt_tokens": 5, "completion_tokens": 2, "cost_usd": 0.0005, "latency_ms": 300, "models": {"nebius:m#nothink": 1}},
         "customer": {"calls": 1, "prompt_tokens": 3, "completion_tokens": 1, "cost_usd": 0.0001, "latency_ms": 100, "models": {"nebius:n#nothink": 1}}}
    merged = llm.merge_usage([a, None, b])
    assert merged["agent"]["calls"] == 3 and merged["agent"]["latency_ms"] == 1200 and merged["agent"]["models"] == {"nebius:m#nothink": 3}
    assert merged["agent"]["cost_usd"] == 0.0015 and set(merged) == {"agent", "customer"}
    assert a["agent"]["calls"] == 2  # the inputs are not changed
