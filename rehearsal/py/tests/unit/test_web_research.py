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


def test_the_builder_can_look_up_documented_commands_only_with_a_key(monkeypatch, tmp_path):
    from rehearsal.compiler.pipeline import AppInput, Compiler
    c = Compiler(app=AppInput("app", tmp_path, {}, "", {}), checkpoint={}, workdir=tmp_path / "b", chain="local:m",
                 log=lambda *a: None, save=lambda *a: None, heartbeat=lambda: None, add_cost=lambda *a: None)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert c._docs_tools() == []
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    assert [t.name for t in c._docs_tools()] == ["web_search", "read_page"]
    assert "(15)" in c._builder_system() and "official documentation" in c._builder_system()


def test_research_that_cannot_finish_skips_instead_of_failing_the_build(monkeypatch, tmp_path):
    from rehearsal.compiler.agent import AgentRun, CompilerAgentError
    from rehearsal.compiler.pipeline import AppInput, Compiler

    c = Compiler(app=AppInput("internal", tmp_path, {}, "", {}), checkpoint={"inspection": {"summary": "an internal tool"}},
                 workdir=tmp_path / "build", chain="local:m", log=lambda *a: None, save=lambda *a: None, heartbeat=lambda: None, add_cost=lambda *a: None)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    def stuck(**kw):  # an app with almost nothing on the web: the brief never reaches five real requests
        raise CompilerAgentError("researcher: the same problem came back 3 times in a row", AgentRun())

    c.agent = stuck
    c.phase_research()
    assert "skipped" in c.ck["research"] and web.digest(c.ck["research"]) == ""


def test_a_repeated_error_is_looked_up_once_with_its_telling_line(tmp_path, monkeypatch):
    """The second time a kind of error comes back in a step, the compiler searches the web for it itself; the fix for a
    setup error is usually written down, and the model should not have to think to look."""
    from rehearsal.compiler import pipeline, web
    from rehearsal.compiler.pipeline import AppInput, Compiler

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    asked = []
    monkeypatch.setattr(web, "search", lambda q, add_cost=None, max_results=6, include_domains=None: asked.append(q) or
                        [{"title": "Install with Docker", "url": "https://docs.gitea.com/installation/install-with-docker", "content": "set INSTALL_LOCK"}])
    c = Compiler(app=AppInput("gitea", tmp_path, {}, "", {}), checkpoint={"done": []}, workdir=tmp_path / "b", chain="local:m",
                 log=lambda *a: None, save=lambda d: None, heartbeat=lambda: None, add_cost=lambda *a: None)
    c._phase = "seed"
    error = ("seed step 0 (exec [...]) failed: exit 1: 2026/10/27 22:46:59 modules/setting/setting.go:108:MustInstalled() [F] Unable to load "
             "config file for a installed Gitea instance")
    c.log("compiler.submit.rejected", error, {"role": "seeder"})
    assert c._web_advice(error) == ""  # once is not a pattern
    c.log("compiler.submit.rejected", error, {"role": "seeder"})
    advice = c._web_advice(error)
    assert "docs.gitea.com/installation/install-with-docker" in advice and "untrusted" in advice
    assert asked == ["gitea modules/setting/setting.go:108:MustInstalled() [F] Unable to load config file for a installed Gitea instance"]
    assert c._web_advice(error) == ""  # one lookup per kind
    assert c._web_advice("one-shot setup exited 1: missing --config", repeats=2)  # runtime starts pass their own count
    monkeypatch.delenv("TAVILY_API_KEY")
    assert c._web_advice("anything else", repeats=5) == ""  # no key, no lookups


def test_setup_notes_come_from_the_apps_own_docs_site(tmp_path, monkeypatch):
    from rehearsal.compiler import web
    from rehearsal.compiler.pipeline import AppInput, Compiler

    (tmp_path / "README.md").write_text("Docs: https://docs.gitea.com/ . Build: https://github.com/go-gitea/gitea ![](https://img.shields.io/x)")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    seen = {}

    def search(q, add_cost=None, max_results=6, include_domains=None):
        seen["domains"] = include_domains
        return [{"title": "Docker", "url": "https://docs.gitea.com/installation/install-with-docker", "content": "..."},
                {"title": "Config cheat sheet", "url": "https://docs.gitea.com/administration/config-cheat-sheet", "content": "INSTALL_LOCK"}]

    monkeypatch.setattr(web, "search", search)
    monkeypatch.setattr(web, "extract", lambda url, focus=None, add_cost=None: {"url": url, "text": "GITEA__security__INSTALL_LOCK=true skips the installer"})
    c = Compiler(app=AppInput("gitea", tmp_path, {}, "", {}), checkpoint={"done": []}, workdir=tmp_path / "b", chain="local:m",
                 log=lambda *a: None, save=lambda d: None, heartbeat=lambda: None, add_cost=lambda *a: None)
    notes = c._setup_notes()
    assert seen["domains"] == ["docs.gitea.com"] and "INSTALL_LOCK=true skips the installer" in notes and "config-cheat-sheet" in notes
    monkeypatch.setattr(web, "search", lambda *a, **k: (_ for _ in ()).throw(AssertionError("read once")))
    assert c._setup_notes() == notes  # kept in the checkpoint
