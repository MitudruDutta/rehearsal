"""Compiler charges each reply before tools and stops before another call."""

from unittest.mock import Mock

import pytest

from rehearsal.agents.llm import LLMReply, ToolCall
from rehearsal.compiler.agent import Tool, run_agent
from rehearsal.worker.context import BudgetExceeded


def tool(name, fn):
    return Tool(name, name, {"type": "object", "properties": {}}, fn)


def test_usage_is_accounted_before_submit(monkeypatch):
    charged = []
    def submit(args):
        assert charged == [(0.75, 15)]
        return {"accepted": True}
    call = ToolCall("submit", "submit", {}, "{}")
    monkeypatch.setattr("rehearsal.compiler.agent.chat", lambda *a, **kw: LLMReply("", [call], "local", "m", 10, 5, .75))
    result = run_agent(role="test", chain="local:m", system="s", user="u", tools=[],
                       submit=tool("submit", submit), log=lambda *a: None,
                       check=lambda: None, add_cost=lambda usd, tokens: charged.append((usd, tokens)))
    assert result.result == {"accepted": True}
    assert result.cost_usd == .75


def test_reply_reaching_budget_cannot_dispatch_tools(monkeypatch):
    spent = []
    def check():
        if spent:
            raise BudgetExceeded("budget")
    fn = Mock()
    chat = Mock(return_value=LLMReply("", [ToolCall("work", "work", {}, "{}")], "local", "m", 10, 5, .75))
    monkeypatch.setattr("rehearsal.compiler.agent.chat", chat)
    with pytest.raises(BudgetExceeded):
        run_agent(role="test", chain="local:m", system="s", user="u", tools=[tool("work", fn)],
                  submit=tool("submit", Mock()), log=lambda *a: None, check=check,
                  add_cost=lambda *usage: spent.append(usage))
    fn.assert_not_called()
    chat.assert_called_once()
    assert spent == [(.75, 15)]


def test_cancellation_stops_between_tools_in_one_reply(monkeypatch):
    first, second = Mock(), Mock()
    def check():
        if first.called:
            raise BudgetExceeded("stopped")
    calls = [ToolCall("one", "one", {}, "{}"), ToolCall("two", "two", {}, "{}")]
    monkeypatch.setattr("rehearsal.compiler.agent.chat", Mock(return_value=LLMReply("", calls, "local", "m")))
    with pytest.raises(BudgetExceeded):
        run_agent(role="test", chain="local:m", system="s", user="u", tools=[tool("one", first), tool("two", second)],
                  submit=tool("submit", Mock()), log=lambda *a: None, check=check)
    first.assert_called_once()
    second.assert_not_called()


def test_compiler_uses_owned_destroy_callback(tmp_path):
    from rehearsal.compiler.pipeline import AppInput, Compiler
    from rehearsal.db.queue import LeaseLost
    from types import SimpleNamespace
    inst = SimpleNamespace(destroy=Mock())
    destroy = Mock(side_effect=LeaseLost("replacement owns sandbox"))
    compiler = Compiler(app=AppInput("test", tmp_path, {}, "", {}), checkpoint={},
                        workdir=tmp_path / "build", chain="local:m", log=lambda *a: None,
                        save=lambda *a: None, heartbeat=lambda: None, add_cost=lambda *a: None,
                        destroy=destroy)
    with pytest.raises(LeaseLost):
        compiler.destroy(inst)
    inst.destroy.assert_not_called()


@pytest.mark.parametrize("unsafe", ["..", ".", "../other", "/absolute", "nested/name", "nested\\name", "bad\0name"])
def test_export_file_names_reject_traversal(unsafe):
    from rehearsal.worker.export import _safe_name
    from rehearsal.sdk.examples import _safe_name as example_name
    for check in (_safe_name, example_name):
        with pytest.raises(ValueError):
            check(unsafe)


def test_event_commands_preserve_payload_but_public_data_is_masked():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from rehearsal.db.events import emit, serialize
    session = SimpleNamespace(execute=Mock(), scalar=lambda q: 0, add=Mock(), flush=Mock())
    payload = {"args": {"password": "sandbox-password"}, "actor": "a"}
    event = emit(session, project_id="p", stream="r", type="external.action.submitted", data=payload)
    assert event.data == payload
    event.id = 1
    event.created_at = datetime.now(timezone.utc)
    assert serialize(event)["data"]["args"]["password"] == "[REDACTED]"
    assert event.data["args"]["password"] == "sandbox-password"


def test_role_stops_early_when_the_same_rejection_keeps_coming_back(monkeypatch):
    from rehearsal.compiler.agent import CompilerAgentError, Rejected

    tries = []

    def submit(args):
        tries.append(1)
        raise Rejected(f"get_user as admin -> FAILED: 401 invalid token (try {len(tries)})")

    call = ToolCall("submit", "submit", {}, "{}")
    monkeypatch.setattr("rehearsal.compiler.agent.chat", lambda *a, **kw: LLMReply("", [call], "local", "m", 10, 5, .01))
    with pytest.raises(CompilerAgentError) as stuck:
        run_agent(role="adapter", chain="local:m", system="s", user="u", tools=[], submit=tool("submit", submit),
                  log=lambda *a: None, check=lambda: None, add_cost=lambda usd, tokens: None, max_submits=8)
    assert len(tries) == 3 and stuck.value.terminal and "invalid token" in str(stuck.value)  # 3 tries, not 8; no automatic new attempt


def test_build_goes_back_to_seed_when_adaptation_is_blocked_by_sign_in_errors():
    from types import SimpleNamespace

    from rehearsal.compiler.pipeline import Compiler

    ck = {"done": ["inspect", "plan", "materialize", "discover", "seed"], "seed": {"steps": [{"path": "/login"}], "roles": [{"name": "admin"}], "vars": {"t": "x"}},
          "rejected": {"adapter": {"args": {}, "error": "old"}}}
    c = SimpleNamespace(ck=ck, save=lambda: None, log=lambda *a: None)
    assert Compiler._rewind(c, "adapt", "adapter: the same problem came back 3 times; last reason: get_user -> FAILED 401 invalid token") is True
    assert "seed" not in ck["done"] and "seed" not in ck and "adapter" not in ck["rejected"]
    assert ck["rejected"]["seeder"]["args"]["steps"] == [{"path": "/login"}] and "invalid token" in ck["rejected"]["seeder"]["error"]
    ck["seed"] = {"steps": [], "roles": [], "vars": {}}
    assert Compiler._rewind(c, "adapt", "401 invalid token") is False  # once per build
    assert Compiler._rewind(SimpleNamespace(ck={"seed": {}}, save=None, log=None), "adapt", "you submitted 48 tools; submit between 3 and 40") is False


def _lanes_compiler(monkeypatch, parallel):
    import threading
    from types import SimpleNamespace

    from rehearsal.compiler import pipeline

    monkeypatch.setattr(pipeline, "settings", lambda: SimpleNamespace(build_parallel=parallel))
    made, destroyed = [], []

    def create(*a, **k):
        inst = SimpleNamespace(record=SimpleNamespace(to_json=lambda: {"instance_id": f"lane{len(made)}"}))
        made.append(inst)
        return inst

    monkeypatch.setattr(pipeline.WorldInstance, "create", create)
    c = pipeline.Compiler.__new__(pipeline.Compiler)
    c.ck, c._lock, c._save = {"secrets": {}, "base_snapshot": "/snap"}, threading.RLock(), lambda ck: None
    main = SimpleNamespace(name="main")
    c.instance, c.manifest, c.world_key, c.log = (lambda: main), (lambda: None), (lambda: "k"), (lambda *a: None)
    c.app, c.destroy, c.options = SimpleNamespace(source_dir=None), destroyed.append, pipeline.BuildOptions()
    return c, main, made, destroyed


def test_scenarios_are_checked_several_at_a_time_each_in_its_own_sandbox(monkeypatch):
    import threading

    c, main, made, destroyed = _lanes_compiler(monkeypatch, parallel=3)
    together, seen = threading.Barrier(3, timeout=5), []

    def work(item, sandbox):
        if item < 3:
            together.wait()  # fails unless three scenarios really run at the same time
        seen.append((item, sandbox))

    c._in_parallel(list(range(7)), work, own_sandbox=True)
    assert sorted(i for i, _ in seen) == list(range(7))
    assert len(made) == 2 and {id(s) for _, s in seen} <= {id(main), *map(id, made)}  # main plus two copies
    assert destroyed == made and "lanes" not in c.ck  # copies are always removed


def test_a_stop_in_one_lane_stops_the_others_and_still_cleans_up(monkeypatch):
    c, main, made, destroyed = _lanes_compiler(monkeypatch, parallel=2)
    done = []

    def work(item, sandbox):
        if item == 0:
            raise KeyboardInterrupt("pause requested")
        done.append(item)

    with pytest.raises(KeyboardInterrupt):
        c._in_parallel(list(range(50)), work, own_sandbox=True)
    assert len(done) < 49 and destroyed == made


def test_plan_rules_catch_a_mix_the_writers_cannot_fix_later():
    from rehearsal.compiler.pipeline import plan_problems

    def brief(i, family, split, revises=True, stress="changed_request", tools=("create_post",)):
        return {"id": f"job_{i}", "title": "t", "family": family, "split": split, "brief": "b", "revises_goal": revises, "stress": stress, "tools": list(tools)}

    tools = {"create_post": True, "create_user": True, "add_member": True, "delete_post": True, "get_post": False}
    good = [brief(1, "a", "train", stress="changed_request", tools=["create_post", "get_post"]), brief(2, "a", "train", stress="unknown_outcome", tools=["create_user"]),
            brief(3, "b", "dev", stress="social_engineering", tools=["add_member"]), brief(4, "c", "holdout", stress="missing_information", tools=["delete_post"])]
    assert plan_problems(good, 4, tools) == []
    bad = [brief(1, "a", "train"), brief(1, "a", "dev", False), brief(3, "b", "dev", False), brief(4, "b", "dev", False)]
    found = " ".join(plan_problems(bad, 4))
    for expected in ("duplicate ids", "three families", "more than one split", "no holdout", "revise the goal"):
        assert expected in found


def test_a_plan_must_attack_the_agent_and_spread_over_the_application():
    from rehearsal.compiler.pipeline import plan_problems

    tools = {"create_post": True, "create_user": True, "get_post": False}
    happy = [{"id": f"job_{i}", "title": "t", "family": f"f{i % 3}", "split": ("train", "dev", "holdout")[i % 3], "brief": "b",
              "revises_goal": True, "stress": "changed_request", "tools": ["create_post"]} for i in range(6)]
    found = " ".join(plan_problems(happy, 6, tools))
    for expected in ("unknown_outcome", "an attack", "missing_information", "different stress categories", "data-changing tools"):
        assert expected in found
    happy[0]["tools"] = ["drop_database"]
    assert "do not exist" in " ".join(plan_problems(happy, 6, tools))


def test_written_jobs_must_contain_the_attack_their_category_promises():
    from rehearsal.compiler import stress
    from rehearsal.core.contracts import (ActorSpec, CheckSpec, EventAction, GoalVersion, NegativeTrajectory, ParticipantSpec,
                                          ScenarioSpec, ScheduledEvent, TrajectoryStep, Trigger)

    def job(**over):
        base = dict(id="job_1", title="t", family="f", actors=[ActorSpec(id="agent", role="staff", instructions="i", can_complete=True)],
                    participant=ParticipantSpec(name="C", persona="p", opening_message="hi"), goals=[GoalVersion(version=1, instruction="do", checks=["c"])],
                    checks=[CheckSpec(id="c", description="d", query="SELECT 1")], reference=[TrajectoryStep(actor="agent", tool="create_post", args={})])
        return ScenarioSpec(**{**base, **over})

    assert stress.problems("unknown_outcome", job())  # no timeout fault: not a stress test
    timeout = [ScheduledEvent(id="t", trigger=Trigger(kind="at_step", step=0), actions=[EventAction(kind="fault", tool="create_post", fault_mode="drop_response")])]
    negative = [NegativeTrajectory(name="blind_retry", description="retries", steps=[TrajectoryStep(actor="agent", tool="create_post", args={})])]
    assert stress.problems("unknown_outcome", job(events=timeout, negatives=negative)) == []
    assert "facts" in " ".join(stress.problems("missing_information", job()))
    assert "hard-rule" in " ".join(stress.problems("social_engineering", job()))
    assert stress.problems("injected_instructions", job(constraints=["c"], negatives=negative)) == ["an injected_instructions job needs a setup step that plants the hidden instruction in a record"]
    limited = [ScheduledEvent(id="r", trigger=Trigger(kind="at_step", step=0), actions=[EventAction(kind="fault", tool="create_post", fault_mode="rate_limit")])]
    assert stress.problems("failure_recovery", job(events=limited)) == []


def test_a_build_uses_no_more_lanes_than_its_plan_allows(monkeypatch):
    c, main, made, destroyed = _lanes_compiler(monkeypatch, parallel=4)
    c.options = c.options.__class__(parallel=1)  # free plan: one sandbox
    c._in_parallel(list(range(5)), lambda item, inst: None, own_sandbox=True)
    assert made == []  # one lane uses the main sandbox only


def test_a_restarted_build_gets_new_repairs_and_keeps_the_earlier_errors(tmp_path, monkeypatch):
    """A build that ran out of start attempts used to fail again at once when restarted, with no repair at all."""
    from rehearsal.compiler import pipeline
    from rehearsal.compiler.pipeline import AppInput, BuildFailed, Compiler

    c = Compiler(app=AppInput("test", tmp_path, {}, "", {}), checkpoint={"runtime": {"secrets": []}, "inspection": {},
                 "materialize_attempts": [f"old error {i}" for i in range(5)]},
                 workdir=tmp_path / "build", chain="local:m", log=lambda *a: None, save=lambda *a: None, heartbeat=lambda: None, add_cost=lambda *a: None)
    monkeypatch.setattr(c, "manifest", lambda **kw: None)
    monkeypatch.setattr(pipeline.WorldInstance, "create", classmethod(lambda cls, *a, **kw: (_ for _ in ()).throw(pipeline.RuntimeError_("yarn build failed"))))
    asked = []
    monkeypatch.setattr(c, "agent", lambda **kw: asked.append(kw["user"]) or {"secrets": []})
    with pytest.raises(BuildFailed, match="after 10 attempts"):
        c.phase_materialize()
    assert len(asked) == 4  # four repairs in the new window (the fifth failure ends it)
    assert "old error 0" in asked[0]  # the builder still sees what already failed


@pytest.mark.parametrize("shape", ["wrapped", "unwrapped"])
def test_a_runtime_is_accepted_in_the_shapes_models_send(tmp_path, shape):

    from rehearsal.compiler.pipeline import AppInput, Compiler
    c = Compiler(app=AppInput("test", tmp_path, {"db": "postgres:16@sha256:" + "a" * 64}, "", {}), checkpoint={}, workdir=tmp_path / "b",
                 chain="local:m", log=lambda *a: None, save=lambda *a: None, heartbeat=lambda: None, add_cost=lambda *a: None)
    rt = {"services": [{"name": "app", "build": {"dockerfile_inline": "FROM alpine"}, "port": 80}, {"name": "db", "image": "postgres:16@sha256:" + "a" * 64}],
          "state_probes": [{"service": "db", "kind": "postgres", "database": "x", "user": "u", "password": "p"}]}
    args = {"wrapped": {"runtime": rt}, "unwrapped": rt}[shape]
    out = c._accept_runtime(args)
    assert [s["name"] for s in out["services"]] == ["app", "db"] and out["state_probes"][0]["kind"] == "postgres"


def test_repairs_start_from_the_runtime_that_got_furthest(tmp_path, monkeypatch):
    """A repair that broke an image which already built must be shown the version that worked, not only the latest."""
    from rehearsal.compiler import pipeline
    from rehearsal.compiler.pipeline import AppInput, BuildFailed, Compiler

    c = Compiler(app=AppInput("test", tmp_path, {}, "", {}), checkpoint={"runtime": {"secrets": [], "v": "a"}, "inspection": {}},
                 workdir=tmp_path / "build", chain="local:m", log=lambda *a: None, save=lambda *a: None, heartbeat=lambda: None, add_cost=lambda *a: None)
    monkeypatch.setattr(c, "manifest", lambda **kw: None)
    errors = iter(["one-shot migrate exited 1: Cannot find module", "image build for app failed: install broke", *["image build for app failed"] * 5])
    monkeypatch.setattr(pipeline.WorldInstance, "create", classmethod(lambda cls, *a, **kw: (_ for _ in ()).throw(pipeline.RuntimeError_(next(errors)))))
    asked, versions = [], iter("bcdefg")
    monkeypatch.setattr(c, "agent", lambda **kw: asked.append(kw["user"]) or {"secrets": [], "v": next(versions)})
    with pytest.raises(BuildFailed):
        c.phase_materialize()
    assert "got furthest" not in asked[0]  # the furthest runtime is the current one: nothing to compare yet
    assert "Attempt 1 got furthest" in asked[1] and '"v": "a"' in asked[1]  # runtime "a" built its images; "b" broke the build
    assert c.ck["materialize_furthest"]["attempt"] == 1


def test_json_text_is_parsed_and_broken_json_text_is_refused_with_the_reason():
    import json

    from rehearsal.compiler.agent import Rejected, _unstring
    assert _unstring({"runtime": json.dumps({"services": []})}) == {"runtime": {"services": []}}
    with pytest.raises(Rejected, match=r"not valid JSON: Expecting ',' delimiter at character \d+.*check its brackets"):
        _unstring({"runtime": '{"services": [] "state_probes": []}'}, {"properties": {"runtime": {"type": "object"}}})  # a missing comma
    assert _unstring({"note": "[draft] plain text"}, {"properties": {"note": {"type": "string"}}}) == {"note": "[draft] plain text"}


def test_copying_a_folder_into_the_working_directory_is_caught_before_building(tmp_path):
    from rehearsal.compiler.pipeline import copy_problems
    (tmp_path / ".yarn" / "releases").mkdir(parents=True)
    (tmp_path / "package.json").write_text("{}")
    found = copy_problems("FROM node:22\nWORKDIR /app\nCOPY package.json yarn.lock .yarn/ .\nRUN yarn install", tmp_path)
    assert len(found) == 1 and "COPY .yarn ./.yarn" in found[0]
    fine = "FROM node:22\nCOPY . .\nCOPY .yarn ./.yarn\nCOPY package.json .\nCOPY --from=build /out .\nRUN true"
    assert copy_problems(fine, tmp_path) == []


def test_a_bracket_slip_in_long_json_is_balanced_once_and_still_validated():
    import json

    from rehearsal.compiler.agent import _balance, _unstring
    slip = '{"services": [{"name": "app"}], "state_probes": [{"service": "db", "password": "{{secret.X}}"]}'  # } missing before ]
    assert json.loads(_balance(slip)) == {"services": [{"name": "app"}], "state_probes": [{"service": "db", "password": "{{secret.X}}"}]}
    assert _unstring({"runtime": slip}, {"properties": {"runtime": {"type": "object"}}})["runtime"]["state_probes"][0]["service"] == "db"
    assert _balance('{"a": "brackets ] } inside a string"}') == '{"a": "brackets ] } inside a string"}'


def test_objects_left_open_in_a_list_are_closed_where_they_end():
    """The slip seen building Saleor: a service's } left out in the middle of the list, with more keys after the list.
    Balancing alone would put the } at the end of the list and swallow the services after it."""
    import json

    from rehearsal.compiler.agent import _unstring
    runtime = {"services": [{"name": "api", "env": {"URL": "http://api.world.test:8000, x"}}, {"name": "db", "image": "postgres"},
                            {"name": "redis", "image": "redis"}], "secrets": ["DB_PASSWORD"], "state_probes": [{"service": "db"}]}
    text = json.dumps(runtime)
    schema = {"properties": {"runtime": {"type": "object"}}}
    one = text.replace('8000, x"}}, {', '8000, x"}, {')  # api's } left out after a nested object
    two = one.replace('"postgres"}, {', '"postgres", {')  # and db's
    for slip in (one, two, two[:-2]):  # also cut off at the end
        assert slip != text and _unstring({"runtime": slip}, schema)["runtime"] == runtime


def test_a_flattening_copy_is_allowed_when_a_later_line_restores_the_folder(tmp_path):
    from rehearsal.compiler.pipeline import copy_problems
    (tmp_path / ".yarn" / "releases").mkdir(parents=True)
    furthest = "FROM node:22\nCOPY package.json .yarnrc.yml .yarn/ .\nCOPY .yarn/releases .yarn/releases\nRUN yarn install"
    assert copy_problems(furthest, tmp_path) == []
    assert copy_problems("FROM node:22\nCOPY .yarn/ .\nCOPY . .\nRUN true", tmp_path) == []
    assert len(copy_problems("FROM node:22\nCOPY .yarn/ .\nRUN yarn install", tmp_path)) == 1


def test_a_repair_that_leaves_the_failing_service_unchanged_is_refused(tmp_path, monkeypatch):
    from rehearsal.compiler import pipeline
    from rehearsal.compiler.pipeline import AppInput, Compiler, failing_service

    assert failing_service("service celery_worker exited during startup (killed for exceeding its 1g memory limit ...)") == "celery_worker"
    assert failing_service("one-shot migrate did not finish within 240 s") == "migrate"
    assert failing_service("image build for app failed") is None

    worker = {"name": "worker", "image": "app@sha256:" + "a" * 64, "command": ["celery", "worker"]}
    web = {"name": "web", "image": "app@sha256:" + "a" * 64, "port": 8000}
    db = {"name": "db", "image": "postgres@sha256:" + "b" * 64}
    probes = [{"service": "db", "kind": "postgres", "database": "x", "user": "u", "password": "p"}]
    c = Compiler(app=AppInput("t", tmp_path, {"app": worker["image"], "db": db["image"]}, "", {}),
                 checkpoint={"runtime": {"services": [worker, web, db], "secrets": [], "state_probes": probes}, "inspection": {}},
                 workdir=tmp_path / "b", chain="local:m", log=lambda *a: None, save=lambda *a: None, heartbeat=lambda: None, add_cost=lambda *a: None)
    monkeypatch.setattr(c, "manifest", lambda **kw: None)
    errors = iter(["service worker exited during startup (killed for exceeding its 1g memory limit)"] + ["image build for x failed"] * 9)
    monkeypatch.setattr(pipeline.WorldInstance, "create", classmethod(lambda cls, *a, **kw: (_ for _ in ()).throw(pipeline.RuntimeError_(next(errors)))))
    outcomes = []

    def agent(**kw):
        unchanged = {"runtime": {"services": [worker, web, db], "state_probes": probes}}
        try:
            kw["submit"].fn(unchanged)
        except pipeline.Rejected as exc:
            outcomes.append(str(exc))
        fixed = {**worker, "command": ["celery", "worker", "--concurrency", "2"]}
        return kw["submit"].fn({"runtime": {"services": [fixed, web, db], "state_probes": probes}})

    monkeypatch.setattr(c, "agent", agent)
    with pytest.raises(pipeline.BuildFailed):
        c.phase_materialize()
    assert "service worker is the one that failed, and it is unchanged" in outcomes[0]


def test_a_host_check_refusal_sends_the_build_back_to_the_runtime_with_the_real_host_names(tmp_path, monkeypatch):
    """The seeder cannot change which hosts an application accepts; the runtime can, so the build goes back there."""
    from rehearsal.compiler import pipeline
    from rehearsal.compiler.pipeline import AppInput, Compiler

    destroyed = []
    c = Compiler(app=AppInput("t", tmp_path, {}, "", {}),
                 checkpoint={"done": ["inspect", "research", "plan", "materialize", "discover"], "runtime": {"secrets": [], "services": [{"name": "db"}, {"name": "web_api", "port": 8000}]},
                             "inspection": {}, "instance": None, "api": {}, "clean_snapshot": "x"},
                 workdir=tmp_path / "b", chain="local:m", log=lambda *a: None, save=lambda *a: None, heartbeat=lambda: None, add_cost=lambda *a: None)
    c._inst = object()
    monkeypatch.setattr(c, "destroy", lambda inst: destroyed.append(inst))
    django = "seed step 4 (http POST /graphql/) failed: HTTP 400: <title>DisallowedHost at /graphql/</title>"
    assert c._rewind("seed", django) is True
    assert c.ck["done"] == ["inspect", "research", "plan"] and "api" not in c.ck and "clean_snapshot" not in c.ck and len(destroyed) == 1
    assert c._rewind("seed", django) is True  # a first repair can change the wrong setting
    assert c._rewind("seed", django) is False  # at most twice per build
    assert c._rewind("seed", "HTTP 500 server error") is False  # only the host check sends it back

    asked = []
    monkeypatch.setattr(c, "manifest", lambda **kw: None)
    monkeypatch.setattr(pipeline.WorldInstance, "create", classmethod(lambda cls, *a, **kw: (_ for _ in ()).throw(pipeline.RuntimeError_("image build for x failed"))))
    monkeypatch.setattr(c, "agent", lambda **kw: asked.append(kw["user"]) or {"secrets": [], "services": []})
    with pytest.raises(pipeline.BuildFailed):
        c.phase_materialize()
    assert "refused Rehearsal's requests in the seed step" in asked[0] and "DisallowedHost" in asked[0]
    assert "Host headers web-api:8000" in asked[0] and "hostnames web-api, web-api.world.test" in asked[0]


def test_an_html_error_page_is_reported_as_its_visible_text():
    from rehearsal.runner.seed import readable

    page = ("<!DOCTYPE html><html><head><title>DisallowedHost at /graphql/</title><style>" + "body { color:#000; }" * 200 +
            "</style></head><body><pre class=\"exception_value\">Invalid HTTP_HOST header: &#x27;saleor:8000&#x27;. You may need to add "
            "&#x27;saleor&#x27; to ALLOWED_HOSTS.</pre></body></html>")
    text = readable(page)
    assert text.startswith("DisallowedHost at /graphql/") and "add 'saleor' to ALLOWED_HOSTS." in text and "color" not in text
    assert readable('{"detail": "bad"}') == '{"detail": "bad"}' and len(readable("x" * 5000)) == 1500


def test_a_save_path_written_as_if_the_response_were_wrapped_gets_the_right_path():
    from rehearsal.runner.seed import _rooted

    response = {"data": {"tokenCreate": {"token": "t", "errors": []}}, "extensions": {}}
    assert _rooted(response, "json.body.data.tokenCreate.token") == "data.tokenCreate.token"
    assert _rooted(response, "$.body.data.tokenCreate.errors[0]") is None  # nothing to find: no suggestion
    assert _rooted(response, "data.missing") is None


def test_a_host_check_is_found_when_the_sandbox_starts_not_after_seeding(tmp_path, monkeypatch):
    """One request right after the runtime starts finds a framework's host check, so the runtime is repaired before
    API discovery and seeding are spent on an application that refuses every request."""
    from types import SimpleNamespace

    from rehearsal.compiler import pipeline
    from rehearsal.compiler.pipeline import AppInput, Compiler

    destroyed, asked = [], []
    c = Compiler(app=AppInput("t", tmp_path, {}, "", {}),
                 checkpoint={"done": ["inspect", "research", "plan"], "inspection": {},
                             "runtime": {"secrets": [], "services": [{"name": "db"}, {"name": "shop", "port": 8000}]}},
                 workdir=tmp_path / "b", chain="local:m", log=lambda *a: None, save=lambda *a: None, heartbeat=lambda: None, add_cost=lambda *a: None,
                 destroy=lambda inst: destroyed.append(inst))
    page = ("<html><head><title>DisallowedHost at /</title><style>body{}</style></head><body>Invalid HTTP_HOST header: "
            "'shop.world.test:8000'. You may need to add 'shop.world.test' to ALLOWED_HOSTS.</body></html>")
    answers = iter([SimpleNamespace(status_code=400, text=page), SimpleNamespace(status_code=200, text="<html>shop</html>")])

    def create(cls, *a, **kw):
        inst = SimpleNamespace(manifest=SimpleNamespace(services=[SimpleNamespace(name="db", port=None), SimpleNamespace(name="shop", port=8000)]),
                               http=lambda *a, **kw: next(answers), record=SimpleNamespace(to_json=lambda: {}), snapshot=lambda path: None)
        return inst

    monkeypatch.setattr(c, "manifest", lambda **kw: None)
    monkeypatch.setattr(pipeline.WorldInstance, "create", classmethod(create))
    monkeypatch.setattr(c, "agent", lambda **kw: asked.append(kw["user"]) or c.ck["runtime"])
    c.phase_materialize()
    assert len(destroyed) == 1 and len(asked) == 1  # the refusing sandbox is torn down, the builder repairs once
    assert "GET / on shop answered HTTP 400" in asked[0] and "add 'shop.world.test' to ALLOWED_HOSTS" in asked[0]
    assert "Host headers shop.world.test:8000" in asked[0] and "style" not in asked[0].split("Earlier failed")[0]
    assert c.ck["instance"] == {}


def test_a_long_rejection_keeps_its_reason_in_the_build_log():
    from rehearsal.compiler.agent import _excerpt

    text = "seed step 0 (exec manage.py) failed: exit 1: " + "WARNING noisy\n" * 200 + "TypeError: create_user() missing 1 required argument: 'password'"
    out = _excerpt(text)
    assert out.startswith("seed step 0 (exec manage.py) failed") and out.endswith("missing 1 required argument: 'password'") and len(out) <= 603
    assert _excerpt("short") == "short"


def test_tools_text_with_line_breaks_in_a_query_and_a_missing_brace_is_still_read():
    """Multi-line GraphQL queries arrive with raw line breaks inside JSON strings; together with a } left out after a
    nested example, that defeated the repair and the adapter was refused until the build stopped."""
    from rehearsal.compiler.agent import Rejected, _unstring

    q = "mutation($input: ProductCreateInput!) {\n  productCreate(input: $input) { product { id } }\n}"
    one = '{"name": "create_product", "graphql": {"query": "%s", "example_args": {"input": {"name": "Sample", "productTypeId": "U::2"}}}' % q
    two = '{"name": "update_product", "graphql": {"query": "%s"}, "example_args": {"id": "U::3"}}' % q
    tools = _unstring({"tools": f"[{one}, {two}]"}, {"properties": {"tools": {"type": "array"}}})["tools"]
    assert [t["name"] for t in tools] == ["create_product", "update_product"] and "\n" in tools[1]["graphql"]["query"]
    with pytest.raises(Rejected) as refused:
        _unstring({"tools": '[{"name": "x" "y"}]'}, {"properties": {"tools": {"type": "array"}}})
    assert refused.value.data == {"text": '[{"name": "x" "y"}]'}  # kept for the build log


def test_tools_text_from_a_real_build_with_both_kinds_of_missing_brace_is_read():
    """Shaped like the Saleor adapter's text: each tool lacks its own }, and one variable's schema lacks the } before
    the ] that ends its list. Both are closed where they belong, in one pass."""
    from rehearsal.compiler.agent import _unstring

    var = '{"name": "input", "schema": {"type": "object", "properties": {"ids": {"type": "array", "items": {"type": "string"}}}}'
    tool = ('{"name": "%s", "service": "saleor", "graphql": {"document": "mutation { x }", "mutating": true, '
            '"variables": [%s], "example_args": {"input": {"ids": ["U::1"]}}}')
    text = "[" + ", ".join([tool % ("one", var + "}"), tool % ("two", var), tool % ("three", var + "}")]) + "}]"
    tools = _unstring({"tools": text}, {"properties": {"tools": {"type": "array"}}})["tools"]
    assert [t["name"] for t in tools] == ["one", "two", "three"]
    assert all(t["graphql"]["variables"][0]["schema"]["properties"]["ids"]["items"] == {"type": "string"} for t in tools)


def test_a_graphql_tools_example_is_read_where_a_missing_brace_put_it():
    from rehearsal.compiler.pipeline import _example_args

    assert _example_args({"graphql": {"document": "q"}, "example_args": {"id": "1"}}) == {"id": "1"}
    assert _example_args({"graphql": {"document": "q", "example_args": {"input": {"name": "x"}}}}) == {"input": {"name": "x"}}
    assert _example_args({"method": "GET", "path": "/x"}) == {}


def test_one_brace_too_many_inside_a_list_of_tool_variables_is_removed():
    """From the same build: a variable's schema closed with one } too many, so its "required" and "description" landed
    in the list of variables."""
    from rehearsal.compiler.agent import _unstring

    var = '{"name": "input", "schema": {"type": "object", "properties": {"name": {"type": "string"}}}}, "required": true, "description": "Product input"}'
    text = '[{"name": "create_product", "graphql": {"document": "mutation { x }", "variables": [%s]}, "example_args": {"input": {"name": "A"}}}]' % var
    tool = _unstring({"tools": text}, {"properties": {"tools": {"type": "array"}}})["tools"][0]
    assert tool["graphql"]["variables"][0] == {"name": "input", "schema": {"type": "object", "properties": {"name": {"type": "string"}}},
                                               "required": True, "description": "Product input"}


def test_build_goes_back_to_seed_when_tool_examples_find_no_records():
    """The Saleor seed made only accounts and tokens, so every example call used an invented id and failed."""
    from types import SimpleNamespace

    from rehearsal.compiler.pipeline import Compiler

    ck = {"done": ["inspect", "plan", "materialize", "discover", "seed"], "seed": {"steps": [{"path": "/graphql/"}], "roles": [{"name": "admin"}], "vars": {}},
          "rejected": {}}
    logged = []
    c = SimpleNamespace(ck=ck, save=lambda: None, log=lambda *a: logged.append(a[1]))
    reason = 'adapter: output rejected 8 times; last reason: product_update -> FAILED: {"errors": [{"field": "id", "message": "Invalid ID: Product:U:1. Expected: Product."}]}'
    assert Compiler._rewind(c, "adapt", reason) is True
    assert "seed" not in ck["done"] and "found no records to act on" in ck["rejected"]["seeder"]["error"]
    assert "records the seed never created" in logged[0]


def test_stack_traces_are_left_out_of_error_bodies():
    from rehearsal.runner.gateway import graphql_failed, without_traces

    body = {"errors": [{"message": "Unknown type \"RefundCreateInput\".", "extensions": {"exception": {"code": "GraphQLError", "stacktrace": ["Traceback"] * 50}}}]}
    assert without_traces(body) == {"errors": [{"message": "Unknown type \"RefundCreateInput\".", "extensions": {"exception": {"code": "GraphQLError"}}}]}
    assert "Traceback" not in graphql_failed(body) and "RefundCreateInput" in graphql_failed(body)


def test_tools_are_verified_one_at_a_time_and_survive_a_resume(tmp_path, monkeypatch):
    """A broken tool costs one add_tool call, not the whole set; verified tools are kept in the checkpoint, so a
    resumed adapter starts from them; submit_tools with {} submits them."""
    from types import SimpleNamespace

    from rehearsal.compiler import pipeline
    from rehearsal.compiler.agent import Rejected
    from rehearsal.compiler.pipeline import AppInput, Compiler

    ck = {"done": ["inspect", "research", "plan", "materialize", "discover", "seed"], "inspection": {"workflows": []},
          "runtime": {"secrets": [], "services": []}, "secrets": {}, "seed": {"roles": [{"name": "admin"}], "vars": {"pid": "P1"}}, "base_snapshot": "x"}
    saved = []
    c = Compiler(app=AppInput("t", tmp_path, {}, "", {}), checkpoint=ck, workdir=tmp_path / "b", chain="local:m",
                 log=lambda *a: None, save=lambda d: saved.append(sorted(d.get("adapt_verified", {}))), heartbeat=lambda: None, add_cost=lambda *a: None)
    inst = SimpleNamespace(restore=lambda path: None)
    monkeypatch.setattr(c, "instance", lambda: inst)
    monkeypatch.setattr(c, "api", lambda: ([], None))
    monkeypatch.setattr(c, "api_summary", lambda: "")
    monkeypatch.setattr(c, "_probe_capabilities", lambda inst, examples: {})
    monkeypatch.setattr(c, "_build_tools", lambda items: [SimpleNamespace(name=it["name"], mutating=bool(it.get("mutating")), roles=["admin"],
                                                                          model_dump=lambda it=it, **kw: {"name": it["name"]}) for it in items])
    monkeypatch.setattr(c, "manifest", lambda **kw: SimpleNamespace(model_copy=lambda update: SimpleNamespace(model_dump=lambda **k: {}, tools=update["tools"])))
    monkeypatch.setattr(pipeline.WorldManifest, "model_validate", staticmethod(lambda d: None))
    monkeypatch.setattr(pipeline, "Prober", lambda inst: None)
    for name in ("api_tools", "schema_tools", "live_tools"):
        monkeypatch.setattr(pipeline, name, lambda *a, **k: [])
    monkeypatch.setattr(pipeline, "role_call_tool", lambda *a, **k: SimpleNamespace(name="call_as_role"))

    class Gateway:
        def __init__(self, *a): pass

        def execute(self, role, name, args, op):
            ok = args.get("id") == "P1"
            return SimpleNamespace(status="SUCCEEDED" if ok else "FAILED", visible={"errors": [{"message": "Invalid ID", "stacktrace": ["x"] * 9}]})

    monkeypatch.setattr(pipeline, "Gateway", Gateway)
    seen = {}

    def agent(**kw):
        add = next(t for t in kw["tools"] if t.name == "add_tool")
        seen["user"] = kw["user"]
        for n in ("get_product", "list_products"):
            assert "verified" in add.fn({"tool": {"name": n, "example_args": {"id": "{{vars.pid}}"}}})
        with pytest.raises(Rejected) as bad:
            add.fn({"tool": '{"name": "update_product", "mutating": true, "example_args": {"id": "U:1"}}'})
        assert "Invalid ID" in str(bad.value) and "stacktrace" not in str(bad.value)
        if len(ck["adapt_verified"]) < 3:  # the first attempt stops here, as if the worker restarted
            raise RuntimeError("worker lost")
        return kw["submit"].fn({})

    monkeypatch.setattr(c, "agent", lambda **kw: agent(**kw))
    with pytest.raises(RuntimeError):
        c.phase_adapt()
    assert sorted(ck["adapt_verified"]) == ["get_product", "list_products"] and saved[-1] == ["get_product", "list_products"]
    ck["adapt_verified"]["delete_product"] = {"name": "delete_product", "mutating": True, "example_args": {"id": "{{vars.pid}}"}}
    c.phase_adapt()  # resumed: the earlier tools are still there, and named in the brief
    assert "Already verified in an earlier attempt" in seen["user"] and "get_product" in seen["user"]
    assert sorted(t["name"] for t in ck["tools"]) == ["delete_product", "get_product", "list_products"]


def test_rejections_group_by_kind_without_their_particulars():
    from rehearsal.compiler.pipeline import rejection_kind

    a = rejection_kind("seed step 4 (http POST /graphql/) failed: HTTP 400: DisallowedHost at /graphql/")
    b = rejection_kind("seed step 6 (http POST /graphql/) failed: HTTP 400: {\"errors\": []}")
    assert a == "seed step 4 (http POST /graphql/) failed" and b == "seed step 6 (http POST /graphql/) failed"  # a later step is progress
    assert rejection_kind("seed step 4 (http POST /graphql/) failed: HTTP 500") == a
    c = rejection_kind("seed step 0 (exec ['python', 'manage.py', 'createsuperuser']) failed: exit 2: usage")
    assert c == "seed step 0 (exec […]) failed"
    j1 = rejection_kind("'tools' was sent as text that is not valid JSON: Expecting ',' delimiter at character 573, near ...")
    j2 = rejection_kind("'tools' was sent as text that is not valid JSON: Expecting property name at character 721")
    assert j1 == j2 == "… was sent as text that is not valid JSON"
    assert rejection_kind("These example calls did not succeed against the seeded state (reads run first):\nproduct_create ...").startswith("These example calls")


def test_a_step_that_keeps_failing_pauses_the_build_and_resuming_grants_another_round(tmp_path):
    """The no-progress brake: the same kind of rejection over and over, or a large share of the budget, pauses the build
    with the reason; spend is kept per step."""
    from rehearsal.compiler.pipeline import GUARD_REPEATS, GUARD_SHARE, AppInput, Compiler, rejection_kind

    paused, logged, costs = [], [], []
    c = Compiler(app=AppInput("t", tmp_path, {}, "", {}), checkpoint={"done": []}, workdir=tmp_path / "b", chain="local:m",
                 log=lambda *a: logged.append(a[0]), save=lambda d: None, heartbeat=lambda: None, add_cost=lambda usd, tokens=0: costs.append(usd),
                 budget=10.0, pause=paused.append)
    c._phase = "adapt"
    for n in range(GUARD_REPEATS - 1):
        c.log("compiler.submit.rejected", f"These example calls did not succeed (attempt {n}):\nx -> FAILED", {"role": "adapter"})
    kind = rejection_kind("These example calls did not succeed (attempt 7):\nx")
    assert not paused and c.ck["stuck"]["adapt"][kind]["count"] == GUARD_REPEATS - 1 and c.ck["stuck"]["adapt"][kind]["role"] == "adapter"
    c.log("compiler.submit.rejected", "These example calls did not succeed (attempt 99):\ny", {"role": "adapter"})
    assert len(paused) == 1 and f"came back {GUARD_REPEATS} times" in paused[0] and "adapt step" in paused[0]
    c.log("compiler.submit.rejected", "These example calls did not succeed (attempt 100):\nz", {"role": "adapter"})
    assert len(paused) == 1  # resuming grants another round before the next pause
    c._phase = "seed"
    c.add_cost(GUARD_SHARE * 10.0 - 0.01)
    assert len(paused) == 1 and c.ck["spend_by_step"]["seed"] == round(GUARD_SHARE * 10.0 - 0.01, 6) and costs
    c.add_cost(0.02)
    assert len(paused) == 2 and "40% of the $10.00 budget" in paused[1]
    assert "compiler.submit.rejected" in logged  # the events still reach the build log


def test_the_seeder_can_send_the_build_back_to_the_runtime_with_its_reason(tmp_path, monkeypatch):
    """Gitea's runtime started without its install lock, so every seed command failed with "run gitea web to install";
    only the runtime can change that. The seeder says so, and the runtime step gets the reason as its first error."""
    from rehearsal.compiler import pipeline
    from rehearsal.compiler.pipeline import AppInput, Compiler, RuntimeChangeNeeded

    ck = {"done": ["inspect", "research", "plan", "materialize", "discover"], "runtime": {"secrets": [], "services": []}, "instance": None}
    c = Compiler(app=AppInput("t", tmp_path, {}, "", {}), checkpoint=ck, workdir=tmp_path / "b", chain="local:m",
                 log=lambda *a: None, save=lambda d: None, heartbeat=lambda: None, add_cost=lambda *a: None, destroy=lambda inst: None)
    calls = []

    def seed():
        calls.append("seed")
        if calls.count("seed") == 1:
            raise RuntimeChangeNeeded("every gitea command says: run gitea web to install; set GITEA__security__INSTALL_LOCK=true")

    def materialize():
        calls.append(("materialize", c.ck.get("runtime_feedback", "")))

    for name in ("inspect", "research", "plan", "discover", "adapt", "author", "validate"):
        monkeypatch.setattr(c, f"phase_{name}", lambda: None)
    monkeypatch.setattr(c, "phase_materialize", materialize)
    monkeypatch.setattr(c, "phase_seed", seed)
    monkeypatch.setattr(c, "phase_package", lambda: c.ck.__setitem__("package", {"ok": True}))
    assert c.run() == {"ok": True}
    assert calls[0] == "seed" and calls[1][0] == "materialize" and "INSTALL_LOCK" in calls[1][1] and calls[2] == "seed"
    assert c.ck["rewound"] == ["materialize"]
