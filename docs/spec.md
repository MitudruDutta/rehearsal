# Technical specification: Rehearsal

| | |
|---|---|
| **Project** | Rehearsal |
| **Document** | Technical specification (step 3 of 3: [scope](scope.md) → [PRD](prd.md) → spec) |
| **Version** | 0.1.2 |
| **Status** | Describes the system as built; planned work is marked |
| **Last updated** | 2026-10-19 |

## 1. Architecture

```text
Browser console / CLI / Python SDK / MCP server
                    |
        API (FastAPI): auth, plans, limits, REST + live events
                    |
  PostgreSQL ── job queue (SKIP LOCKED, leases, checkpoints) ── domain tables + event log
                    |
        Workers: world_build · evaluation · improvement · export
                    |
        Runner: Docker sandbox per world instance
          ├─ internal network, no internet: the application's own services
          ├─ providers: stand-ins for payments, email, shipping, webhooks, SMTP (+ effect journal)
          └─ gateway: the only path from an actor to the application
                    |
        Oracle: read-only probes on the application's database + the journal
```

One database holds control flow (jobs) and domain state, so there is one source of truth. Workers are separate processes from the API; long work never runs inside a web request.

## 2. Code layout

| Package | Responsibility |
|---|---|
| `rehearsal/core/` | Typed contracts: world manifest, services, tools, roles, scenarios, checks (immutable once published) |
| `rehearsal/compiler/` | The World Compiler: pipeline, role tool loop, API discovery, stress categories, validation |
| `rehearsal/runner/` | Docker lifecycle, snapshots and reset, seeding, the action gateway |
| `rehearsal/providers/` | Emulated outside services and the world's edge proxy |
| `rehearsal/agents/` | Episode engine, simulated customer, model client with fallback chains |
| `rehearsal/evaluator/` | Oracle and read-only probes |
| `rehearsal/worker/` | Job handlers: build, evaluate, improve, export |
| `rehearsal/db/` | SQLAlchemy models, Alembic migrations, job queue, event log |
| `rehearsal/api/` | REST API, live event streams, auth, request limits, static console |
| `rehearsal/billing.py`, `rehearsal/pricing.py` | Plans and Dodo Payments; model price catalog and spend caps |
| `rehearsal/telemetry/` | neatlogs spans and secret masking |
| `rehearsal/sdk/` | Python client, CLI (28 commands), MCP server (18 tools) |
| `web/` | Console (Next.js static export, served by the API) |
| `docs/` | Documentation site (Fumadocs) and these planning documents |
| `infra/` | Docker Compose stack, Caddy, AWS CloudFormation |

## 3. Data model

Every project-owned row carries `project_id`, and every API lookup filters on it.

| Table | Holds |
|---|---|
| `organizations`, `projects`, `users`, `memberships`, `api_keys`, `cli_logins` | Tenancy, people, roles, hashed keys, terminal sign-in |
| `plan_credits`, `billing_events` | Granted extras and applied payment events |
| `applications`, `credentials` | Source (git commit or upload), images, owner policies |
| `worlds`, `world_versions`, `scenarios` | Published worlds (manifest, snapshot, content hash) and their jobs with split and status |
| `agent_profiles` | Versions of an agent: instructions, tool guidance, model |
| `runs`, `episodes`, `actions`, `messages` | Evaluations, attempts, what each actor did and said, oracle results |
| `events` | Append-only log written in the same transaction as the change it describes |
| `jobs`, `model_spend`, `artifacts` | Queue entries, spend per job and month, exported files |

## 4. World Compiler

Phases, each checkpointed before the next starts: **inspect → plan → materialize → discover → seed → adapt → author → validate (+ repair) → package**.

| Phase | Output |
|---|---|
| Inspect | Evidence-linked model of the application: services, routes, schema, roles |
| Plan | Typed runtime manifest: services, images or builds, ports, data paths, state probe |
| Materialize | The application running in a fresh sandbox; outside services redirected to stand-ins |
| Discover | API operations from OpenAPI, Swagger, GraphQL introspection or source |
| Seed | Fictional, relationally consistent data and role credentials; a base snapshot |
| Adapt | Typed tools per role that call the application's real routes |
| Author | Jobs: goal, scheduled events, checks, a reference trajectory, negative trajectories, split |
| Validate and repair | The five gates (§5), then a live agent tries each job; failures go back to the model as evidence |
| Package | An immutable world version with manifest, snapshot, capability report and content hash |

Roles (inspector, builder, scenario designer, validation investigator) share one tool loop: a role finishes only by calling its submit tool **and** passing a deterministic validator, whose feedback returns to the model as the tool result. Builder tools act only inside the build sandbox. Image references the model writes must be owner-supplied or pinned by a real `sha256` digest.

Every world must cover several stress categories: changed request, unknown outcome (a write times out after it succeeded), failure recovery, permission boundary, social engineering, injected instructions, missing information, privacy, conflict. Jobs are split into train, dev and held-out by family.

## 5. Job validation

A job is accepted only when, from a fresh reset:

1. its setup runs;
2. a no-op run (claiming completion at once) does **not** satisfy the goal;
3. the reference trajectory satisfies the goal with no hard violation, rejected step or environment error;
4. every negative trajectory is rejected (reward ≤ 0);
5. replaying the reference gives the same check results.

No model judgement is involved. A published world can be re-checked later (`rehearsal worlds validate`); jobs found unfair are withdrawn and excluded from verdicts.

## 6. Runtime and sandbox

- **Networks:** each instance gets an internal network with no egress for the application and providers, and a bridge only for the providers container, which publishes on loopback and acts as an authenticated edge proxy (per-instance admin token, stripped before forwarding).
- **Containers:** memory, CPU and process limits, `no-new-privileges`, dropped capabilities. Image references must match `registry/name[:tag][@sha256:digest]`; Docker options end with `--` before the image.
- **Reset:** volumes are restored from a snapshot; one-shot services are skipped because their effects are in the snapshot.
- **Gateway:** checks the role's authority just before dispatch, validates arguments against the tool contract, attaches the role's credential and an `Idempotency-Key` equal to the operation id, applies armed faults, and returns only what a real client would see. The full exchange is kept privately for the oracle.
- **Providers:** payments, email, shipping and webhook sinks over HTTP, SMTP on port 2525; every effect lands in an append-only journal keyed by idempotency key or message id.

## 7. Episodes and scoring

- The **episode engine** owns the step counter, goal version, inboxes, triggers and gateway; a policy only chooses the next tool calls. State is persisted after every step, so a restarted worker resumes the same episode against the same sandbox.
- The **simulated customer** takes goal and facts from the job; goal changes happen only through scheduled events.
- The **oracle** runs the job's checks as read-only probes (one statement, read-only transaction, bound parameters; an authorizer on SQLite) plus the provider journal. It records `goal_satisfied`, hard violations, rejected attempts, duplicate effects, false completion, recovery after faults, cost and tokens.
- **Verified rate** = finished episodes with the goal met and no hard violation ÷ finished episodes.
- **Ready to pilot** = at least 3 scored episodes on jobs the version never learned from, verified rate ≥ 0.8, no violations, no false completions.
- The **improvement agent** reads only train and dev episodes and edits only the system prompt and per-tool guidance; the new version is evaluated like any other.

## 8. Job queue

- A job is claimable when queued, or running with an expired lease (its worker died); claims use `FOR UPDATE SKIP LOCKED`.
- Workers renew leases by heartbeat and save a checkpoint after each phase; attempts are counted at claim, and a job past `max_attempts` fails.
- An evaluation is cut into shards (one worker and one sandbox each) that take episodes one at a time.
- Plan limits (builds, episodes, sandboxes, allowance) are checked under a lock on the organization row, so two API replicas cannot both take the last unit.

## 9. API and interfaces

- **REST** under `/v1`, with live event streams per job and run; OpenAPI at `/api/docs`.
- **Auth:** API keys (random, shown once, hashed at rest, scoped `read`, `write`, `evaluator`, `agent`, `admin`) for the CLI, SDK and CI; same-origin session cookies for the console; Google sign-in or email and password; browser approval for `rehearsal login`.
- **CLI and SDK:** `pip install rehearsal-kit`; reference pages are generated from the code and checked in CI.
- **MCP server:** lets an AI assistant add applications, build worlds, run evaluations, read failures, propose improvements, or act as the agent under test.
- **Console:** Next.js exported to static files and served by the API.

## 10. Models and spending

- One OpenAI-compatible client with fallback chains (`provider:model,...`) across 17 providers, including OpenAI, Anthropic, Google, Groq, Nebius, OpenRouter and a LiteLLM proxy. Rate limits, credit errors, server errors and timeouts move to the next entry. Each call has a 180-second limit and a 10-second connect timeout.
- Prices come from the provider's reported cost, its price list, a pinned price file, or OpenRouter's listing of the vendor or host. A job does not start if any model in its chain has no known price.
- Every job has a spending cap and every workspace a monthly allowance.

## 11. Billing

Plans (Free, Pro, Team, Enterprise) set applications, builds and episodes per month, sandboxes at once and a model-spend safety net. Checkout and the customer portal use Dodo Payments; webhooks are signature-verified, time-limited and applied once, and subscription state is re-read from Dodo rather than trusted from the event. Self-hosted servers run with plans off.

## 12. Observability and provenance

- **neatlogs:** spans only when `NEATLOGS_API_KEY` is set; every exported span passes through secret masking. Workflow roots for compilation, evaluation and improvement; detections for failed executions, slow and expensive model calls.
- **Entire:** coding sessions recorded as checkpoints in git refs, synced to a separate checkpoint repository; commits carry `Entire-Checkpoint` trailers ([CHECKPOINTS.md](../CHECKPOINTS.md)). entire-graph is installed for change-impact analysis.

## 13. Deployment

- **Compose stack** (`infra/compose.full.yaml`): migrate, API with console, workers, docs assistant, Caddy for HTTPS; optional local PostgreSQL. The worker receives only the settings it uses.
- **Production** (`infra/aws/ec2.yaml`): an always-on small machine serves the API, console and assistant; a larger worker machine starts when a job is due and stops after 15 idle minutes; both share data on EFS; PostgreSQL on Supabase through its IPv4 session pooler; docs on Vercel.

## 14. Testing

- **Unit tests** (565): contracts, compiler validation, runtime arguments, billing, pricing, API limits, recovery after crashes.
- **Integration tests** (40): API and queue against PostgreSQL, CLI sign-in, plans, and a full episode against a real Gitea container.
- **CI:** tests and a console build on every push; docs reference pages must match the code, plus lint, build and link checks.

## 15. Known limitations

- Applications need source and container images.
- World builds take 1–3 hours and do not always succeed.
- Only payments, email, shipping, webhooks and SMTP are emulated.
- Weight training and world-bundle replay are planned, not offered.
- Arbitrary public repositories need per-job VM isolation, which is planned.
