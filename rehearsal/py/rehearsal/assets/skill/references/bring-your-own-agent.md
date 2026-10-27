# Bring your own agent

Use this when the agent under test is code that the user runs (LangGraph, OpenAI Agents SDK, smolagents, CrewAI, a custom loop), or when you yourself act as the agent.

Rehearsal does not run a model for such an agent. It runs the world, the simulated customer and the checks. It sends each turn to the agent over the API and applies the action the agent sends back. The agent's own model calls are billed by its own provider; the world and the customer count against the Rehearsal allowance.

## Set up

1. `create_agent(name, bring_your_own=True)`, or CLI `rehearsal profiles create NAME --external`.
2. Start a run with it: `run_evaluation(world_version_id, [agent_id], splits=["dev"])`. Ask first.
3. Start the agent loop below, quickly. Each turn waits 10 minutes for an action, then the episode ends with `external_timeout`.

## The turn protocol

Each turn belongs to one actor in one episode. A run can have several episodes waiting at the same time, one per sandbox.

1. `waiting_turns(run_id)` returns, per waiting episode:
   - `actor`: the actor you play now (for example `mira`, the maintainer).
   - `new_messages`: what arrived since your last action. The first turn has the role instructions; later turns have tool results, customer messages and teammate messages.
   - `tools`: the tools you may call now, with JSON Schema parameters.
2. Choose exactly one tool, then `take_action(episode_id, actor, tool, arguments)`. You get the tool result.
3. Repeat until no turns wait and `run_results` shows `finished`.

Keep your own memory per episode and actor: everything the actor has seen so far. A turn has only the new messages.

## Built-in tools

Besides the application's tools, a turn can offer:

| Tool | Use |
|---|---|
| `reply_to_customer(text)` | Talk to the customer (when the customer talks over the message bus). Each contact interrupts them; keep contacts necessary |
| `send_message(to, text)` | Message a teammate actor, for example ask an administrator to do a privileged change |
| `retry_operation(operation_id)` | Safely re-send an earlier write with its original idempotency key, after an `UNKNOWN` result. Returns the original effect if it already happened |
| `wait()` | Wait for new messages (for example a teammate's answer) |
| `complete(summary)` | Declare the customer's latest request done and verified. Only one actor has it |

When the customer talks through the application (a chat channel, an issue comment), their messages arrive as notifications. You answer with the application's own tools.

## Behave like a careful production agent

1. Read the customer's **latest** message before every write. Requests change mid-way.
2. When a write returns "not carried out: a new message from the customer arrived", read the new message. Then decide again.
3. After an `UNKNOWN` (timed out) result, do not repeat the write blindly. Read the state first, or use `retry_operation`.
4. Find ids with read tools. Never guess an id.
5. Call `complete` only after a read shows the work is done.
6. Do not contact the customer more than necessary.

## Python loop (the user's own agent)

```python
import uuid
from rehearsal.sdk import Rehearsal

rh = Rehearsal()                      # REHEARSAL_API_KEY, REHEARSAL_URL
run = rh.evaluations.create(WORLD_VERSION_ID, [EXTERNAL_AGENT_ID], splits=["dev"])
memory = {}                           # (episode_id, actor) -> conversation so far

while rh.runs.get(run["run_id"])["status"] not in ("finished", "failed", "cancelled"):
    for ep in rh.runs.episodes(run["run_id"]):
        if ep["status"] != "running":
            continue
        obs = rh.external.observation(ep["id"])
        if not obs.get("awaiting_action"):
            continue
        turn = obs["turn"]["data"]
        history = memory.setdefault((ep["id"], turn["actor"]), [])
        history += turn["new"]
        tool, args = my_agent_decide(history, turn["tools"])   # the user's agent: one tool call
        result = rh.external.act(ep["id"], turn["actor"], tool, args, idempotency_key=uuid.uuid4().hex)
        history.append({"role": "tool", "name": tool, "content": str(result)})
```

## TypeScript loop (the same, with the npm package `rehearsal-kit`)

```ts
import { randomUUID } from "node:crypto";
import { Rehearsal, type Json } from "rehearsal-kit";

const rh = new Rehearsal();                // REHEARSAL_API_KEY, REHEARSAL_URL
const run = await rh.evaluations.create(WORLD_VERSION_ID, [EXTERNAL_AGENT_ID], ["dev"]);
const memory = new Map<string, Json[]>();  // episode id and actor -> conversation so far

while (!["finished", "failed", "cancelled"].includes((await rh.runs.get(run.run_id)).status)) {
  for (const ep of await rh.runs.episodes(run.run_id)) {
    if (ep.status !== "running") continue;
    const obs = await rh.external.observation(ep.id);
    if (!obs.awaiting_action) continue;
    const turn = obs.turn.data;
    const history = memory.get(`${ep.id} ${turn.actor}`) ?? [];
    memory.set(`${ep.id} ${turn.actor}`, history);
    history.push(...turn.new);
    const [tool, args] = await myAgentDecide(history, turn.tools);   // the user's agent: one tool call
    const result = await rh.external.act(ep.id, turn.actor, tool, args, randomUUID());
    history.push({ role: "tool", name: tool, content: JSON.stringify(result) });
  }
}
```

`turn["tools"]` uses the OpenAI function format (`{"type": "function", "function": {"name", "description", "parameters"}}`). Most agent frameworks accept it directly as their tool list.

## Acting as the agent yourself (from an assistant)

You can play the agent through the MCP tools. It is a good way to show the user how a careful agent behaves, or to check that a job is fair.

- Play only the actor named in the turn. Use only the offered tools.
- Do not read the job's checks or the holdout job specs to pass. The point is to behave as a real agent would, from the messages alone.
- Report what you did and the verdict from `run_results`.
