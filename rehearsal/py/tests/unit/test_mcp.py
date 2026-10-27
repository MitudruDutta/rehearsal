"""The MCP server exposes Rehearsal to AI assistants through a Rehearsal API key only."""

import asyncio
import json

import pytest

pytest.importorskip("mcp")

from rehearsal.sdk.mcp import build_server


class FakeClient:
    base_url = "https://rehearsal.example"

    def __init__(self):
        self.posts = []
        self.external = self

    def get(self, path, params=None):
        if path.endswith("/episodes"):
            return [{"id": "ep_wait", "status": "running"}, {"id": "ep_busy", "status": "running"}, {"id": "ep_done", "status": "finished"}]
        if path == "/v1/episodes/ep_wait/observation":
            tool = {"type": "function", "function": {"name": "create_post", "description": "Post a message", "parameters": {"type": "object"}}}
            return {"awaiting_action": True, "turn": {"data": {"actor": "agent", "new": [{"role": "user", "content": "hi"}], "tools": [tool]}}}
        if path == "/v1/episodes/ep_busy/observation":
            return {"awaiting_action": False, "turn": {"data": {}}}
        raise AssertionError(path)

    def post(self, path, body):
        self.posts.append((path, body))
        return {"run_id": "run_1", "job_id": "job_1", "episodes": 4, "shards": 2}

    def act(self, ep, actor, tool, args, idempotency_key, wait_s):
        return {"status": 200, "acted": [ep, actor, tool, args]}


def call(server, name, args):
    result = asyncio.run(server.call_tool(name, args))
    blocks = result[0] if isinstance(result, tuple) else result
    return json.loads(blocks[0].text)


def test_assistant_sees_the_whole_workflow_as_tools():
    names = {t.name for t in asyncio.run(build_server(FakeClient()).list_tools())}
    assert {"workspace_status", "add_application", "build_world", "job_status", "run_evaluation", "run_results",
            "episode_details", "fix_agent", "improve_agent", "compare_runs", "waiting_turns", "take_action"} <= names


def test_bring_your_own_agent_gets_only_turns_that_wait_for_it_and_can_act():
    client = FakeClient()
    server = build_server(client)
    turns = call(server, "waiting_turns", {"run_id": "run_1", "wait_s": 0})
    turns = turns if isinstance(turns, list) else [turns]
    assert [t["episode_id"] for t in turns] == ["ep_wait"] and turns[0]["tools"][0]["name"] == "create_post"
    acted = call(server, "take_action", {"episode_id": "ep_wait", "actor": "agent", "tool": "create_post", "arguments": {"message": "On it"}})
    assert acted["acted"] == ["ep_wait", "agent", "create_post", {"message": "On it"}]


def test_evaluation_returns_a_console_link_to_watch():
    client = FakeClient()
    out = call(build_server(client), "run_evaluation", {"world_version_id": "wv_1", "agent_ids": ["prof_1"]})
    assert out["watch"] == "https://rehearsal.example/app/run/?id=run_1"
    assert client.posts == [("/v1/evaluations", {"world_version_id": "wv_1", "profile_ids": ["prof_1"]})]  # server defaults: every job, twice


def test_fix_agent_starts_the_loop_and_links_to_it():
    client = FakeClient()
    out = call(build_server(client), "fix_agent", {"agent_id": "prof_1", "run_id": "run_0", "rounds": 2})
    assert out["console"] == "https://rehearsal.example/app/fix/?job=job_1" and out["episodes"] == 4
    assert client.posts == [("/v1/autofix", {"profile_id": "prof_1", "run_id": "run_0", "rounds": 2, "repeats": 1})]


def test_make_agent_starts_the_factory_and_links_to_it():
    client = FakeClient()
    out = call(build_server(client), "make_agent", {"world_version_id": "wv_1", "rounds": 2})
    assert out["console"] == "https://rehearsal.example/app/fix/?job=job_1"
    assert client.posts == [("/v1/factory", {"world_version_id": "wv_1", "name": "", "rounds": 2, "repeats": 1})]
