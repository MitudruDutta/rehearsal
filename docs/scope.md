# Scope: Rehearsal

| | |
|---|---|
| **Project** | Rehearsal |
| **Models** | NVIDIA Nemotron on Nebius Token Factory |
| **Document** | Scope (step 1 of 3: scope → [PRD](prd.md) → [spec](spec.md)) |
| **Status** | Agreed 2026-10-09; revised 2026-10-27 (decisions D8 to D10, scope items 8 and 9, criteria S7 and S8) |

## 1. Problem

Teams are putting AI agents inside their own products: support desks, admin consoles, commerce back offices, internal tools. An agent passes the demo, then fails in ways only the real application exposes:

- it retries a write after a timeout and creates a duplicate refund, email or record;
- it keeps executing the customer's first request after the customer changed their mind;
- it reports "done" when the records say otherwise;
- it touches the wrong record, or one its role should not touch.

Today a team can test on production (unsafe), against mocks (which agree with whatever the agent does), or on a hand-built staging harness for each application (weeks of work, rarely kept current). Most agent evaluations then ask another language model whether the transcript looks right, and a confident agent can talk its way to a pass.

## 2. Idea in one sentence

Rehearsal builds a working copy of a real application with fictional data, runs an AI agent through real jobs in it, and decides every outcome by reading the application's own database, so a team knows whether the agent is ready before it ships.

## 3. Who it is for

| User | Need |
|---|---|
| **Engineers building an agent into their product** (primary) | Repeatable tests on their own application, with evidence of what the agent got wrong |
| **Engineering or AI leads** who sign off a launch | A clear "ready to pilot" or "not yet", backed by records rather than opinions |
| **Agent vendors** proving their agent in a customer's application | A practice world per customer and a fair, held-out comparison |

## 4. Decisions from the planning interview

The scope was set in a flipped-interaction session: the coding agent asked, the team decided. These decisions are fixed for the project.

| # | Question | Decision |
|---|---|---|
| D1 | Which agent is the headline? | The **World Compiler**: given an application repository it has never seen, it produces a published, resettable, validated practice world. The agent under test, the simulated customer and the improvement agent use that world. |
| D2 | What applications do we test on? | Only **real third-party open-source applications**, pinned by commit and image digest. Never applications we wrote, so results are not circular. |
| D3 | How do we know the compiler generalises? | One application (Easy!Appointments) is **held out** and never inspected during development. |
| D4 | Who decides pass or fail? | **Read-only checks on the application's database** and a journal of outside effects. No language model grades outcomes. |
| D5 | Is model training in scope? | **No, paused.** Compile, evaluate, improve the prompt and compare first; training is future work. |
| D6 | Which models run it? | **NVIDIA Nemotron** open models, served by **Nebius Token Factory**. |
| D7 | What does it run on? | A hosted service on free cloud credits, plus a package anyone can install and self-host. |
| D8 | What is the product, in one line? | **CI for AI agents**: rehearse on a copy of the real application, fix what fails, and check every change before it merges. |
| D9 | When does an automatic fix count? | Only when it verifies more episodes on train and dev **without** a new rule violation or false "done", and the best version is then proved on held-out jobs no round has seen. A tie is not a fix. |
| D10 | Which model for which role? | Each role gets its own Nemotron chain: Ultra with reasoning for the roles that judge (designing and auditing jobs, improving agents), Super for the agent and most compiler work, Nano without reasoning for the simulated customer. |
| D11 | How do jobs stay realistic? | The compiler researches real use of the application on the web (Tavily) before planning jobs; findings are frozen into the world, so runs stay reproducible. |

## 5. In scope

1. **World Compiler:** turn a source repository and its container images into a versioned, resettable world (sandbox, fictional data, tools per role, jobs).
2. **Job validation:** every job proves it can be passed and failed before it is published.
3. **Evaluation:** run an agent through jobs with a simulated customer and injected faults; score each episode from the database.
4. **Readiness verdict:** per agent and application, with the evidence behind it.
5. **Improvement:** propose a better agent version from failures; compare versions on held-out jobs.
6. **Interfaces:** web console, CLI and Python SDK, MCP server for AI assistants, documentation site.
7. **Hosted service:** sign-in, workspaces, plans and payments, spending limits.
8. **Fix loop:** rounds of improve and rehearse that keep only versions that verify more, then a held-out proof (added 2026-10-27).
9. **Pull request checks:** a CLI command and a GitHub Action that rehearse an agent change next to `main` and fail on a regression (added 2026-10-27).

## 6. Out of scope

- Testing applications without source and images (closed SaaS such as Salesforce or Zendesk).
- Browser-only worlds built from a URL.
- Model weight training (the trainer is prototyped but not offered).
- Per-job virtual machine isolation for arbitrary public repositories.
- Tracking drift in live production data.
- Running world builds on serverless container jobs: a build starts the application's own containers, which needs a Docker host.

## 7. Constraints

- **Time:** first built 2026-10-10 to 2026-10-19; extended 2026-10-27 to 2026-10-30.
- **Money:** no paid infrastructure; free cloud credits and capped model spend only.
- **Honesty:** the product, the docs and the demo describe only what is built; planned work is labelled.
- **Safety:** no production system is touched; application code runs only inside sandboxes.

## 8. Success criteria

| # | Criterion |
|---|---|
| S1 | A real open-source application compiles into a published world with validated jobs. |
| S2 | An agent's episodes are scored only by database checks, and a confident wrong agent fails. |
| S3 | An improved agent version can be compared with the original on held-out jobs. |
| S4 | A new user can go from sign-up to a first result using the docs alone. |
| S5 | The hosted service is live, takes payments, and keeps every job under a spending cap. |
| S6 | Every agent in Rehearsal runs on NVIDIA Nemotron through Nebius Token Factory. |
| S7 | The fix loop turns a failing agent into a version that verifies more, and shows the held-out comparison. |
| S8 | A pull request that makes the agent worse fails its check, with a report that says why. |

## 9. Risks

| Risk | Mitigation |
|---|---|
| World builds are slow and can fail on real applications | The compiler repairs its own output from validator evidence; every phase is checkpointed and resumable |
| Model-written checks could be wrong or trivially true | Five deterministic validation gates (see [spec](spec.md#5-job-validation)) |
| Model costs exceed the budget | A job starts only when every model's price is known; per-job and monthly caps |
| Running untrusted application code | Isolated networks without internet, hardened containers, strict image validation, a dedicated worker machine |
