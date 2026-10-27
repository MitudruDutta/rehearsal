"""Why episodes failed, through the API: causes from stored verdicts and actions, behind evaluator access."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from rehearsal.api.app import app
from rehearsal.api.auth import bootstrap, create_key
from rehearsal.db.models import Action, Episode
from rehearsal.db.session import session

from .test_autofix_api import _world


def test_failure_causes_come_from_the_record_and_need_evaluator_access(db):
    project, key = bootstrap("Causes", "causes")
    client = TestClient(app)
    auth = {"Authorization": f"Bearer {key}"}
    wv = _world(project)
    prof = client.post("/v1/agent-profiles", headers=auth, json={"name": "support"}).json()["id"]
    run = client.post("/v1/evaluations", headers=auth, json={"world_version_id": wv, "profile_ids": [prof], "splits": ["train"], "repeats": 1}).json()["run_id"]
    with session() as s:
        first, second = s.scalars(select(Episode).where(Episode.run_id == run).order_by(Episode.id)).all()
        first.status, first.reward, first.termination = "finished", 0, "completed"
        first.oracle = {"goal_satisfied": False, "hard_constraint_violations": [], "duplicate_effects": 1, "check_results": []}
        second.status, second.reward, second.termination = "finished", 0, "completed"
        second.oracle = {"goal_satisfied": False, "hard_constraint_violations": [], "check_results": []}
        s.add(Action(episode_id=second.id, seq=1, actor="agent", tool="update_ticket", operation_id=f"op-{second.id}", args={}, status="SUCCEEDED", goal_version=2, observed_goal_version=1, mutating=True))
    out = client.get(f"/v1/runs/{run}/failures", headers=auth).json()
    causes = {c["cause"]: c for c in out["support@v1"]["causes"]}
    assert out["support@v1"]["failed"] == 2 and causes["duplicate"]["episodes"] == [first.id] and causes["old_request"]["episodes"] == [second.id]

    with session() as s:
        reader = create_key(s, project, "dashboard", ["read"])
    assert client.get(f"/v1/runs/{run}/failures", headers={"Authorization": f"Bearer {reader}"}).status_code == 403  # check details reveal held-out jobs


def test_the_improver_is_told_the_causes_from_train_and_dev_only(db, monkeypatch):
    import json

    from rehearsal.agents.llm import LLMReply
    from rehearsal.db import queue
    from rehearsal.db.models import Job, Scenario
    from rehearsal.worker import improve
    from rehearsal.worker.context import JobContext

    project, key = bootstrap("Learn", "learn")
    client = TestClient(app)
    auth = {"Authorization": f"Bearer {key}"}
    wv = _world(project)
    prof = client.post("/v1/agent-profiles", headers=auth, json={"name": "support"}).json()["id"]
    run = client.post("/v1/evaluations", headers=auth, json={"world_version_id": wv, "profile_ids": [prof], "repeats": 1}).json()["run_id"]
    with session() as s:
        for e, split in s.execute(select(Episode, Scenario.split).join(Scenario, Scenario.id == Episode.scenario_id).where(Episode.run_id == run)).all():
            e.status, e.reward, e.termination = "finished", 0, "completed"
            # train and dev episodes made duplicates; the held-out one broke a rule, which the improver must never learn from
            e.oracle = {"goal_satisfied": False, "check_results": [], "duplicate_effects": 1 if split != "holdout" else 0,
                        "hard_constraint_violations": ["secret_rule"] if split == "holdout" else []}
        s.query(Job).filter(Job.kind == "improvement").update({"status": "cancelled"})  # leftovers from earlier tests
        queue.enqueue(s, project_id=project, kind="improvement", payload={"profile_id": prof, "run_id": run})
    with session() as s:
        ctx = JobContext(queue.claim(s, "w1", ["improvement"]), "w1")
    seen = {}

    def fake_chat(chain, messages, **kw):
        seen.update(json.loads(messages[1]["content"]))
        return {"system_prompt": "Look before retrying. {actor_id} {role} {instructions}", "rationale": "duplicates"}, LLMReply(content="{}", tool_calls=[], provider="local", model="m")

    monkeypatch.setattr(improve, "chat_json", fake_chat)
    improve.propose(ctx, prof, run)
    assert [c["label"] for c in seen["failure_causes"]] == ["Did the same thing twice"] and seen["failure_causes"][0]["count"] == 3
    assert "secret_rule" not in json.dumps(seen)  # nothing from the held-out job
