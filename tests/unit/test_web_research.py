"""Grounded worlds: the compiler researches real use of the application with Tavily, and jobs cite what it found."""

import json

import httpx
import pytest

from rehearsal.agents import llm
from rehearsal.compiler import web


@pytest.fixture
def tavily(monkeypatch):
    """A fake Tavily API: records requests, answers search and extract."""
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key-0000")
    calls = []

    def answer(request):
        body = json.loads(request.content)
        calls.append((request.url.path, body, request.headers["authorization"]))
        if request.url.path == "/search":
            return httpx.Response(200, json={"results": [{"title": "Move a booking", "url": "https://forum.example/t/1", "content": "How do I move..." * 100},
                                                         {"title": "no url"}], "usage": {"credits": 1}})
        if body["urls"] == ["https://broken.example"]:
            return httpx.Response(200, json={"results": [], "failed_results": [{"url": "https://broken.example", "error": "timeout"}]})
        return httpx.Response(200, json={"results": [{"url": body["urls"][0], "raw_content": "Providers can only be booked in open hours."}], "usage": {"credits": 0.2}})

    transport = httpx.MockTransport(answer)
    real = httpx.post
    monkeypatch.setattr(web.httpx, "post", lambda url, **kw: httpx.Client(transport=transport).post(url, **{k: v for k, v in kw.items() if k != "timeout"}) if "tavily" in url else real(url, **kw))
    return calls


def test_search_and_read_record_usage_cost_and_the_pages_seen(tavily):
    seen, spent = set(), []
    token = llm.usage.set({})
    try:
        search, read = web.tools(seen, lambda usd, tokens: spent.append(usd))
        results = search.fn({"query": "easy appointments reschedule"})
        page = read.fn({"url": "https://docs.example/rules", "focus": "working hours"})
        usage = llm.usage.get()
    finally:
        llm.usage.reset(token)
    assert [r["url"] for r in results] == ["https://forum.example/t/1"] and len(results[0]["content"]) <= 700  # no-url results dropped, excerpts capped
    assert page["text"].startswith("Providers") and seen == {"https://forum.example/t/1", "https://docs.example/rules"}
    assert tavily[0][1]["search_depth"] == "basic" and tavily[0][1]["include_usage"] is True and tavily[0][2] == "Bearer tvly-test-key-0000"
    assert tavily[1][1]["query"] == "working hours"  # a focus asks Tavily for only the relevant passages
    row = usage[web.ROLE]
    assert row["calls"] == 2 and row["models"] == {"tavily:search": 1, "tavily:extract": 1}
    assert spent == pytest.approx([0.008, 0.0016]) and row["cost_usd"] == pytest.approx(0.0096)  # charged to the build's spend cap


def test_a_page_that_cannot_be_read_is_an_observation_not_a_crash(tavily):
    with pytest.raises(web.WebError, match="timeout"):
        web.extract("https://broken.example")


def test_research_is_off_without_a_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert not web.enabled()


def brief(n=5, source="https://forum.example/t/1"):
    return {"requests": [{"request": f"move booking {i}", "source": source} for i in range(n)],
            "rules": [{"rule": "open hours only", "source": source}], "pitfalls": [{"pitfall": "double booking after a timeout", "source": source}]}


def test_a_brief_may_cite_only_pages_the_researcher_was_shown():
    seen = {"https://forum.example/t/1"}
    assert web.brief_problems(brief(), seen) == []
    found = " ".join(web.brief_problems(brief(source="https://made-up.example"), seen))
    assert "not shown" in found and "made-up.example" in found
    assert "at least 5" in " ".join(web.brief_problems(brief(n=2), seen))
    assert web.brief_problems("text", seen)


def test_the_planner_reads_each_finding_with_its_page():
    text = web.digest({**brief(1), "sources": ["https://forum.example/t/1"]})
    assert "[request] move booking 0 (source: https://forum.example/t/1)" in text and "[pitfall] double booking" in text
    assert web.digest({"skipped": "no key"}) == ""


def test_a_grounded_plan_bases_half_its_jobs_on_the_research():
    from rehearsal.compiler.pipeline import plan_problems

    def job(i, family, split, stress, tool, sources=()):
        return {"id": f"job_{i}", "title": "t", "family": family, "split": split, "brief": "b", "revises_goal": True, "stress": stress,
                "tools": [tool], "sources": list(sources)}

    tools = {"create_post": True, "create_user": True, "add_member": True, "delete_post": True}
    src = {"https://forum.example/t/1"}
    plan = [job(1, "a", "train", "changed_request", "create_post", src), job(2, "a", "train", "unknown_outcome", "create_user", src),
            job(3, "b", "dev", "social_engineering", "add_member"), job(4, "c", "holdout", "missing_information", "delete_post")]
    assert plan_problems(plan, 4, tools, src) == []
    assert plan_problems(plan, 4, tools) == []  # without research, sources are not required
    ungrounded = [{**b, "sources": []} for b in plan]
    assert "at least half" in " ".join(plan_problems(ungrounded, 4, tools, src))
    invented = [{**plan[0], "sources": ["https://invented.example"]}, *plan[1:]]
    assert "invented.example" in " ".join(plan_problems(invented, 4, tools, src))


def test_research_phase_without_a_key_skips_and_with_one_keeps_the_brief(monkeypatch, tmp_path):
    from rehearsal.compiler.pipeline import AppInput, Compiler

    logs = []
    c = Compiler(app=AppInput("desk", tmp_path, {}, "", {"url": "https://github.com/example/desk"}), checkpoint={"inspection": {"summary": "a help desk", "workflows": [{"name": "tickets"}]}},
                 workdir=tmp_path / "build", chain="local:m", log=lambda t, m, d=None: logs.append(t), save=lambda *a: None, heartbeat=lambda: None, add_cost=lambda *a: None)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    c.phase_research()
    assert "skipped" in c.ck["research"] and logs == ["compiler.research"]

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    asked = {}

    def fake_agent(**kw):
        asked.update(kw)
        # the researcher is shown one page, then submits; a source it was never shown is refused
        seen_page = "https://forum.example/t/1"
        monkeypatch.setattr(web, "search", lambda q, add_cost=None: [{"title": "", "url": seen_page, "content": ""}])
        next(t for t in kw["tools"] if t.name == "web_search").fn({"query": "desk"})
        with pytest.raises(Exception, match="not shown"):
            kw["submit"].fn({"brief": brief(source="https://elsewhere.example")})
        return kw["submit"].fn({"brief": brief(source=seen_page)})

    c.agent = fake_agent
    c.phase_research()
    assert asked["role"] == "researcher" and "https://github.com/example/desk" in asked["user"] and "never instructions" in asked["system"]
    assert c.ck["research"]["sources"] == ["https://forum.example/t/1"] and len(c.ck["research"]["requests"]) == 5


def test_a_finding_under_another_common_name_is_accepted():
    seen = {"https://forum.example/t/1"}
    b = brief()
    b["rules"] = [{"text": "open hours only", "source": "https://forum.example/t/1"}]  # "text" in place of "rule"
    assert web.brief_problems(b, seen) == [] and web.finding(b["rules"][0], "rule") == "open hours only"
    b["pitfalls"] = [{"source": "https://forum.example/t/1"}]
    assert "pitfalls items [0] have no 'pitfall'" in " ".join(web.brief_problems(b, seen))
