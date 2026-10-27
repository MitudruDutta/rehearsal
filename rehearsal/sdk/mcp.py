"""MCP server: lets an AI assistant (Claude Code, Cursor, Codex, ...) use Rehearsal with a Rehearsal API key.

    rehearsal login                      # once: saves the server URL and an API key
    claude mcp add rehearsal -- rehearsal mcp
    (or REHEARSAL_API_KEY / REHEARSAL_URL in the server's environment)

The assistant can add applications, build practice worlds, run evaluations, read why episodes failed, and propose a
better agent version. It can also be the agent under test: an agent created with bring_your_own=True gets its turns
through waiting_turns and acts through take_action. Every call uses the key's own permissions; model costs of builds
and evaluations count against the workspace's monthly allowance.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from .client import Rehearsal

INSTRUCTIONS = (
    "Rehearsal tests AI agents on a sandboxed copy of a real application, with fictional data, a simulated customer who "
    "changes their mind, and injected faults; results are checked against the application's own database. Typical flow: "
    "list_applications or add_application -> build_world (1-3 hours; check with job_status) -> list_worlds -> list_agents "
    "or create_agent -> run_evaluation -> run_results -> episode_details for failures -> fix_agent (rounds of improve and "
    "rehearse, proven on held-out jobs; or improve_agent for one proposal) -> job_status. Builds and evaluations spend "
    "model money from the workspace's monthly allowance: say what you are about to start and ask the user before "
    "build_world, run_evaluation, fix_agent, improve_agent and recheck_world. To act as the agent under test yourself, create_agent(bring_your_own=True), start run_evaluation with "
    "it, then loop: waiting_turns -> read the new messages -> take_action with one of the offered tools."
)


def _short(text: Any, n: int = 600) -> str:
    text = "" if text is None else str(text)
    return text if len(text) <= n else text[:n] + "..."


class _Client:
    """Connects on first use, so the server starts (and the assistant can explain what to do) before the user signs in."""

    def __init__(self) -> None:
        self._c: Rehearsal | None = None

    def __getattr__(self, name: str) -> Any:
        if self._c is None:
            try:
                self._c = Rehearsal()
            except ValueError as exc:
                raise RuntimeError("Rehearsal is not signed in on this machine. Ask the user to run `rehearsal login` "
                                   "(or `uvx --from rehearsal-kit rehearsal login`) with an API key from the console's API keys page, "
                                   "then try again.") from exc
        return getattr(self._c, name)


def build_server(client: Rehearsal | None = None) -> Any:
    from mcp.server.fastmcp import FastMCP

    c: Any = client or _Client()
    link = lambda path: f"{c.base_url}{path}"  # noqa: E731
    mcp = FastMCP("rehearsal", instructions=INSTRUCTIONS)

    # ------------------------------------------------------------------ workspace and applications

    @mcp.tool()
    def workspace_status() -> dict[str, Any]:
        """The workspace's plan and what it has left this month (applications, world builds, episodes, sandboxes), model
        spend against the monthly allowance, and what exists in the workspace."""
        usage = c.get("/v1/usage")
        b = c.get("/v1/billing")
        plan = {"name": b["plan"]["title"], "limits": {k: b["plan"][k] for k in ("applications", "builds", "episodes", "sandboxes")},
                "used": b["usage"], "renews": b["renews"], "quiet_hours_utc": b.get("quiet_hours_utc"), "more": link("/app/billing/")}
        worlds = c.get("/v1/worlds")
        published = [v for w in worlds for v in w["versions"] if v["status"] == "published"]
        return {"plan": plan, "usage": usage, "applications": len(c.get("/v1/applications")), "published_world_versions": len(published),
                "agents": len(c.get("/v1/agent-profiles")), "console": link("/app/")}

    @mcp.tool()
    def list_applications() -> list[dict[str, Any]]:
        """Applications in the workspace (the real apps that practice worlds are built from)."""
        return [{"id": a["id"], "name": a["name"], "source": a.get("source"), "notes": a.get("notes")} for a in c.get("/v1/applications")]

    @mcp.tool()
    def add_application(name: str, repository_url: str, commit: str = "", images: dict[str, str] | None = None, policies: str = "") -> dict[str, Any]:
        """Add an application from a public git repository. images maps service name to a pinned image
        (for example {"app": "org/app:1.2@sha256:..."}). policies are rules agents must follow, in plain words."""
        source = {"kind": "git", "url": repository_url, **({"commit": commit} if commit else {})}
        a = c.post("/v1/applications", {"name": name, "source": source, "images": images or {}, "policies": policies})
        return {"id": a["id"], "name": a["name"]}

    # ------------------------------------------------------------------ worlds

    @mcp.tool()
    def build_world(application_id: str, scenarios: int = 8, budget_usd: float | None = None) -> dict[str, Any]:
        """Start compiling an application into a practice world. Takes 1-3 hours and spends model money (about $3-8).
        Ask the user first. Follow progress with job_status."""
        r = c.post("/v1/world-builds", {"application_id": application_id, "scenario_target": scenarios, **({"budget_usd": budget_usd} if budget_usd else {})})
        return {**r, "watch": link(f"/app/build/?id={r['job_id']}")}

    @mcp.tool()
    def job_status(job_id: str) -> dict[str, Any]:
        """Status of a build, evaluation shard or improvement job: state, finished steps, spend, and the error if it failed."""
        j = c.get(f"/v1/jobs/{job_id}")
        return {"id": j["id"], "kind": j["kind"], "status": j["status"], "attempts": j["attempts"], "spent_usd": round(j.get("spent_usd") or 0, 4),
                "completed_steps": j.get("completed_phases"), "result": j.get("result"), "error": _short(j.get("error"), 800) or None}

    @mcp.tool()
    def control_job(job_id: str, command: str) -> dict[str, Any]:
        """pause, resume, stop, or retry (restart a failed or stopped job from its last saved step)."""
        return c.post(f"/v1/jobs/{job_id}/commands", {"command": command})

    @mcp.tool()
    def list_worlds() -> list[dict[str, Any]]:
        """Practice worlds and their versions. Only published versions can be used in evaluations."""
        return [{"world": w["name"], "application_id": w["application_id"],
                 "versions": [{"world_version_id": v["id"], "version": v["version"], "status": v["status"]} for v in w["versions"]]} for w in c.get("/v1/worlds")]

    @mcp.tool()
    def list_scenarios(world_version_id: str) -> list[dict[str, Any]]:
        """The jobs (scenarios) in a world version, with their split: train and dev are for improving, holdout is for the final score."""
        return [{"id": s["id"], "slug": s["slug"], "title": (s.get("spec") or {}).get("title"), "split": s["split"], "status": s["status"]}
                for s in c.get(f"/v1/world-versions/{world_version_id}/scenarios")]

    @mcp.tool()
    def recheck_world(world_version_id: str) -> dict[str, Any]:
        """Replay every job of a published world and try each with a live agent; unfair jobs are withdrawn. Costs about $0.03 per job. Ask first."""
        return c.post(f"/v1/world-versions/{world_version_id}/validate", {})

    # ------------------------------------------------------------------ agents and evaluations

    @mcp.tool()
    def list_agents() -> list[dict[str, Any]]:
        """Agent profiles (versions of an agent: instructions, tool guidance, model)."""
        return [{"id": p["id"], "name": p["name"], "version": p["version"], "driver": (p.get("spec") or {}).get("driver", "llm"),
                 "created_by": p.get("created_by")} for p in c.get("/v1/agent-profiles")]

    @mcp.tool()
    def create_agent(name: str, instructions: str = "", model: str | None = None, bring_your_own: bool = False) -> dict[str, Any]:
        """Create an agent profile. instructions is its system prompt (empty uses the platform default). With
        bring_your_own=True, Rehearsal does not run a model for it: your own agent acts through waiting_turns and take_action."""
        p = c.post("/v1/agent-profiles", {"name": name, "system_prompt": instructions, "model": model, "driver": "external" if bring_your_own else "llm"})
        return {"id": p["id"], "name": p["name"], "version": p["version"]}

    @mcp.tool()
    def run_evaluation(world_version_id: str, agent_ids: list[str], splits: list[str] | None = None, repeats: int | None = None, budget_usd: float | None = None) -> dict[str, Any]:
        """Run agents through the jobs of a published world version. By default every job (train, dev, holdout) is run
        twice, with the default stress layer on. Narrow it with splits (any of train, dev, holdout) and repeats.
        Spends model money (about $0.02 per episode). Ask the user first."""
        r = c.post("/v1/evaluations", {"world_version_id": world_version_id, "profile_ids": agent_ids, **({"splits": splits} if splits else {}),
                                       **({"repeats": repeats} if repeats else {}), **({"budget_usd": budget_usd} if budget_usd else {})})
        return {**r, "watch": link(f"/app/run/?id={r['run_id']}")}

    @mcp.tool()
    def run_results(run_id: str) -> dict[str, Any]:
        """Status and scores of an evaluation run, one line per episode, and why episodes failed: named causes per
        agent with their usual fix. Start from the causes when explaining a run."""
        run = c.get(f"/v1/runs/{run_id}")
        episodes = c.get(f"/v1/runs/{run_id}/episodes")
        causes = {agent: [{k: x[k] for k in ("label", "count", "fix", "episodes")} for x in v["causes"]] for agent, v in c.get(f"/v1/runs/{run_id}/failures").items()}
        return {"status": run["status"], "summary": (run.get("summary") or {}).get("profiles") or None, "failure_causes": causes,
                "episodes": [{"id": e["id"], "split": e.get("split"), "scenario": e.get("scenario"), "status": e["status"], "verified": e.get("reward") == 1,
                              "ending": e.get("termination")} for e in episodes],
                "console": link(f"/app/run/?id={run_id}")}

    @mcp.tool()
    def episode_details(episode_id: str) -> dict[str, Any]:
        """What happened in one episode: the request and its revisions, every action with its result, and which checks failed."""
        e = c.get(f"/v1/episodes/{episode_id}")
        oracle = e.get("oracle") or {}
        return {
            "scenario": (e.get("scenario") or {}).get("title"), "goals": (e.get("scenario") or {}).get("goals"), "status": e["status"], "ending": e.get("termination"),
            "verified": e.get("reward") == 1, "environment_error": oracle.get("environment_error"),
            "failed_checks": [{"check": x.get("description"), "observed": x.get("actual"), "wanted": f"{x.get('op')} {x.get('expected')}"}
                              for x in oracle.get("check_results", []) if not x.get("passed")],
            "duplicate_effects": oracle.get("duplicate_effects"), "false_completion": oracle.get("false_completion"),
            "actions": [f"{a['actor']}: {a['tool']}({_short(a.get('args'), 160)}) -> {a['status']}{' [' + a['fault'] + ']' if a.get('fault') else ''}" for a in e.get("actions", [])],
            "messages": [f"{m.get('sender')}: {_short(m.get('text'), 300)}" for m in e.get("messages", [])][-30:],
            "console": link(f"/app/run/?id={e.get('run_id')}&episode={episode_id}"),
        }

    @mcp.tool()
    def improve_agent(agent_id: str, run_id: str) -> dict[str, Any]:
        """Propose the next version of an agent from its failed train and dev episodes in a run. Ask first. Then
        evaluate both versions on the holdout split and compare_runs before keeping the new one."""
        return c.post("/v1/improvements", {"profile_id": agent_id, "run_id": run_id})

    @mcp.tool()
    def fix_agent(agent_id: str, run_id: str, rounds: int = 3, repeats: int = 1) -> dict[str, Any]:
        """Fix an agent end to end: each round proposes a new version from failed train and dev episodes, rehearses it,
        and keeps it only if it verifies more episodes without new rule violations. The best version is then compared
        with the original on held-out jobs. Spends money from the allowance: say the episode count and ask first.
        Follow it with job_status; the finished job's result lists every round and the held-out comparison."""
        res = c.post("/v1/autofix", {"profile_id": agent_id, "run_id": run_id, "rounds": rounds, "repeats": repeats})
        return {**res, "console": link(f"/app/fix/?job={res['job_id']}")}

    @mcp.tool()
    def compare_runs(run_a: str, run_b: str | None = None) -> dict[str, Any]:
        """Compare agents within one run, or two runs on the same world version."""
        return c.get("/v1/compare", params={"run_a": run_a, **({"run_b": run_b} if run_b else {})})

    # ------------------------------------------------------------------ bring your own agent

    @mcp.tool()
    def waiting_turns(run_id: str, wait_s: int = 30) -> list[dict[str, Any]]:
        """For a run of a bring-your-own agent: episodes waiting for your next action. Each has the actor you play,
        the new messages since your last action, and the tools you may call. Waits up to wait_s for a turn."""
        deadline = time.monotonic() + max(0, min(wait_s, 120))
        while True:
            out = []
            for e in c.get(f"/v1/runs/{run_id}/episodes"):
                if e["status"] != "running":
                    continue
                obs = c.get(f"/v1/episodes/{e['id']}/observation")
                if obs.get("awaiting_action"):
                    data = obs["turn"]["data"]
                    out.append({"episode_id": e["id"], "actor": data["actor"], "new_messages": data.get("new", []),
                                "tools": [{"name": t["function"]["name"], "description": _short(t["function"].get("description"), 400),
                                           "parameters": t["function"].get("parameters")} for t in data.get("tools", [])]})
            if out or time.monotonic() >= deadline:
                return out
            time.sleep(2)

    @mcp.tool()
    def take_action(episode_id: str, actor: str, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Act in an episode as the actor named by waiting_turns, with one of the tools it offered. Returns the tool's result."""
        return c.external.act(episode_id, actor, tool, arguments or {}, idempotency_key=uuid.uuid4().hex, wait_s=90)

    return mcp


def main() -> None:
    build_server().run()  # stdio
