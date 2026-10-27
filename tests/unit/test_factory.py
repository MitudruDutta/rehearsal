"""Agent Factory: a world in, a verified agent out, with a runnable program and a proof report."""

import importlib.util
import json
from types import SimpleNamespace

import pytest

from rehearsal.core.contracts import AgentProfile, WorldManifest
from rehearsal.worker import factory


def manifest():
    return WorldManifest.model_validate({
        "name": "desk", "description": "a help desk", "services": [{"name": "app", "image": "desk", "port": 8080}],
        "roles": [{"name": "admin", "description": "runs the desk"}, {"name": "agent", "description": "answers customers", "customer_channel": True}],
        "tools": [
            {"name": "update_ticket", "description": "Change a ticket.", "service": "app", "method": "PATCH", "path": "/api/tickets/{id}", "mutating": True, "roles": ["agent"],
             "params": [{"name": "id", "location": "path", "schema": {"type": "integer"}}, {"name": "status", "location": "body"}, {"name": "notify", "location": "query", "required": False}]},
            {"name": "delete_user", "description": "Delete a user.", "service": "app", "method": "DELETE", "path": "/api/users/{id}", "mutating": True, "roles": ["admin"],
             "params": [{"name": "id", "location": "path"}]},
        ],
    })


def test_the_packaged_agent_plays_the_customer_role_with_only_its_tools():
    profile = AgentProfile(name="desk-agent", version=3, system_prompt="You are {actor_id} as {role}. {instructions}", tool_guidance={"update_ticket": "Read it first."})
    spec = factory.export_spec(manifest(), profile, "desk-agent")
    assert spec["role"] == "agent" and [t["name"] for t in spec["tools"]] == ["update_ticket"]  # never the admin's delete_user
    assert spec["system_prompt"].startswith("You are desk-agent as agent. Help the customers") and "{" not in spec["system_prompt"]
    tool = spec["tools"][0]
    assert tool["method"] == "PATCH" and tool["path"] == "/api/tickets/{id}" and "Guidance: Read it first." in tool["description"]
    assert {p["name"]: p["location"] for p in tool["params"]} == {"id": "path", "status": "body", "notify": "query"}
    assert spec["model"].startswith("nvidia/") and spec["services"] == ["app"]


def load_agent(tmp_path, monkeypatch, spec):
    (tmp_path / "agent.json").write_text(json.dumps(spec))
    (tmp_path / "agent.py").write_text(factory.AGENT_PY)
    monkeypatch.setenv("NEBIUS_API_KEY", "test")
    monkeypatch.setenv("APP_URL", "https://desk.example/")
    monkeypatch.setenv("APP_AUTH", "Authorization: token abc")
    module_spec = importlib.util.spec_from_file_location("packaged_agent", tmp_path / "agent.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def test_the_packaged_program_calls_the_real_api_and_asks_before_a_change(tmp_path, monkeypatch):
    spec = factory.export_spec(manifest(), AgentProfile(name="desk-agent", system_prompt="{actor_id} {role} {instructions}"), "desk-agent")
    agent = load_agent(tmp_path, monkeypatch, spec)
    sent = []
    monkeypatch.setattr(agent.httpx, "request", lambda method, url, **kw: sent.append((method, url, kw)) or SimpleNamespace(status_code=200, json=lambda: {"ok": True}))
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert agent.call(agent.TOOLS["update_ticket"], {"id": 7, "status": "closed"}) == {"error": "the operator did not allow this change"} and sent == []
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert agent.call(agent.TOOLS["update_ticket"], {"id": 7, "status": "closed", "notify": True})["status"] == 200
    method, url, kw = sent[0]
    assert (method, url) == ("PATCH", "https://desk.example/api/tickets/7") and kw["json"] == {"status": "closed"} and kw["params"] == {"notify": True}
    assert kw["headers"] == {"Authorization": "token abc"}
    assert {f["function"]["name"] for f in agent.FUNCTIONS} == {"update_ticket", "reply_to_customer", "complete"}


class Factory:
    """Scripted world, draft, rehearsals and fix loop, with a recorded checkpoint."""

    def __init__(self, monkeypatch, fix_result):
        self.calls, self.saved = [], []
        self.ctx = SimpleNamespace(payload={"world_version_id": "wv", "rounds": 2, "repeats": 1}, checkpoint={}, job_id="job", check=lambda: None,
                                   log=lambda *a: self.calls.append(("log", a[0])), save_checkpoint=self.saved.append)
        monkeypatch.setattr(factory, "_world", lambda wv: {"name": "desk", "version": 1, "manifest": manifest(), "policies": "", "research": None})
        monkeypatch.setattr(factory, "_draft", lambda ctx, w, name: self.calls.append(("draft", name)) or {"profile_id": "p1", "version": 1, "rationale": "first"})
        monkeypatch.setattr(factory.autofix, "_new_run", lambda ctx, wv, pids, splits, rep, purpose: self.calls.append(("run", splits[0], pids[0])) or f"run:{splits[0]}")
        monkeypatch.setattr(factory.autofix, "_rehearse", lambda ctx, run_id: self.calls.append(("rehearse", run_id)))
        monkeypatch.setattr(factory.autofix, "handle", lambda ctx: self.calls.append(("fix", ctx.payload["profile_id"], ctx.payload["run_id"])) or json.loads(json.dumps(fix_result)))
        monkeypatch.setattr(factory.improve, "score", lambda run, pid, splits: {"success_rate": 0.75, "finished": 4})
        monkeypatch.setattr(factory, "_package", lambda ctx, w, st: self.calls.append(("package", st["fix"]["best"]["profile_id"])) or "art1")


ORIGINAL = {"profile_id": "p1", "version": 1, "run_id": "run:train", "score": {"success_rate": 0.5}}


def test_draft_rehearse_harden_and_package_when_the_fix_loop_proved_a_better_version(monkeypatch):
    best = {"profile_id": "p3", "version": 3, "run_id": "r3", "score": {"success_rate": 0.83}}
    f = Factory(monkeypatch, {"original": ORIGINAL, "best": best, "rounds": [], "holdout": {"run_id": "h", "original": {"success_rate": 0.33}, "best": {"success_rate": 0.67}}})
    out = factory.handle(f.ctx)
    steps = [c for c in f.calls if c[0] != "log"]
    assert steps == [("draft", "desk-agent"), ("run", "train", "p1"), ("rehearse", "run:train"), ("fix", "p1", "run:train"), ("package", "p3")]
    assert out["artifact_id"] == "art1" and out["best"]["version"] == 3 and f.ctx.payload == {"world_version_id": "wv", "rounds": 2, "repeats": 1}


def test_when_no_round_beat_the_draft_the_draft_is_proved_on_held_out_jobs(monkeypatch):
    f = Factory(monkeypatch, {"original": ORIGINAL, "best": ORIGINAL, "rounds": [], "holdout": None})
    out = factory.handle(f.ctx)
    assert ("run", "holdout", "p1") in f.calls and ("rehearse", "run:holdout") in f.calls
    assert out["holdout"]["best"]["success_rate"] == 0.75


def test_a_restarted_factory_does_not_draft_twice(monkeypatch):
    f = Factory(monkeypatch, {"original": ORIGINAL, "best": ORIGINAL, "rounds": [], "holdout": {"best": {"success_rate": 1.0}}})
    f.ctx.checkpoint = {"factory": {"phase": "harden", "draft": {"profile_id": "p1", "version": 1}, "baseline_run": "run:train"}}
    factory.handle(f.ctx)
    assert not any(c[0] in ("draft", "rehearse") for c in f.calls) and ("fix", "p1", "run:train") in f.calls


def test_the_proof_report_shows_every_score_and_what_is_left():
    st = {"draft": {"version": 1}, "fix": {"original": ORIGINAL, "best": {"profile_id": "p3", "version": 3, "score": {"success_rate": 0.83}},
                                          "rounds": [{"round": 1, "version": 2, "score": {"success_rate": 0.4}, "accepted": False, "rationale": "asked twice"}],
                                          "holdout": {"original": {"success_rate": 0.33}, "best": {"success_rate": 0.67}}}}
    causes = [{"label": "Did the same thing twice", "count": 1, "fix": "Look it up before retrying."}]
    text = factory.proof_report({"name": "desk", "version": 2}, st, {"name": "desk-agent", "version": 3}, causes)
    assert "| v1, the draft | 50% | 33% |" in text and "| v3, packaged | 83% | 67% |" in text
    assert "Round 1: v2 verified 40%, discarded" in text and "Did the same thing twice: 1 episode." in text
    readme = factory.readme({"name": "desk-agent", "version": 3, "role": "agent", "model": "m", "services": ["app"], "tools": [{}]})
    assert "python agent.py" in readme and "CONFIRM_WRITES=0" in readme


@pytest.mark.parametrize("name", ["Desk Agent!", "a/b"])
def test_factory_names_are_slugs(name):
    from pydantic import ValidationError

    from rehearsal.api.app import FactoryIn
    with pytest.raises(ValidationError):
        FactoryIn(world_version_id="wv", name=name)
