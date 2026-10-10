"""A LangGraph ReAct agent rehearsed by Rehearsal (bring your own agent).

The ReAct agent (LangChain's create_agent, which runs on LangGraph) decides; Rehearsal runs the world, the simulated customer and the checks.
Each world tool becomes a LangChain tool whose body sends the action to Rehearsal and returns the result,
so every tool call the agent makes is one action in the episode.

    source ~/python/bin/activate
    rehearsal profiles create langgraph-react --external        # once; prints the agent id
    python examples/agents/langgraph_react.py --world WORLD_VERSION_ID --agent AGENT_ID --split dev

Rehearsal: REHEARSAL_URL, REHEARSAL_API_KEY. The agent's own model (any OpenAI-compatible endpoint):
AGENT_BASE_URL, AGENT_API_KEY, AGENT_MODEL (default: Nebius, NEBIUS_API_KEY, zai-org/GLM-5.3-Flash,
the same model as the baseline profile, so a comparison measures the framework, not the model).
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
try:  # LangChain 1.x builds its ReAct agent on LangGraph; older installs have LangGraph's prebuilt one
    from langchain.agents import create_agent as react_agent
except ImportError:
    from langgraph.prebuilt import create_react_agent as react_agent

from rehearsal.sdk import Rehearsal

DONE = ("finished", "failed", "cancelled")


def model() -> ChatOpenAI:
    return ChatOpenAI(
        base_url=os.environ.get("AGENT_BASE_URL", "https://api.tokenfactory.nebius.com/v1"),
        api_key=os.environ.get("AGENT_API_KEY") or os.environ["NEBIUS_API_KEY"],
        model=os.environ.get("AGENT_MODEL", "zai-org/GLM-5.3-Flash"),
        temperature=0.2,
        timeout=180,
    )


class Seat:
    """One actor in one episode: its conversation so far, kept across turns."""

    def __init__(self, rh: Rehearsal, llm: ChatOpenAI, episode: str, actor: str):
        self.rh, self.llm, self.episode, self.actor = rh, llm, episode, actor
        self.messages: list[BaseMessage] = []

    def take_turn(self, turn: dict[str, Any]) -> str:
        for m in turn.get("new", []):  # tool results are already in the graph's state
            if m.get("role") == "system":
                self.messages.append(SystemMessage(m["content"]))
            elif m.get("role") == "user":
                self.messages.append(HumanMessage(m["content"]))
        acted: list[str] = []

        def tool_for(spec: dict[str, Any]) -> StructuredTool:
            fn = spec["function"]

            def run(**args: Any) -> str:
                if acted:  # one action per turn; the next turn brings the next one
                    return "Not executed: one action per turn. Call it again on your next turn if still needed."
                acted.append(fn["name"])
                result = self.rh.external.act(self.episode, self.actor, fn["name"], args, idempotency_key=uuid.uuid4().hex)
                return json.dumps(result, default=str)[:8000]

            return StructuredTool(name=fn["name"], description=fn.get("description") or fn["name"],
                                  args_schema=fn.get("parameters") or {"type": "object", "properties": {}},
                                  func=run, return_direct=True)  # stop after the action: one tool call = one turn

        tools = [tool_for(t) for t in turn.get("tools", [])]
        graph = react_agent(self.llm, tools)
        out = graph.invoke({"messages": self.messages}, {"recursion_limit": 6})
        self.messages = list(out["messages"])
        if acted:
            return acted[0]
        # The agent answered in words only. Rehearsal needs an action, so yield the turn.
        names = {t["function"]["name"] for t in turn.get("tools", [])}
        fallback = "wait" if "wait" in names else next(iter(names))
        self.rh.external.act(self.episode, self.actor, fallback, {}, idempotency_key=uuid.uuid4().hex)
        self.messages.append(AIMessage(f"(called {fallback})"))
        return fallback


def drive(rh: Rehearsal, run_id: str) -> None:
    llm, seats = model(), {}
    while rh.runs.get(run_id)["status"] not in DONE:
        acted = False
        for ep in rh.runs.episodes(run_id):
            if ep["status"] != "running":
                continue
            obs = rh.external.observation(ep["id"])
            if not obs.get("awaiting_action"):
                continue
            turn = obs["turn"]["data"]
            seat = seats.setdefault((ep["id"], turn["actor"]), Seat(rh, llm, ep["id"], turn["actor"]))
            try:
                tool = seat.take_turn(turn)
            except Exception as exc:  # the agent's own model or code failed: stop cleanly instead of leaving episodes waiting
                rh.runs.command(run_id, "stop")
                raise SystemExit(f"The agent failed on {ep['id']} ({exc.__class__.__name__}: {str(exc)[:300]}). The run was stopped.") from None
            print(f"{ep['id'][-6:]} {turn['actor']}: {tool}", flush=True)
            acted = True
        if not acted:
            time.sleep(1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--world", help="world version id; starts a new evaluation run")
    ap.add_argument("--agent", help="id of the bring-your-own agent profile (rehearsal profiles create NAME --external)")
    ap.add_argument("--split", action="append", default=[])
    ap.add_argument("--repeats", type=int, default=None, help="default 2; with no --split, every job runs")
    ap.add_argument("--run", help="drive an existing run instead of starting one")
    args = ap.parse_args()
    rh = Rehearsal()
    run_id = args.run
    if not run_id:
        if not (args.world and args.agent):
            ap.error("give --run, or --world and --agent")
        run = rh.evaluations.create(args.world, [args.agent], splits=args.split or None, repeats=args.repeats)
        run_id = run["run_id"]
        print(f"run {run_id}: {run['episodes']} episodes, watch {rh.base_url}/app/run/?id={run_id}", flush=True)
    drive(rh, run_id)
    summary = (rh.runs.get(run_id).get("summary") or {}).get("overall") or {}
    print(json.dumps({k: summary.get(k) for k in ("episodes", "successes", "success_rate", "duplicate_effects", "false_completions", "recovered", "cost_usd")}))


if __name__ == "__main__":
    main()
