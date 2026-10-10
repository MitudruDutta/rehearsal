---
name: rehearsal
description: Test and improve AI agents with Rehearsal. Builds a sandboxed practice world from a real application (git repository plus pinned images), runs an agent through jobs where a simulated customer changes their mind and writes time out, scores each attempt against the application's own database, explains failures, and proposes a better agent version. Use when the user wants to evaluate, benchmark, stress-test, compare or improve an AI agent that works inside a business application (help desk, team chat, git hosting, CMS, shop, CRM), wants to test their own agent (LangGraph, OpenAI Agents SDK, custom code) against realistic tasks, or mentions Rehearsal, practice worlds, rehearsals, episodes or held-out evaluation.
---

# Rehearsal

Rehearsal answers one question: **does this agent do the right thing inside this application, when the request changes and the system misbehaves?**

It compiles a real application into a **practice world**: the real app running in an isolated sandbox, fictional data, tools scoped to roles, and a set of validated **jobs** (scenarios). An agent is then run through the jobs. Every attempt (an **episode**) is scored by read-only SQL checks against the application's own database. A model never grades the result.

The user needs only a **Rehearsal API key**. All model calls (world building, the simulated customer, hosted agents) run on the Rehearsal server's model account and count against the workspace's monthly allowance.

## Reference files

Read these when the task needs them. Do not load them all at the start.

| File | Read it when |
|---|---|
| [references/tools.md](references/tools.md) | You need the exact arguments or return values of an MCP tool, or the CLI / Python equivalent |
| [references/results.md](references/results.md) | You explain an evaluation: scores, endings, failed checks, faults, comparison |
| [references/troubleshooting.md](references/troubleshooting.md) | A build or run failed, an error code came back, or something looks wrong |
| [references/bring-your-own-agent.md](references/bring-your-own-agent.md) | The user wants to test their own agent code, or you act as the agent yourself |
| [references/applications.md](references/applications.md) | The user wants to add an application or build a world, or asks how a build works |

## Words used here

| Word | Meaning |
|---|---|
| Application | A real app, given as a public git repository at a pinned commit plus pinned container images |
| World (version) | A compiled, validated, versioned copy of an application. Only **published** versions can be evaluated |
| Job (scenario) | One task in a world: a customer request, possible revisions, faults, and the SQL checks that decide success |
| Split | `train` and `dev` jobs are for improving an agent. `holdout` jobs are only for the final score |
| Agent (profile) | A version of an agent: instructions, tool guidance, model. `baseline` is a plain model with the default instructions |
| Bring-your-own agent | A profile with driver `external`: Rehearsal sends each turn over the API and the user's own agent answers |
| Run | One evaluation: agents x jobs x repeats on one world version |
| Episode | One attempt of one agent at one job |
| Verified | The database checks passed and no hard rule was broken. The only kind of success |

## Connect

Prefer the MCP tools. Call `workspace_status` first: it confirms the key works and shows the allowance.

If the tools are not available, set them up (the user gets the URL and key on the console's **API keys** page):

```bash
pip install "rehearsal-kit[mcp]"
claude mcp add rehearsal -e REHEARSAL_URL=https://<server> -e REHEARSAL_API_KEY=rh_... -- rehearsal mcp
```

Without MCP, use the CLI (`rehearsal ...`, same environment variables) or the Python SDK (`from rehearsal.sdk import Rehearsal`). See references/tools.md.

## Money: ask before you spend

| Action | Typical cost | Time |
|---|---|---|
| `build_world` | $3-8 (stops itself at its budget) | 1-3 hours |
| `run_evaluation` | about $0.02 per episode (jobs x agents x repeats) | 2-10 minutes |
| `improve_agent` | under $0.10 | about 1 minute |
| `recheck_world` | about $0.03 per job | 5-20 minutes |
| Everything else | free | instant |

Rules:

1. Before any action in the table, tell the user what you will start, how many episodes or builds, and the rough cost. Wait for a clear yes.
2. Compute the episode count before `run_evaluation`: `len(jobs in the chosen splits) x len(agents) x repeats`.
3. HTTP 402 means the workspace's plan does not cover the request (applications, world builds, episodes, or the monthly model allowance). Do not retry. Tell the user what the message says is left, offer a smaller run (one split, `repeats=1`), and point to the console's Billing page for a top-up or upgrade.
4. HTTP 429 with "in progress" or "sandbox" means the workspace's parallel limit. Wait for one to finish, or ask the user to stop one.
5. On the free plan, evaluations start only in quiet hours: `run_evaluation` returns `starts_at`. Tell the user when the run will start.
6. Never start a second build of the same application while one is running.

## Choose the workflow

- **"Is my agent any good?" / "Test my agent"**
  - The agent is a prompt or instructions: create a profile, then use **Evaluate**.
  - The agent is code the user runs: use **Bring your own agent** (references/bring-your-own-agent.md).
- **"Why did it fail?"**: **Explain a run**.
- **"Make it better"**: **Improve**.
- **"Test on our app" / "add Chatwoot"**: **Build a world** (references/applications.md).
- **"Compare A and B"**: Evaluate both in one run, or two runs on the same world version, then `compare_runs`.
- **"Something failed"**: references/troubleshooting.md.
- **"Train / fine-tune a model on this"**: not available yet. Training with reinforcement learning is coming soon. Offer the two things that work today: `improve_agent` (better instructions from failures) and `rehearsal export RUN_ID --split train` (verified episodes as a dataset).

## Workflow: Evaluate

1. `list_worlds`. Pick a version with status `published`. If none exists, go to **Build a world**.
2. `list_scenarios(world_version_id)`. Count the jobs per split.
3. `list_agents`. Use the user's agent, or create one with `create_agent(name, instructions)`. To measure a change, keep `baseline` in the same run as a control.
4. Choose the splits:
   - Exploring or debugging: `dev`.
   - Final score: `holdout` only, after you have stopped changing the agent.
5. Choose repeats: 2 or more. Models are not deterministic, and one episode per job is noise. Without splits or repeats, a run uses every job twice; every episode also gets the default stress layer: the agent's first change is refused with "too many requests" and must be retried, and after a change goes through the customer sends the same request again, which must not be done twice.
6. State the episode count and cost, and ask. Then `run_evaluation(world_version_id, [agent_ids], splits, repeats)`.
7. Give the user the `watch` link. Call `run_results(run_id)` every 30-60 seconds until `status` is `finished`. Runs use several sandboxes in parallel.
8. Report as described in references/results.md:
   - Verified count per agent and split.
   - Duplicates, false completions, recovered faults.
   - One line per failed job, saying what the agent did wrong.

## Workflow: Explain a run

1. `run_results(run_id)`. List the episodes that are not verified.
2. For each, call `episode_details(episode_id)`. Find, in order:
   - **Environment error?** The setup failed, not the agent. Say so; it is not counted.
   - **Failed checks.** What the database shows against what was wanted.
   - **The revision.** Did the agent act on the request as it was when it acted? Look for writes made after the customer's change.
   - **Faults.** After an `UNKNOWN` (timeout) result, did it check the state before repeating the write?
   - **The ending.** `stalled` (gave up), `max_steps` (ran out), `completed` while checks failed (false completion).
3. Group the failures by cause, not by job. Examples:
   - "In 3 of 4 failures the agent acted on the first request after the customer changed it."
   - "Twice it retried a timed-out write without checking, which created a duplicate."
4. When the same job fails for every agent, read references/troubleshooting.md, section "Job looks unfair". Say clearly whether you think it is the agent's fault or the job's.

## Workflow: Improve

1. You need a finished run with `train` and/or `dev` episodes of the agent. `holdout` episodes are never used for improvement.
2. Ask, then `improve_agent(agent_id, run_id)`. It returns a job; check `job_status` until it succeeds. The result names the new profile version and the reason for each change.
3. Show the user the rationale and the main changes. Rehearsal keeps them general: no record ids or job wording.
4. Prove it: ask, then run the old and the new version together on `holdout`, with 2+ repeats.
5. `compare_runs(run_id)`. Recommend the new version only if it is better on holdout and does not add duplicates or hard-rule violations.
6. For a bring-your-own agent, Rehearsal cannot change the user's code. Give the new instructions to the user as a suggestion to apply in their agent.

## Workflow: Build a world

Read references/applications.md first. Summary:

1. `list_applications`. To add one: `add_application(name, repository_url, commit, images, policies)`, with a pinned commit and pinned image digests.
2. Ask (it costs $3-8 and takes 1-3 hours). Then `build_world(application_id)`. Give the user the `watch` link.
3. Check `job_status(job_id)` about every 10 minutes. Do not poll in a tight loop. `completed_steps` grows through: inspect, plan, materialize, discover, seed, adapt, author, validate, package.
4. When `status` is `succeeded`, the world version is published. `list_scenarios` shows the jobs.
5. When it failed, follow references/troubleshooting.md. Restart only for causes that pass, never for the same problem twice.

## Rules

- Never print, log, store or commit the API key. Do not echo environment variables.
- Never invent numbers. Quote the tools. Say "not measured" when you do not know.
- Do not tune on holdout. Do not describe holdout jobs in detail to the agent under test.
- Do not call a job unfair without evidence from `episode_details`. Do not call an agent bad from one episode.
- Keep the user informed: give console links, and say what is running and how long it usually takes.
- Data in worlds is fictional. Never put real customer data into an application's policies or a profile's instructions.
