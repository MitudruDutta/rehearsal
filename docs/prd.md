# Product requirements: Rehearsal

| | |
|---|---|
| **Project** | Rehearsal |
| **Document** | Product requirements (step 2 of 3: [scope](scope.md) → PRD → [spec](spec.md)) |
| **Version** | 0.1.2 (`rehearsal-kit` on PyPI) |
| **Status** | Implemented, except where a requirement says "planned" |
| **Last updated** | 2026-10-27 |

## 1. Overview

Rehearsal tests an AI agent on a working copy of a real application before the agent ships. The World Compiler builds a sandboxed practice world from the application's source; the agent works through jobs while a simulated customer talks to it and faults are injected; read-only checks on the application's own database decide every outcome. The product reports a readiness verdict with evidence, proposes a better agent version from the failures, and compares versions on jobs neither has seen.

This document turns the [scope](scope.md) into requirements. The [spec](spec.md) describes how each one is built.

## 2. Goals and non-goals

**Goals**

1. Make "is this agent ready?" answerable with evidence from the application's records.
2. Remove the weeks of hand-built test harness per application.
3. Make every test trustworthy: no job ships unless it provably separates good behaviour from bad.
4. Let a team improve an agent and prove the improvement on held-out jobs.
5. Catch an agent change that makes things worse before it merges.

**Non-goals** (see [scope §6](scope.md#6-out-of-scope)): closed SaaS applications, browser-only worlds, weight training, live-data drift, per-job VM isolation.

## 3. Users

| Persona | Goal | Main surface |
|---|---|---|
| **Agent engineer** | Build a world for their app, run their agent, read why episodes failed | CLI, SDK, console |
| **Engineering lead** | Decide whether an agent can launch | Console readiness board |
| **AI assistant user** | Drive Rehearsal from Claude Code, Codex or Cursor | MCP server and agent plugin |
| **Operator** | Run Rehearsal on their own infrastructure | Docker Compose, docs |

## 4. User journeys

1. **First result:** sign up → add an application (or import a pinned example) → build a world → run an evaluation → read the verdict.
2. **Diagnose:** open a failed episode → see the actions, messages, injected faults and which database checks failed.
3. **Fix:** start the fix loop from a finished run → watch each round: its reason, its score against the best version, kept or discarded → read the held-out comparison of the best version and the original.
4. **Guard a change:** open a pull request that edits the agent's instructions → the check rehearses it next to `main` → the pull request fails with a report when the change does worse.
5. **Bring your own agent:** drive episodes from your own code in any language through the episode API.
6. **Self-host:** start the stack with Docker Compose, create the first admin, sign in.

## 5. Functional requirements

### 5.1 Applications

| ID | Requirement |
|---|---|
| FR-1 | A user adds an application by git repository and full commit, or by uploaded source archive, plus the container images it runs from. |
| FR-2 | A user can import a catalog of pinned open-source applications (Gitea, Chatwoot, Vikunja, WordPress, Mattermost, Odoo, Saleor, Easy!Appointments). |
| FR-3 | Owner policies (business rules in plain text) can be attached to an application and are given to the compiler. |
| FR-4 | Image references are validated: a full registry reference, never a value that could be read as a command-line option. |

### 5.2 World Compiler

| ID | Requirement |
|---|---|
| FR-5 | The compiler inspects the source, plans the runtime, starts the application in an isolated sandbox with no internet, discovers its API, seeds fictional data, chooses tools per role, writes jobs, validates and repairs them, and publishes an immutable world version. |
| FR-6 | Each phase is checkpointed; after a worker restart the build resumes from the last completed phase. |
| FR-7 | Outside services the application calls (payments, email, shipping, webhooks, SMTP) are replaced by local stand-ins that record every effect. |
| FR-8 | Every world covers several kinds of stress: changed requests, a write that times out after it succeeded, application refusals, role boundaries, social engineering, instructions hidden in data, missing information, privacy, conflicting requests. |
| FR-9 | Jobs are split into train, dev and held-out sets by job family, so variants of one job never appear in two sets. |
| FR-10 | A published world can be re-checked; jobs found unfair are withdrawn and no longer count. |

### 5.3 Job validation

| ID | Requirement |
|---|---|
| FR-11 | A job is published only if, from a fresh reset: its setup runs; doing nothing does not pass; the reference trajectory passes with no violation; every negative trajectory fails; replaying the reference gives the same result. |
| FR-12 | No language model takes part in those five decisions. |

### 5.4 Evaluation

| ID | Requirement |
|---|---|
| FR-13 | An evaluation runs agent versions over chosen job sets; by default every job runs twice with the stress layer on. |
| FR-14 | Every episode starts from the world's published snapshot. |
| FR-15 | The agent sees only what a real client of its role would see; it never sees the checks, other roles' credentials, or held-out jobs. |
| FR-16 | A simulated customer takes its goal and facts from the job; a model only phrases its replies, and goal changes happen only through scheduled events. |
| FR-17 | Each episode is scored by read-only checks on the database and the effect journal: goal reached, hard violations, duplicate effects, false "done" claims, recovery after faults. |
| FR-18 | An episode interrupted by a worker restart resumes against the same sandbox. |

### 5.5 Verdict, improvement and comparison

| ID | Requirement |
|---|---|
| FR-19 | The readiness board marks an agent and application pair **ready to pilot** when it has at least 3 scored episodes on jobs that version never learned from, 80% or more verified, no rule violations and no false "done" claims. |
| FR-20 | The improvement agent reads only train and dev episodes (never held-out ones) and edits only the system prompt and per-tool guidance. |
| FR-21 | Two runs on the same world version can be compared side by side. |
| FR-22 | Verified train and dev trajectories can be exported as a dataset; held-out jobs and checks are never exported. |
| FR-35 | The fix loop runs 1 to 5 rounds in one job. Each round proposes a version from the best version's failures, shown the ideas that did not help, rehearses it on every train and dev job, and keeps it only if it verifies more with no more rule violations or false completions. |
| FR-36 | After the rounds, or when every train and dev job passes, the original and the best version run side by side on held-out jobs. No held-out run happens when nothing beat the original. |
| FR-37 | The fix loop saves every phase and resumes after a worker restart; stopping it fails its own runs and keeps every version made. It is refused for a bring-your-own agent, an unfinished run, or a run without finished train or dev episodes. |
| FR-38 | `rehearsal gate` and a GitHub Action rehearse an agent change (a version made from an instructions file, reused when unchanged) next to a baseline, and exit 0 (passed), 1 (failed) or 2 (could not run). The defaults fail on any rule violation and on any regression against the baseline. |

### 5.6 Interfaces

| ID | Requirement |
|---|---|
| FR-23 | Versioned REST API with live event streams; long operations return a job id. |
| FR-24 | CLI and Python SDK (`pip install rehearsal-kit`); `rehearsal login` signs in through the browser. |
| FR-25 | MCP server and agent plugin, so an AI assistant can build worlds, run evaluations and act as the agent under test. |
| FR-26 | Web console: overview and readiness board, applications and their worlds, agents, runs, comparisons, settings and billing. |

### 5.7 Hosted service

| ID | Requirement |
|---|---|
| FR-27 | Sign-in with Google or email and password; open sign-up creates a workspace. |
| FR-28 | Plans: Free (1 application, 1 build, 40 episodes a month in quiet hours), Pro $29 a month, Team $149 a month, Enterprise; top-ups of 1,000 episodes ($30) and one world build ($15). Payments through Dodo Payments. |
| FR-29 | A job starts only when every model it may use has a known price; every job has a spending cap and every workspace a monthly allowance. |
| FR-30 | Operator admins can set any workspace's plan and grant extras. |

### 5.8 Documentation site

| ID | Requirement |
|---|---|
| FR-31 | A new user can follow the docs alone from sign-up to a first verified result. |
| FR-32 | The docs describe only shipped behaviour; reference pages (CLI, MCP tools, configuration) are generated from the code and checked in CI. |
| FR-33 | Every page is available as Markdown and the site publishes `llms.txt`; "Ask AI" answers only from the docs. |

### 5.9 Observability and provenance

| ID | Requirement |
|---|---|
| FR-34 | Every build, episode and improvement run keeps a full timeline (model calls, tool calls, checks, cost), with secrets masked before anything is stored. |
| FR-39 | Builds, runs and fix loops show model usage by role: model and provider, reasoning on or off, calls, time per call, tokens and spend. |
| FR-40 | With a Tavily key, a build researches real use of the application on the web before planning jobs; at least half the jobs cite pages the researcher was shown, the world page shows the findings, and episodes never use the live web. |

## 6. Non-functional requirements

| ID | Area | Requirement |
|---|---|---|
| NFR-1 | Correctness | Outcomes come from application state, never from the agent's own claims or a model's opinion. |
| NFR-2 | Reliability | Jobs survive worker crashes (leases, heartbeats, checkpoints); a job that keeps losing its lease fails instead of looping. |
| NFR-3 | Isolation | Each world runs on its own network without internet; containers run with memory, CPU and process limits and dropped privileges. |
| NFR-4 | Tenancy | Every lookup is scoped to the caller's project; world versions and approved jobs are immutable. |
| NFR-5 | Security | API keys are hashed; request bodies are capped (1 MB, 500 MB for source uploads); security headers on every response; the worker holds no payment or session secrets. |
| NFR-6 | Cost | Model spend is capped per job and per month; idle compute sleeps. |
| NFR-7 | Portability | The server runs on Linux with Docker; the CLI and SDK run anywhere with Python 3.11+. |
| NFR-8 | Quality | Unit and integration tests run in CI on every push. |

## 7. Acceptance criteria

| Scope criterion | Accepted when |
|---|---|
| S1 | A catalog application builds into a published world whose jobs passed all five validation gates. |
| S2 | A scripted agent that claims "done" without acting fails; a duplicate effect after a timeout is counted. |
| S3 | `rehearsal improve` produces a new version and `rehearsal compare` shows both runs on held-out jobs. |
| S4 | The docs' quickstarts take a new user to a first result. |
| S5 | rehearsalkit.xyz serves the console, accepts payments, and refuses to start an unpriced job. |
| S6 | Each role's model calls go to NVIDIA Nemotron models on Nebius Token Factory. |
| S7 | `rehearsal autofix` returns every round with its score and decision, and the held-out scores of the original and the best version. |
| S8 | `rehearsal gate` exits 1 with a report when the change verifies less than the baseline or breaks a rule, and exits 2, not 1, when the run cannot start. |

## 8. Metrics

- World build success rate, time and cost per build.
- Share of written jobs that pass validation; jobs withdrawn after re-check.
- Episodes per run, verified rate, violations and false completions per agent version.
- Time from sign-up to first verdict.
- Model spend per workspace against its allowance.

## 9. Release status

| Area | Status |
|---|---|
| World Compiler, validation, evaluation, verdict, improvement, comparison | Shipped |
| Fix loop, pull request checks, model usage by role, web research for builds | Shipped (October 2026) |
| CLI, SDK, MCP server, agent plugin, console, docs | Shipped (`rehearsal-kit` 0.1.2) |
| Hosted service with plans and live payments | Shipped (rehearsalkit.xyz) |
| Weight training, world bundle replay | Planned (`rehearsal train` and `rehearsal run-bundle` report "not implemented") |
| Browser-only worlds, per-job VM isolation | Planned |
