"""factory job: from a published world to a verified agent you can run.

1. Draft: the agent designer writes the first agent from the world itself: its roles and tools, which writes are safe
   to retry, the owner's policies, the web research on real use, and the failure causes Rehearsal checks for.
2. Rehearse the draft on every train and dev job.
3. Harden it with the fix loop (worker/autofix.py), which keeps only versions that verify more and compares the best
   with the draft on held-out jobs. When no round was needed, the draft is proved on held-out jobs alone.
4. Package a zip: the instructions, the tool definitions mapped to the application's real API, a standalone Python
   agent that runs on NVIDIA Nemotron through Nebius Token Factory, and a proof report with every score.

Each phase is saved in the job checkpoint under "factory"; the fix loop keeps its own state under "autofix".
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime, timezone
from typing import Any

from ..agents.llm import LLMError, chat_json
from ..compiler import web
from ..config import settings
from ..core.contracts import AgentProfile, WorldManifest
from ..db.models import Application, World, WorldVersion
from ..db.session import session
from ..evaluator.failures import CAUSES, run_failures
from . import autofix, improve
from .context import JobContext
from .export import _artifact

MODEL = "nvidia/nemotron-3-super-120b-a12b"  # what the packaged agent runs on by default


def _world(wv_id: str) -> dict[str, Any]:
    with session() as s:
        wv = s.get(WorldVersion, wv_id)
        world = s.get(World, wv.world_id) if wv else None
        app = s.get(Application, world.application_id) if world else None
        if wv is None or world is None:
            raise ValueError("world version not found")
        return {"name": world.name, "version": wv.version, "manifest": WorldManifest.model_validate(wv.manifest),
                "policies": app.policies if app else "", "research": (wv.validation or {}).get("research")}


def agent_role(manifest: WorldManifest) -> str:
    """The role the packaged agent plays: the one that talks to customers, else the first."""
    return next((r.name for r in manifest.roles if r.customer_channel), manifest.roles[0].name if manifest.roles else "agent")


def _draft(ctx: JobContext, w: dict[str, Any], name: str) -> dict[str, Any]:
    m: WorldManifest = w["manifest"]
    brief = {
        "application": m.name, "what_it_is": m.description,
        "roles": [{"name": r.name, "does": r.description, "talks_to_customers": r.customer_channel} for r in m.roles],
        "tools": [{"name": t.name, "does": t.description[:300], "changes_data": t.mutating, "safe_to_retry": t.name in m.capabilities.idempotent_tools, "roles": t.roles}
                  for t in m.tools],
        "owner_policies": w["policies"] or "(none)",
        "how_real_people_use_it": web.digest(w["research"]) or "(no web research for this world)",
        "what_agents_get_wrong": {CAUSES[c][0]: CAUSES[c][2] for c in CAUSES},
    }
    system = (
        "You are the Agent designer of Rehearsal's Agent Factory. Write the operating instructions for an AI agent that does real "
        "work in this application for its customers, through the tools listed. The agent will be tested on jobs where the "
        "customer changes the request mid-way, writes time out after they succeeded, requests break the owner's rules, and "
        "information is missing, and every outcome is checked in the application's database. Write general, concrete "
        "behaviours: which tools to use for which requests, what to verify before and after every change, what to ask the "
        "customer, what to refuse, and when the work is done. Never name record ids or invent data. Add per-tool guidance for "
        "the tools that are easy to misuse. Keep the {actor_id}, {role} and {instructions} placeholders in the prompt. "
        'Return JSON: {"system_prompt": str, "tool_guidance": {tool: str}, "rationale": str}.'
    )
    try:
        data, reply = chat_json(settings().model_improver, [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(brief, default=str)[:100_000]}],
                                check=ctx.check, role="factory.designer")
    except LLMError as exc:
        if (reply := getattr(exc, "reply", None)) is not None:
            ctx.add_cost(reply.cost_usd, reply.prompt_tokens + reply.completion_tokens)
        raise
    ctx.add_cost(reply.cost_usd, reply.prompt_tokens + reply.completion_tokens)
    return improve.save_version(ctx, AgentProfile(name=name), data, parent_id=None, created_by="factory", summary="drafted by the Agent Factory from the world")


def handle(ctx: JobContext) -> dict[str, Any]:
    p = ctx.payload
    st: dict[str, Any] = ctx.checkpoint.get("factory") or {"phase": "draft"}

    def save() -> None:
        ctx.checkpoint["factory"] = st
        ctx.save_checkpoint(ctx.checkpoint)

    w = _world(p["world_version_id"])
    name = p.get("name") or re.sub(r"[^a-z0-9]+", "-", f"{w['name']} agent".lower()).strip("-")
    while st["phase"] != "done":
        ctx.check()
        if st["phase"] == "draft":
            st["draft"] = _draft(ctx, w, name)
            st["phase"] = "rehearse"
            save()
            ctx.log("factory.drafted", f"{name} v{st['draft']['version']} drafted from the world", st["draft"])
        elif st["phase"] == "rehearse":
            if not st.get("baseline_run"):
                st["baseline_run"] = autofix._new_run(ctx, p["world_version_id"], [st["draft"]["profile_id"]], autofix.PRACTICE, int(p.get("repeats", 1)), "factory: the draft")
                if not st["baseline_run"]:
                    raise ValueError("this world has no approved train or dev jobs to rehearse on")
                save()
            autofix._rehearse(ctx, st["baseline_run"])
            st["phase"] = "harden"
            save()
        elif st["phase"] == "harden":
            ctx.payload = {**p, "profile_id": st["draft"]["profile_id"], "run_id": st["baseline_run"]}
            try:
                st["fix"] = autofix.handle(ctx)
            finally:
                ctx.payload = p
            st["phase"] = "prove" if st["fix"]["holdout"] is None else "package"
            save()
        elif st["phase"] == "prove":  # nothing beat the draft, so the draft itself is proved on unseen jobs
            best = st["fix"]["best"]
            if not st.get("proof_run"):
                st["proof_run"] = autofix._new_run(ctx, p["world_version_id"], [best["profile_id"]], ("holdout",), int(p.get("repeats", 1)), "factory: held-out proof")
                save()
            if st["proof_run"]:
                autofix._rehearse(ctx, st["proof_run"])
                st["fix"]["holdout"] = {"run_id": st["proof_run"], "best": improve.score(st["proof_run"], best["profile_id"], ("holdout",))}
            st["phase"] = "package"
            save()
        elif st["phase"] == "package":
            st["artifact_id"] = _package(ctx, w, st)
            st["phase"] = "done"
            save()
            h = (st["fix"].get("holdout") or {}).get("best") or {}
            ctx.log("factory.finished", f"{name} v{st['fix']['best']['version']} packaged; held-out verified {_pct(h.get('success_rate'))}", {"artifact_id": st["artifact_id"]})
    return {"name": name, "draft": st["draft"], **st["fix"], "artifact_id": st["artifact_id"]}


def _pct(x: float | None) -> str:
    return "not measured" if x is None else f"{x:.0%}"


def export_spec(manifest: WorldManifest, profile: AgentProfile, name: str) -> dict[str, Any]:
    """What the packaged agent needs: its instructions with the placeholders filled, and each tool with its HTTP mapping."""
    role = agent_role(manifest)
    r = manifest.role(role)
    prompt = (profile.system_prompt.replace("{actor_id}", name).replace("{role}", role)
              .replace("{instructions}", "Help the customers who contact you with their requests in this application."))
    prompt += f"\n\nYour role: {r.description if r else role}\n\nIf a tool result says the outcome is unknown, check the current state before repeating any change."
    tools = []
    for t in manifest.tools:
        if role not in t.roles:
            continue
        guidance = profile.tool_guidance.get(t.name)
        tools.append({"name": t.name, "description": (t.description + (f"\nGuidance: {guidance}" if guidance else ""))[:1000], "service": t.service,
                      "method": t.method, "path": t.path, "graphql": t.graphql, "mutating": t.mutating, "parameters": t.json_schema(),
                      "params": [{"name": x.name, "location": x.location} for x in t.params]})
    return {"name": name, "version": profile.version, "role": role, "model": MODEL, "thinking": True, "system_prompt": prompt,
            "services": sorted({t["service"] for t in tools}), "tools": tools}


def _package(ctx: JobContext, w: dict[str, Any], st: dict[str, Any]) -> str:
    from ..db.models import AgentProfileRow

    best = st["fix"]["best"]
    with session() as s:
        row = s.get(AgentProfileRow, best["profile_id"])
        profile = AgentProfile.model_validate(row.spec)  # type: ignore[union-attr]
    spec = export_spec(w["manifest"], profile, profile.name)
    causes = next(iter(run_failures(best["run_id"], splits=autofix.PRACTICE, profile_id=best["profile_id"]).values()), {}).get("causes", [])
    proof = proof_report(w, st, spec, causes)
    out_dir = settings().artifacts_dir / ctx.project_id / "agents"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{spec['name']}-v{spec['version']}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{spec['name']}/agent.json", json.dumps(spec, indent=2))
        z.writestr(f"{spec['name']}/agent.py", AGENT_PY)
        z.writestr(f"{spec['name']}/PROOF.md", proof)
        z.writestr(f"{spec['name']}/README.md", readme(spec))
    return _artifact(ctx, ctx.project_id, "agent", path.name, path, {"profile_id": best["profile_id"], "world_version_id": ctx.payload["world_version_id"]})


def proof_report(w: dict[str, Any], st: dict[str, Any], spec: dict[str, Any], causes: list[dict[str, Any]]) -> str:
    fix, draft = st["fix"], st["draft"]
    best, original = fix["best"], fix["original"]
    held = fix.get("holdout") or {}
    lines = [
        f"# Proof: {spec['name']} v{spec['version']}", "",
        f"Built and verified by Rehearsal's Agent Factory on {datetime.now(timezone.utc):%Y-%m-%d} for the **{w['name']}** world, version {w['version']}.",
        "Every outcome below was decided by read-only checks on the application's own database, with the default stress layer on:",
        "a refused first write that must be retried, and a repeated request that must not be done twice.", "",
        "## Scores", "", "| Version | Train and dev jobs | Held-out jobs (never used to improve it) |", "|---|---|---|",
        f"| v{draft['version']}, the draft | {_pct(original['score'].get('success_rate'))} | {_pct((held.get('original') or {}).get('success_rate')) if held.get('original') else '–'} |",
    ]
    if best["profile_id"] != original["profile_id"] or not held.get("original"):
        lines.append(f"| v{best['version']}, packaged | {_pct(best['score'].get('success_rate'))} | {_pct((held.get('best') or {}).get('success_rate'))} |")
    lines += ["", "## How it was hardened", ""]
    lines += [f"- Round {r['round']}: v{r['version']} verified {_pct(r['score'].get('success_rate'))}, {'kept' if r['accepted'] else 'discarded'}. {r.get('rationale', '')[:300]}" for r in fix["rounds"]] or ["- The draft needed no rounds."]
    lines += ["", "## Remaining failure causes on train and dev", ""]
    lines += [f"- {c['label']}: {c['count']} episode{'s' if c['count'] != 1 else ''}. {c['fix']}" for c in causes] or ["- None."]
    lines += ["", "Results hold for this world version. Re-run the proof after the application changes: `rehearsal gate` in CI."]
    return "\n".join(lines) + "\n"


def readme(spec: dict[str, Any]) -> str:
    urls = "\n".join(f"export APP_URL_{s.upper()}=https://...      # base address of the {s} service" for s in spec["services"][1:])
    return f"""# {spec['name']} v{spec['version']}

An AI agent for the **{spec['role']}** role, built and verified by Rehearsal. PROOF.md has its scores.

```bash
pip install openai httpx
export NEBIUS_API_KEY=...                # Nebius Token Factory; it runs on {spec['model']}
export APP_URL=https://your-app.example  # base address of your application's API
{urls}
export APP_AUTH="Authorization: token ..."   # the header for an account of the {spec['role']} role
python agent.py
```

Type as the customer. The agent works through your application's real API with {len(spec['tools'])} tools. Every
change asks for your confirmation first; set `CONFIRM_WRITES=0` only after you trust it. `MODEL` and
`MODEL_BASE_URL` select another OpenAI-compatible model.
"""


AGENT_PY = '''"""An AI agent built and verified by Rehearsal. See README.md to run it and PROOF.md for its scores."""

import json
import os
from pathlib import Path
from urllib.parse import quote

import httpx
from openai import OpenAI

SPEC = json.loads(Path(__file__).with_name("agent.json").read_text(encoding="utf-8"))
TOOLS = {t["name"]: t for t in SPEC["tools"]}
llm = OpenAI(base_url=os.environ.get("MODEL_BASE_URL", "https://api.tokenfactory.nebius.com/v1"), api_key=os.environ["NEBIUS_API_KEY"])
MODEL = os.environ.get("MODEL", SPEC["model"])
EXTRA = {"chat_template_kwargs": {"enable_thinking": SPEC.get("thinking", True)}} if "MODEL" not in os.environ else {}


def headers():
    name, _, value = os.environ.get("APP_AUTH", "").partition(":")
    return {name.strip(): value.strip()} if value else {}


def call(tool, args):
    """Turns a tool call into the HTTP request the application expects."""
    path, query, body, variables = tool["path"], {}, {}, {}
    for p in tool["params"]:
        if p["name"] not in args:
            continue
        value = args[p["name"]]
        if p["location"] == "path":
            path = path.replace("{" + p["name"] + "}", quote(str(value), safe=""))
        elif p["location"] == "query":
            query[p["name"]] = value
        elif p["location"] == "variables":
            variables[p["name"]] = value
        else:
            body[p["name"]] = value
    payload = {"query": tool["graphql"], "variables": variables} if tool.get("graphql") else body["body"] if list(body) == ["body"] else body or None
    if tool["mutating"] and os.environ.get("CONFIRM_WRITES", "1") != "0":
        answer = input(f"\\n  allow {tool['method']} {path} {json.dumps(payload)[:300]}? [y/N] ")
        if answer.strip().lower() != "y":
            return {"error": "the operator did not allow this change"}
    base = os.environ.get("APP_URL_" + tool["service"].upper()) or os.environ["APP_URL"]
    r = httpx.request(tool["method"], base.rstrip("/") + path, params=query or None, json=payload, headers=headers(), timeout=30)
    try:
        return {"status": r.status_code, "body": r.json()}
    except ValueError:
        return {"status": r.status_code, "body": r.text[:4000]}


def fn(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required}}}


FUNCTIONS = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in SPEC["tools"]]
FUNCTIONS += [fn("reply_to_customer", "Send a message to the customer.", {"text": {"type": "string"}}, ["text"]),
              fn("complete", "Declare the customer's latest request handled and verified.", {"summary": {"type": "string"}}, ["summary"])]


def main():
    messages = [{"role": "system", "content": SPEC["system_prompt"]}]
    print(f"{SPEC['name']} v{SPEC['version']} is ready. Type as the customer; Ctrl+D quits.")
    while True:
        try:
            messages.append({"role": "user", "content": input("\\ncustomer> ")})
        except EOFError:
            return
        for _ in range(25):
            reply = llm.chat.completions.create(model=MODEL, messages=messages, tools=FUNCTIONS, extra_body=EXTRA).choices[0].message
            messages.append(reply.model_dump(exclude_none=True))
            if not reply.tool_calls:
                print(f"agent> {reply.content}")
                break
            done = False
            for tc in reply.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                if tc.function.name == "reply_to_customer":
                    print(f"agent> {args.get('text', '')}")
                    result = {"delivered": True}
                elif tc.function.name == "complete":
                    print(f"  [done: {args.get('summary', '')}]")
                    result, done = {"ok": True}, True
                elif tc.function.name in TOOLS:
                    result = call(TOOLS[tc.function.name], args)
                else:
                    result = {"error": f"unknown tool {tc.function.name}"}
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, default=str)[:12000]})
            if done:
                break


if __name__ == "__main__":
    main()
'''
