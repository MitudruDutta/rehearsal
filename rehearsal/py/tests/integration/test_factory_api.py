"""Agent Factory through the API: the endpoint's checks and quote, and a package you can download."""

import io
import json
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import update

from rehearsal.api.app import app
from rehearsal.api.auth import bootstrap
from rehearsal.db import queue
from rehearsal.db.models import Job, WorldVersion
from rehearsal.db.session import session

from .test_autofix_api import _world

MANIFEST = {"name": "desk", "description": "a help desk", "services": [{"name": "app", "image": "desk", "port": 8080}],
            "roles": [{"name": "agent", "description": "answers customers", "customer_channel": True}],
            "tools": [{"name": "close_ticket", "description": "Close a ticket.", "service": "app", "method": "POST", "path": "/api/tickets/{id}/close",
                       "mutating": True, "roles": ["agent"], "params": [{"name": "id", "location": "path"}]}]}


def test_factory_quotes_its_episodes_and_packages_a_downloadable_agent(db):
    from rehearsal.worker import factory
    from rehearsal.worker.context import JobContext

    project, key = bootstrap("Factory", "factory")
    auth = {"Authorization": f"Bearer {key}"}
    client = TestClient(app)
    wv = _world(project)  # two train, one dev and one held-out job
    with session() as s:
        s.execute(update(WorldVersion).where(WorldVersion.id == wv).values(manifest=MANIFEST))
        s.execute(update(Job).where(Job.kind == "factory").values(status="cancelled"))  # leftovers from earlier tests
    assert client.post("/v1/factory", headers=auth, json={"world_version_id": wv, "name": "Bad Name"}).status_code == 422
    made = client.post("/v1/factory", headers=auth, json={"world_version_id": wv, "rounds": 2})
    assert made.status_code == 202 and made.json()["episodes"] == (2 + 1) * 3 + 2 * 1  # the draft and two rounds on 3 practice jobs, then 2 versions on 1 held-out job

    prof = client.post("/v1/agent-profiles", headers=auth, json={"name": "desk-agent", "system_prompt": "You are {actor_id}, {role}. {instructions}"}).json()
    run = client.post("/v1/evaluations", headers=auth, json={"world_version_id": wv, "profile_ids": [prof["id"]], "splits": ["train"], "repeats": 1}).json()["run_id"]
    with session() as s:
        ctx = JobContext(queue.claim(s, "w1", ["factory"]), "w1")
    best = {"profile_id": prof["id"], "version": 1, "run_id": run, "score": {"success_rate": 1.0}}
    st = {"draft": {"version": 1}, "fix": {"original": best, "best": best, "rounds": [], "holdout": {"best": {"success_rate": 1.0}}}}
    art = factory._package(ctx, factory._world(wv), st)

    zipped = client.get(f"/v1/artifacts/{art}/download", headers=auth)
    assert zipped.status_code == 200
    files = zipfile.ZipFile(io.BytesIO(zipped.content))
    assert sorted(files.namelist()) == ["desk-agent/PROOF.md", "desk-agent/README.md", "desk-agent/agent.json", "desk-agent/agent.py"]
    spec = json.loads(files.read("desk-agent/agent.json"))
    assert spec["tools"][0]["path"] == "/api/tickets/{id}/close" and spec["system_prompt"].startswith("You are desk-agent, agent.")
    assert "| v1, packaged | 100% | 100% |" in files.read("desk-agent/PROOF.md").decode()
