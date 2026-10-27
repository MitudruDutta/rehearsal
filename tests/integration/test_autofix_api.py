"""The fix-my-agent endpoint and the runs the loop creates, against PostgreSQL."""

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from rehearsal.api.app import app
from rehearsal.api.auth import bootstrap
from rehearsal.db import queue
from rehearsal.db.models import Application, Episode, Job, Run, Scenario, World, WorldVersion
from rehearsal.db.session import session


def _world(project: str) -> str:
    with session() as s:
        a = Application(project_id=project, name="desk")
        s.add(a)
        s.flush()
        w = World(project_id=project, application_id=a.id, name="desk")
        s.add(w)
        s.flush()
        wv = WorldVersion(project_id=project, world_id=w.id, version=1, status="published")
        s.add(wv)
        s.flush()
        for i, split in enumerate(["train", "train", "dev", "holdout"]):
            s.add(Scenario(project_id=project, world_version_id=wv.id, slug=f"job{i}", family=f"f{i}", split=split, status="approved"))
        return wv.id


def test_autofix_checks_its_inputs_and_queues_one_job(db):
    project, key = bootstrap("Fix", "fix")
    auth = {"Authorization": f"Bearer {key}"}
    client = TestClient(app)
    wv = _world(project)
    prof = client.post("/v1/agent-profiles", headers=auth, json={"name": "support"}).json()["id"]
    run = client.post("/v1/evaluations", headers=auth, json={"world_version_id": wv, "profile_ids": [prof], "splits": ["train", "dev"], "repeats": 1}).json()["run_id"]

    body = {"profile_id": prof, "run_id": run, "rounds": 2}
    assert client.post("/v1/autofix", headers=auth, json=body).status_code == 409  # the run has not finished

    with session() as s:
        s.execute(update(Run).where(Run.id == run).values(status="finished"))
    refused = client.post("/v1/autofix", headers=auth, json=body)
    assert refused.status_code == 422 and "train and dev" in refused.json()["detail"]  # nothing finished to learn from

    with session() as s:
        s.execute(update(Episode).where(Episode.run_id == run).values(status="finished", reward=0))
    made = client.post("/v1/autofix", headers=auth, json=body)
    assert made.status_code == 202
    assert made.json()["episodes"] == 2 * 3 + 2 * 1  # two rounds on three train/dev jobs, then two versions on one held-out job
    with session() as s:
        job = s.get(Job, made.json()["job_id"])
        assert job.kind == "autofix" and job.payload["world_version_id"] == wv and job.budget_usd > 0
        job.checkpoint = {"autofix": {"phase": "rehearse", "round": 1}, "instance": {"secret": "x"}}
    shown = client.get(f"/v1/jobs/{made.json()['job_id']}", headers=auth).json()
    assert shown["autofix"] == {"phase": "rehearse", "round": 1} and "checkpoint" not in shown  # progress only, never the sandbox

    external = client.post("/v1/agent-profiles", headers=auth, json={"name": "mine", "driver": "external"}).json()["id"]
    assert client.post("/v1/autofix", headers=auth, json={**body, "profile_id": external}).status_code == 422


def test_loop_runs_belong_to_the_job_and_fail_with_it(db):
    from rehearsal.worker import autofix
    from rehearsal.worker.context import JobContext
    from rehearsal.worker.main import _mark_owner_failed

    project, key = bootstrap("Loop", "loop")
    client = TestClient(app)
    auth = {"Authorization": f"Bearer {key}"}
    wv = _world(project)
    prof = client.post("/v1/agent-profiles", headers=auth, json={"name": "support"}).json()["id"]
    with session() as s:
        s.execute(update(Job).where(Job.kind == "autofix").values(status="cancelled"))  # leftovers from earlier tests
        queue.enqueue(s, project_id=project, kind="autofix", payload={"profile_id": prof, "run_id": "r", "world_version_id": wv})
    with session() as s:
        ctx = JobContext(queue.claim(s, "w1", ["autofix"]), "w1")
    run_id = autofix._new_run(ctx, wv, [prof], ("train", "dev"), 2, "fix round 1")
    with session() as s:
        eps = list(s.scalars(select(Episode).where(Episode.run_id == run_id)))
        assert len(eps) == 6 and {e.job_id for e in eps} == {ctx.job_id}  # no evaluation shard can take them
        assert s.get(Run, run_id).config["autofix_job"] == ctx.job_id
        assert autofix._new_run(ctx, wv, [prof], ("missing",), 1, "x") is None
    with session() as s:
        _mark_owner_failed(s, s.get(Job, ctx.job_id), "boom")
    with session() as s:
        assert s.get(Run, run_id).status == "failed"
        s.get(Job, ctx.job_id).status = "failed"
    assert client.post(f"/v1/jobs/{ctx.job_id}/commands", headers=auth, json={"command": "retry"}).status_code == 200
    with session() as s:
        assert s.get(Run, run_id).status == "running"  # retry reopens the rehearsal the loop stopped in


def test_a_run_shows_model_usage_per_role_over_every_shard(db):
    project, key = bootstrap("Usage", "usage")
    auth = {"Authorization": f"Bearer {key}"}
    client = TestClient(app)
    wv = _world(project)
    prof = client.post("/v1/agent-profiles", headers=auth, json={"name": "support"}).json()["id"]
    run = client.post("/v1/evaluations", headers=auth, json={"world_version_id": wv, "profile_ids": [prof], "repeats": 2}).json()["run_id"]
    row = {"calls": 2, "prompt_tokens": 10, "completion_tokens": 4, "cost_usd": 0.002, "latency_ms": 800, "models": {"nebius:m#nothink": 2}}
    with session() as s:
        shards = queue.run_jobs(s, run)
        for job in shards:
            job.result = {"models": {"agent": row}}
    models = client.get(f"/v1/runs/{run}", headers=auth).json()["models"]
    assert models["agent"]["calls"] == 2 * len(shards) and models["agent"]["models"] == {"nebius:m#nothink": 2 * len(shards)}
