# Rehearsal: implementation specification

Status: architecture and product contracts, revised 9 October 2026 after the neatHack track was published. This document describes the full platform. No measured improvement is claimed by this document; measured results live in run evidence, not here.

## 0. Hackathon fit and revisions

The neatHack track is "Build an agent that works (literally)": an agent or team of agents completing a substantial task from start to finish, judged on planning, tool use, state, context, execution, recovery, verification, and iteration. Weights: the agent 30%, use of neatlogs + Entire + cfo.ai 25%, demo video 20%, building in public 15%, usefulness/originality 10%. [neatHack](https://neatlogs.com/hackathon)

**The headline agent is the World Compiler.** Its one substantial task: given an authorized application repository it has never seen, produce a published, resettable, independently validated practice world. It plans, uses tools (file reads, container builds, HTTP probes, database inspection), keeps durable phase state, recovers from failed builds and failed validation, and verifies its own output with checks it cannot approve for itself. Agents under test, simulated participants, and the improvement agent are consumers of that world; they demonstrate why the world is worth building.

Required evidence mapping:

| Required evidence | Where Rehearsal produces it |
|---|---|
| Before/after run with numbers | Same evaluation suite, pinned world/scenario/oracle versions, agent profile v1 vs v2 (or compiler v1 vs v2 on the same applications) |
| neatlogs traces | Compiler phases, episodes, tool calls, oracle checks as WORKFLOW/AGENT/TOOL/GUARDRAIL spans |
| Entire checkpoints / entire-graph | Development sessions of this repository |
| cfo.ai business plan | Pricing, cost, revenue, and runway plan; inputs recorded in `docs/BUSINESS.md` |
| Recovery from a failed action | Compiler build/validation repair, and in-episode `UNKNOWN` outcome reconciliation |
| Public repository with event-dated commits | Repository history; any pre-kickoff work is disclosed in the README rather than re-dated |

Revisions made in this version, with reasons:

1. **Headline agent defined** (above). The earlier draft listed seven roles without saying which one the track should judge.
2. **cfo.ai added.** The rules require neatlogs, Entire, and cfo.ai; the earlier draft omitted cfo.ai.
3. **Temporal replaced by a PostgreSQL lease queue.** The earlier draft kept control flow in Temporal and domain state in PostgreSQL, two sources of truth for the same job. A `jobs` table with `FOR UPDATE SKIP LOCKED` claiming, leases, heartbeats, attempt limits, and persisted phase checkpoints provides the restart and retry semantics this product needs without another server. Effects still require idempotency keys; no queue reverses application state.
4. **Next.js replaced by a Vite + React + TypeScript single-page console served by the API.** Every console screen shows authenticated, live, per-project data; server rendering adds a client-only boundary problem and no benefit. Serving from the API origin keeps session cookies same-origin for SSE.
5. **Pixel Agents replaced by an in-house Canvas 2D workspace renderer.** Its code is MIT but its character artwork carries separate terms, and its reference integration targets a different host. Procedurally drawn characters avoid redistribution questions. Pixel Agents remains a visual reference.
6. **Weight updates run on Kaggle GPU kernels; rollouts run on the runner.** Docker is unavailable inside Kaggle, so environment interaction stays where the world runs and only fine-tuning moves to Kaggle (item 9).
7. **Reconciliation semantics made precise** (section 3): the gateway offers `retry_operation` only when validation proved the application honours idempotency keys; otherwise the agent reconciles through read tools.
8. **Inputs are real open-source applications, never apps written by the Rehearsal authors.** If the same people write the application, the compiler, and the scenarios, any result is circular. Development applications, pinned by commit and image digest in `rehearsal/assets/catalog.yaml`: Gitea (Go, MIT; REST/Swagger; SQLite), Chatwoot (Rails, MIT core; Postgres, Redis, Sidekiq; REST; real customer inbox channel), Saleor (Django, BSD-3; Postgres, Redis; GraphQL). Held-out application, not inspected during development: Easy!Appointments (PHP, GPL-3; MySQL; REST). Small fixtures under `tests/fixtures/` exist only for fast unit tests and are never presented as results.
9. **Training is per application, and the claims say so.** A trained agent learns the workflows of the world it trained in. What should transfer across applications is the World Compiler, measured on the held-out application. Weight training uses **expert iteration**: a small open model served locally performs rollouts in Docker worlds on the runner, the oracle keeps only verified successful trajectories, a Kaggle kernel fine-tunes a LoRA adapter on them, and the next round serves the new adapter. Before/after compares the same base model on held-out scenario families. API-hosted models cannot be weight-trained; their improvement is prompt/tool-policy optimization, reported as a separate claim.
10. **State probes cover SQLite, PostgreSQL, and MySQL**, executed read-only inside the world, and emulated dependencies include an SMTP sink and a webhook sink, because real applications send email over SMTP and call webhooks rather than calling bespoke provider APIs.
11. **Scenario coverage is measured.** Scenarios are derived from the application's own routes, schema, and documentation, and every world reports which mutating operations its validated scenarios exercise. No domain template (such as refunds) is built into the compiler.

## Product

Rehearsal converts an authorized application into a versioned, resettable environment where agents can practice meaningful work, encounter changing human instructions, and receive independently checked feedback. It produces environments, scenarios, evaluation evidence, and training data. An optional training service produces model adapters or checkpoints.

The application is the workplace. The world adds initial conditions, controlled dependencies, scoped tools, participants, an event scheduler, and a verifier. A scenario defines a job inside that workplace. An episode is one attempt at that job. Training is a separate process that changes model parameters using episodes.

The differentiating product is the application-to-world construction and validation process, including changing human intentions. A model gateway, workflow engine, or attractive simulation alone is insufficient.

Primary users: teams deploying agents into their own software, companies evaluating automation before deployment, and AI builders needing application-specific training environments. Business benefits are hypotheses to validate: less manual environment engineering, fewer unsafe agent actions, and lower human supervision per correctly completed task.

## 1. What an application becomes

Represent a world as `W = (runtime, state, actions, observations, reset, events, verifier, provenance)`.

- Runtime: actual application services and versioned dependencies.
- State: application records, files, external-effect records, identities, pending jobs, and simulated time.
- Actions: operations an assigned role may perform through APIs or a browser.
- Observations: only information that role could obtain through its authorized interface.
- Reset: repeatable reconstruction of an initial state, including dependencies.
- Events: controlled customer messages, delays, cancellations, permission changes, and failures.
- Verifier: independent rules checking outcomes and forbidden effects.
- Provenance: source commits, image digests, approved policies, scenario versions, and validation evidence.

### Application connection modes

| Mode | Input | What Rehearsal builds | Boundary |
|---|---|---|---|
| Source-backed | Repository or OCI images, build configuration, fixture/policy inputs | Isolated instance of the real application | Preferred, strongest grounding; arbitrary repositories can still need configuration |
| Sandbox-backed | Owned staging/test account, API specification, reset/seed capability | Scoped tool adapter and episode controller | Training certification requires repeatable reset and inspectable outcomes |
| Browser-backed | Owned staging URL, test accounts, reset mechanism | Browser action/observation adapter | A URL alone cannot reveal hidden business logic or create a faithful clone |
| Emulated dependency | Documented external service contract plus authorized observations | Versioned local service emulator | Label fidelity limits; do not assume every provider behavior is reproduced |

An OpenAPI file supplies interface shapes, not complete business rules. Source-backed execution avoids guessing those rules. Missing reset, hidden external effects, or undocumented policy become explicit capability gaps. An application can be usable for a limited evaluation without being certified as resettable or suitable for training.

### Compilation pipeline

1. **Inspect:** identify services, startup commands, routes, schemas, identities, tool opportunities, dependencies, and policy sources. Produce `inspection.json`, listing evidence and unresolved assumptions.
2. **Plan:** construct a typed build plan. Mark which services run unchanged and which dependencies are replaced. Check the plan against runner permissions and resource budgets.
3. **Materialize:** start the real application in a fresh execution boundary. Install only scoped test credentials. Redirect email, payment, shipment, and similar effects to local test providers or authorized provider sandboxes.
4. **Seed:** generate fictional but relationally consistent users, records, files, and roles. Synthetic data generation does not establish privacy by itself; validate exports and keep real production data out of the public demonstration.
5. **Adapt:** expose typed tools and/or browser access. For example, `get_order`, `cancel_replacement`, and `request_refund` call actual application routes. The agent never gets database-administrator access just because the evaluator has it.
6. **Author scenarios:** generate initial conditions, user goals, scheduled changes, bounds, and proposed outcome checks. Attach each important rule to code, documentation, or an explicit owner-approved policy.
7. **Validate:** run reset checks, application equivalence checks where relevant, positive reference trajectories, and negative trajectories that must fail. A second model's agreement is not independent proof.
8. **Repair:** use observed failures to adjust the adapter, seed, scenario, or emulator. Re-run affected checks. Stop with an explicit unsupported capability when the model cannot establish the required behavior within budget.
9. **Package:** publish an immutable world version with an execution manifest, capability report, validation evidence, and content hashes.

No production account is mutated during compilation. Importing arbitrary code also requires a real execution boundary; a public web API must not hand untrusted build instructions directly to its own Docker daemon.

## 2. What the agents actually do

Use a fixed workflow with role-specific model calls and explicit tool permissions. These roles need not be separate models or separate always-running processes.

| Role | Inputs and tools | Output | Cannot do |
|---|---|---|---|
| Inspector | Read repository, schemas, policy documents; probe owned sandbox | Evidence-linked application model | Invent unobserved rules as established facts |
| World builder | Approved build plan, sandbox provisioner, fixture generator, adapter tests | Executable world candidate | Access production secrets or change platform permissions |
| Scenario designer | Verified capabilities, policy contract, scenario templates | Tasks, event schedules, proposed checks | Certify its own checks as sufficient |
| Validation investigator | Run reference and negative cases, inspect isolated state, compare contracts | Failure diagnosis and bounded repair requests | Silently weaken approved acceptance criteria |
| Agent under test | Goal, role-filtered observations, permitted tools | Actions, messages, completion claim | Read hidden graders or privileged state |
| Simulated participant | Scenario facts and scheduled goals | Natural-language messages | Change ground truth through free-form prose alone |
| Improvement agent | Training/development failures and allowed policy files | Prompt/tool-policy candidate or training configuration | Read holdout results repeatedly to optimize against them |

The **orchestrator**, **event scheduler**, **action gateway**, and **oracle** are deterministic services. The oracle executes approved checks. A model may propose those checks, but cannot approve or edit them while being evaluated.

The simulated participant's words come from a model if useful; its underlying goal and permitted facts come from a versioned scenario. An actor describing frustration does not prove a real user's feelings or satisfaction. Real user research remains necessary.

### Multi-agent collaboration inside one world

A company can register one agent or a team. A coordinator can assign work to support, fulfillment, and finance agents. Each has a distinct identity, inbox, action scope, and observation filter. Messages travel through a recorded message bus. All authorized agents act on the same episode state; they do not have separate imaginary copies of the application.

Parallel reads are permitted. Mutating actions use a per-world sequencer or application transactions with version checks. Roles receive only their authorized results. Every action records which agent requested it and which goal/permission version it used. Impersonating another role or reading the evaluator's state is forbidden by capability enforcement.

World-building agents run before publication. Business agents run inside a published world. Training workers repeatedly launch episodes. These are three separate lifecycles.

## 3. One complete episode

Commerce is an explanatory example, not a product-specific engine. The same interfaces support issue trackers, booking applications, CRMs, and document workflows.

Initial state: fictional order O-42 is paid, replacement not shipped, no refund exists. The participant asks for a replacement. Coordinator delegates eligibility to support and fulfillment work to an operations agent.

1. Tools return actual seeded order state.
2. Fulfillment prepares a replacement but has not committed shipment.
3. Scenario scheduler delivers: "Actually, cancel that. I need the money back." It records goal version 2 and invalidates pending authorization tied to version 1.
4. Coordinator reads the update, checks whether replacement is merely planned or already committed, and delegates cancellation plus refund handling.
5. Finance calls the permitted refund action. The fake payment provider applies one refund, then the fault injector drops the response. Result is `UNKNOWN`, not `FAILED`.
6. Finance reconciles before retrying. If the world's capability report proves the application honours `Idempotency-Key`, the gateway offers `retry_operation(operation_id)`, which replays the identical request under the same key and returns the original effect. Otherwise finance reads order/refund state through its normal read tools. Either way it discovers the existing refund rather than issuing a second one. The gateway never reveals the dropped response itself; that would hand the agent information a real client would not have.
7. Coordinator verifies replacement cancellation, refund state, and a fictional notification receipt.
8. Oracle evaluates actual state and the event journal. It confirms the latest goal is satisfied and no prohibited effect occurred.
9. Rehearsal saves the episode, evidence, cost, timing, policy version, and outcome. Reset returns all services to the declared starting state for the next attempt.

If shipment was already irreversible before goal revision, the correct task may be arranging a return or asking a required decision. The scenario contract defines that branch. Agents must not claim an external action was undone when it was not.

### Changed-intent and race semantics

- Each update receives a monotonic sequence number, goal version, delivery timestamp, and effective boundary.
- Gateway checks role authority and current permission/goal version immediately before committing an effect where it controls that commit.
- An accepted operation that has already committed is reconciled or compensated under allowed policy; cancellation is not time travel.
- Actions are `PROPOSED`, `AUTHORIZED`, `RUNNING`, `SUCCEEDED`, `FAILED`, or `UNKNOWN`; stale proposals are `SUPERSEDED`.
- On timeout, query the action receipt/provider state before retrying. Use stable idempotency keys where supported. Without sufficient evidence, pause that action as uncertain.
- Record rejected attempts separately from executed violations. A protective gateway stopping an unsafe request is not evidence that the model itself respected the rule.
- Distinguish an update not yet observable to an agent from an agent ignoring an update it already received.
- Pause, stop, and cancel have different meanings. Pausing prevents new dispatch; already-running effects still need reconciliation.

## 4. Fidelity and grading

A runnable emulator is not automatically a faithful world. Publish a **validation report**, not an absolute correctness certificate.

Check five properties independently:

1. **Resetability:** reset twice with the same seed and compare canonical state. Reset database, uploads, queues, sessions, provider journals, clock, counters, and scheduled jobs. A fresh browser context resets browser-local state, not server records. [Playwright isolation](https://playwright.dev/docs/browser-contexts).
2. **Behavioral fidelity:** for covered operations, compare approved reference application behavior with the adapted/emulated behavior. Use invariant comparisons where generated IDs or timestamps differ. Report coverage and unsupported cases; finite tests cannot prove universal equivalence.
3. **Task solvability:** a reference policy can complete each solvable task. Intentionally impossible tasks require a separately specified correct escalation outcome.
4. **Grader validity:** incomplete, wrong-user, duplicate, unauthorized, and stale-goal outcomes must be rejected. Mutation cases test that a grader is more than "HTTP 200" or "agent said done."
5. **Isolation:** learner tools cannot inspect private state, alter the oracle, retrieve holdout scenarios, or contact real external providers.

Core grading consumes database invariants and effect receipts. Language-model review can supply auxiliary communication-quality labels; it is not the authority for whether a refund happened.

Store structured results: `goal_satisfied`, `hard_constraint_violations`, `rejected_attempts`, `unnecessary_interruptions`, `recovery_result`, `elapsed_ms`, `model_cost`, `environment_error`, and evidence references. Environment failures are distinct from agent failures.

For an initial training reward, use 1 for verified task success with no hard violation, 0 for unsuccessful work without a hard violation, and -1 for an executed hard violation. Report the vector as well as the scalar. Sparse rewards are an honest starting point; any shaping requires shortcut tests. Cost or speed must not compensate for violating a hard constraint. Gate promotion on hard-constraint performance separately from mean reward.

Version and freeze evaluation contracts before a comparison. Keep train/development/holdout partitions separated by scenario families and application behaviors, not merely random seed. Candidate improvement uses development data. Run limited final evaluations on untouched holdouts and on a clean authorized application instance to test transfer beyond the training world.

## 5. Training: what changes and what does not

### Evaluation

Run an existing model or external agent against scenarios. Measure outcomes. Its weights do not change.

### Policy/scaffold optimization

An improvement agent edits allowed system instructions, examples, tool descriptions, or routing logic, then runs development evaluations. Version candidates and compare them using identical conditions. This works with API models but is not model-weight RL.

### Supervised fine-tuning

Export successful, independently verified trajectories with observations, typed tool calls, results, and final outcomes. Train a supported open model or compatible provider fine-tuning job. Do not include hidden oracle state or evaluator-only information as agent input.

### Reinforcement learning

Use an open/trainable model, GPU worker, rollout policy, isolated environment instances, and oracle rewards.

Rehearsal's default weight-training method is **expert iteration** (rejection-sampling fine-tuning), chosen because real applications need Docker and Kaggle kernels cannot run Docker:

1. Serve base model + current LoRA adapter locally through an OpenAI-compatible endpoint (vLLM with LoRA support, or another compatible server).
2. Run K rollouts per training-split scenario in Docker worlds on the runner.
3. Keep only trajectories the oracle verifies: goal satisfied, no hard violation, no environment error.
4. Push a private Kaggle dataset (verified trajectories, pinned requirements) and kernel; the kernel fine-tunes a LoRA adapter with TRL SFT on a T4 and writes the adapter plus training metrics to its output.
5. Download the adapter, verify its hashes, and serve it for the next round.
6. After each round, evaluate base and adapter on development scenarios; after the final round, evaluate once on held-out scenario families.

The trained model only ever sees role-visible observations and its own tool calls. Iterations, rollouts per scenario, and success counts are reported with denominators. Live-environment GRPO remains possible for worlds that declare a `native` runtime a Kaggle kernel can start as plain processes; it is not the default. A trainer updates model parameters after batches of rollouts. A model API key alone does not grant access to that provider's model weights or arbitrary RL training.

Adopt an OpenEnv compatibility adapter rather than inventing a closed environment convention. OpenEnv defines environment reset/step/state concepts. TRL documents stateful multi-turn training via `GRPOTrainer(environment_factory=...)`; the wrapper exposes only intended actor tools. Keep inspect/reset administration, secret retrieval, and oracle methods out of tool discovery. Pin and verify compatible dependency versions before implementation. [OpenEnv concepts](https://huggingface.co/docs/openenv/main/guides/concepts), [TRL integration](https://huggingface.co/docs/trl/openenv).

Training is optional for using Rehearsal. Its output is a model adapter/checkpoint plus a held-out evaluation report, never an automatic claim of safer real-world behavior. GPU requirements depend on model size, rollout length, concurrency, and training method; benchmark them rather than promise training cost or duration.

### Trajectory record

Each episode records world/scenario/policy/model versions; seed; actor identity; role-visible observations; action requests/results; externally emitted decision summaries; goal revisions; state/effect evidence references; reward components; token/cost data; termination reason; and oracle version.

Training exports exclude private grader internals, API credentials, raw customer data, and private model reasoning. Retention and permitted export scopes belong to the owning organization.

## 6. Technology choices and system boundaries

| Layer | Choice | Reason |
|---|---|---|
| Agent/world core | Python 3.12, Pydantic, uv | Typed contracts and access to agent/RL tooling |
| Public API | FastAPI | Versioned REST, validation, OpenAPI and streaming endpoints |
| Durable orchestration | PostgreSQL job table with leases, heartbeats, attempt limits, phase checkpoints | Restart-safe long jobs, pause/stop commands, one source of truth |
| Product UI | TypeScript, React, Vite; in-house Canvas 2D workspace renderer | Live console, cartoon agent workspace, typed API client, accessible controls |
| Browser execution | Playwright worker | Real UI interaction and browser observations |
| Application runtime | OCI images/Compose in a dedicated runner | Reuse the actual app and its dependencies |
| Metadata/events | PostgreSQL, SQLAlchemy, Alembic | Transactional records, tenant scoping, append-only event sequence |
| Large artifacts | S3-compatible object storage; local filesystem implementation for local mode | Screenshots, recordings, packages, datasets |
| Live event delivery | SSE plus REST commands | Reconnectable event feed; commands remain authenticated requests |
| Training bridge | OpenEnv + TRL on Kaggle GPU kernels | Interoperable environment and genuine training path |
| Model access | OpenAI-compatible client (OpenRouter by default, any compatible endpoint) | One driver for many models; provider keys stay server-side |
| Observability | neatlogs | Model/tool/workflow traces and before/after investigation |
| Development provenance | Entire | Coding-session checkpoints tied to changes |
| Business plan | cfo.ai | Pricing, costs, revenue, and runway |

Separate API serving, orchestration workers, execution runners, and GPU workers. Never run a long training job inside a web request or rely on a web process's in-memory background task for durable work. [FastAPI background task guidance](https://fastapi.tiangolo.com/tutorial/background-tasks/).

The job table records control flow and PostgreSQL records domain events and action receipts, in one database. A worker claims a job with `FOR UPDATE SKIP LOCKED`, holds a lease it renews by heartbeat, and writes a phase checkpoint after each completed phase. An expired lease returns the job to the queue; the next worker resumes from the last checkpoint. A retried phase still needs safe effect handling: effects carry stable operation keys and are reconciled, never blindly replayed.

Core flow:

```text
Browser / Python SDK / CLI
            |
     API + identity + quotas
            |
    PostgreSQL job queue -------- PostgreSQL / artifact storage
            |
  Compiler workers / episode workers / optional training workers
            |
  Scoped runner service + action gateway
            |
  Isolated app + database + fake dependencies + participant inboxes
            |
  Privileged read-only evaluator -> outcome evidence

Sanitized durable events -> SSE -> live UI
Sanitized execution spans -> neatlogs
Development changes + sessions -> Entire checkpoints
```

### Execution trust

For local/team-owned apps, begin with a dedicated VM and hardened container runner. For a public multi-tenant service accepting arbitrary repositories, use per-job VM/microVM isolation or an appropriately isolated execution provider before launch. Containers alone are not a blanket security guarantee. Do not mount the host Docker socket into agent-controlled code. Bound egress, CPU, memory, disk, time, and model spend. [Docker security](https://docs.docker.com/engine/security/).

Keep platform services outside the application execution boundary. The learner can access only its app origin and scoped tool gateway. Builder network access is separately controlled from episode execution. Compilers' generated commands and adapters undergo schema/policy validation before execution.

## 7. SDK, CLI, API, and keys

Package as one product with complementary entry points:

- **Web application:** connect applications, review world capabilities, watch runs, compare versions, download artifacts.
- **Python SDK:** programmatic build, evaluation, export, and training-job submission.
- **CLI:** local onboarding, runner startup, world validation, CI evaluation, bundle export.
- **Versioned REST API:** language-independent integration; generate a TypeScript client from the API schema.
- **Runner:** performs execution on Rehearsal-managed infrastructure or within the customer's environment.
- **Portable world format:** content-addressed bundle plus OCI images, with documented licensing and dependency requirements.

Proposed names are provisional until registry and trademark availability are checked.

### Credential model

1. `REHEARSAL_API_KEY` authenticates a user/service account to our control plane. Scope by organization/project and permitted operations; store hashed key material for validation where applicable, support rotation and revocation.
2. **Managed inference:** our backend calls model providers using our provider credentials; meter and cap each organization's usage. Never distribute those provider keys in an SDK or browser bundle.
3. **BYOK inference:** a customer stores encrypted provider credentials server-side or in its local runner secret store. Job configuration references a credential ID. Tenant-scoped access, explicit export policy, redaction, and key deletion apply.
4. **Application credentials:** scoped sandbox accounts, separate from provider credentials. Inject just-in-time into the appropriate runner; exclude them from exported worlds.
5. **Training credentials:** the Kaggle API token used to push kernels and datasets, separate again. Running a model API does not authorize training a provider's weights.

Local mode can keep source and app data in the user's machine/VPC. Hosted model inference may still transmit permitted observations to its provider; disclose that distinction. Offline/private inference requires an appropriate local endpoint. A local-only installation need not require a cloud account; hosted features do.

### Proposed Python SDK

```python
# Proposed API contract, not an installable example yet.
import os
from rehearsal import Rehearsal

client = Rehearsal(api_key=os.environ["REHEARSAL_API_KEY"])
job = client.worlds.build(
    source={"kind": "runner_path", "runner_id": "runner_local", "path": "./app"},
    manifest="./rehearsal.yaml",
    model_profile="builder-default",
)
world = client.jobs.wait(job.id).world
run = client.evaluations.create(
    world_version=world.version,
    suite="changing-intent-v1",
    agents=[{"name": "support", "profile": "candidate-v1"}],
    seeds=[11, 17, 23],
)
for event in client.runs.events(run.id):
    print(event.type, event.summary)
```

The SDK must explicitly register/upload sources or refer to a registered runner; a cloud API cannot magically read a local path. Long operations return job IDs. Polling, events, cancellation, timeouts, and stable retry keys are part of the SDK contract.

### Proposed REST surface

| Method/path | Purpose |
|---|---|
| `POST /v1/applications` | Register source reference and connection mode |
| `POST /v1/runners/register` | Register a scoped execution runner |
| `POST /v1/world-builds` | Start asynchronous compilation |
| `GET /v1/jobs/{id}` | Read durable job state and errors |
| `POST /v1/worlds/{version}/validate` | Execute capability/fidelity checks |
| `POST /v1/worlds/{version}/scenarios` | Propose scenarios, pending validation |
| `POST /v1/evaluations` | Start versioned scenario/model comparison |
| `POST /v1/episodes/{id}/actions` | Submit scoped actor action with idempotency key |
| `POST /v1/episodes/{id}/interventions` | Operator changes goal or injects allowed fault |
| `GET /v1/runs/{id}/events` | SSE stream supporting event cursor/reconnect |
| `POST /v1/runs/{id}/commands` | Pause, resume, or stop; explicit command semantics |
| `POST /v1/dataset-exports` | Export permitted trajectories asynchronously |
| `POST /v1/training-jobs` | Start actual supported training workflow |
| `GET /v1/artifacts/{id}` | Retrieve authorized artifact metadata/download |

Authenticated browser SSE uses a scoped session cookie or short-lived stream token; never put a long-lived API key in a URL. Every database lookup and artifact read enforces tenant/project scope. Local runner job claiming uses scoped short-lived credentials and outbound connections; do not expose an unauthenticated localhost control port.

### Minimal engine interfaces

```python
# Proposed interfaces; trusted runner methods are NOT exposed as learner tools.
class WorldAdapter:
    async def provision(self, manifest, execution_scope): ...
    async def reset(self, scenario, seed): ...
    async def observe(self, actor_id): ...
    async def execute(self, actor_id, action, operation_id, goal_version): ...
    async def reconcile(self, operation_id): ...
    async def inspect_for_oracle(self, evaluator_capability): ...
    async def teardown(self): ...

class AgentDriver:
    async def next_action(self, observation, tool_catalog, inbox): ...
```

Do not assume every reset can be a database transaction rollback; applications have other state and side effects. Snapshot/restore is an optional capability. If unsupported, rebuild from the seed. A branch at a historical event requires a consistent snapshot or deterministic replay, not just replaying UI logs.

### Portable artifact

```text
world-bundle/
  world.yaml                # version, image digests, capabilities, allowed resources
  adapters/                 # reviewed and versioned runtime/tool adapters
  fixtures/                 # fictional seed records and files
  scenarios/train/          # public training tasks and event schedules
  policies/                 # approved public policy contracts
  validation/               # scoped validation results, versions, known limits
  provenance.json           # source commit and build/evidence references
  checksums.json

private-evaluation-bundle/   # separate storage and credentials
  holdout-scenarios/
  oracle-checks/
```

Keep private holdouts/oracles outside the learner's filesystem, API scope, and downloads. Public train checks can be provided intentionally, but evaluation tasks cannot inherit privileged answers. Artifacts contain no credentials. Dependency licenses and redistribution restrictions travel with exported artifacts.

## 8. Database and event contracts

Main records: organizations, users, projects, credential references, runners, applications, world versions, build jobs, scenario versions, agent profiles, suites, runs, episodes, actor messages, actions, effect receipts, events, oracle results, artifacts, dataset exports, and training jobs.

World versions are immutable. A run binds exact world/scenario/agent/policy/evaluator versions and a seed. State transitions use transactions and an outbox so database writes and event publication cannot silently diverge. Worker leases and heartbeats expose stuck jobs; jobs have bounded retry/time/cost policies.

Event envelope:

```json
{
  "event_id": "evt_example",
  "run_id": "run_example",
  "episode_id": "ep_example",
  "sequence": 14,
  "type": "action.outcome_unknown",
  "actor_id": "finance",
  "goal_version": 2,
  "summary": "Refund response timed out; checking the existing operation before retrying.",
  "evidence_refs": ["artifact_receipt_query"],
  "visibility": "project",
  "created_at": "2026-10-10T08:00:00Z"
}
```

Timestamps above illustrate a schema, not an executed run. Sequence numbers provide ordered delivery within an episode. Cross-episode views use timestamp plus IDs without pretending there is one transactional global ordering. Retain source events; create redacted projections for UI and telemetry.

## 9. User interface

The main product is a web console, with SDK and CLI for automation. Use a cartoon agent workspace driven by actual execution events, alongside the application preview and evidence panels. Animations communicate observed activity; they must not invent progress or fabricate "thinking" text.

### Visual foundation: in-house Canvas 2D workspace

Rehearsal draws its cartoon workspace with a small Canvas 2D renderer inside the React console. Characters are drawn procedurally from role colours, so no third-party artwork needs licensing review. [Pixel Agents](https://github.com/pixel-agents-hq/pixel-agents) (MIT code, separately licensed artwork) remains the visual reference for rooms, workstations, speech bubbles, and sub-agent display.

Rehearsal owns world compilation, agent orchestration, episode state, permissions, grading, and training. The renderer only consumes Rehearsal's typed event stream.

### Visual language and event mapping

| Rehearsal concept or event | Cartoon representation | Inspectable evidence |
|---|---|---|
| World construction | Inspector and builder characters work in a laboratory | Build plan, tool results, validation and repair history |
| Application world | A named room for each world; label its version and active episode | Application preview, capabilities, initial state |
| Agent joins an episode | Character appears with its name and role | Identity, assigned task, permitted tools |
| Task assignment / tool execution | Character moves to the relevant workstation and shows an activity state | Actual action, sanitized arguments, result, timestamps |
| Delegation / agent message | Message indicator between the sending and receiving characters | Recorded message, sender, recipient, task reference |
| Goal revision | Updated task board and revision indicator on affected agents | New instruction, goal version, superseded plans |
| Blocked action / uncertain outcome | Character displays a waiting or uncertainty indicator | Error, pending decision, or reconciliation status |
| Outcome verification | Verifier character checks the completed task | Independent checks and application/effect receipts |
| Verified completion | Completion animation only after the oracle confirms the outcome | Outcome report, trace links, exported artifacts |

Clicking a character opens its current goal, task, concise decision summaries, tool activity, results, and linked neatlogs evidence. Keep the actual application/browser preview and state-difference panel available beside the cartoon workspace. Character position is presentation state; it is never authoritative application state or proof of collaboration.

### Integration requirements

- Translate authenticated SSE events into a small typed renderer model keyed by world, episode, and actor IDs. Rehydrate from a current-state snapshot and sequence cursor after reconnect; deduplicate replayed events.
- Derive working, waiting, blocked, verifying, and completed states from backend events. Idle animations are cosmetic and cannot imply that work occurred.
- Preserve controls and a text activity view for keyboard users, reduced-motion preferences, and environments where the graphical view is unavailable.
- Keep speech bubbles brief and sanitized. Show externally emitted decision summaries, never hidden chain-of-thought or secrets.

Screens:

1. **Applications:** connection mode, source version, runner, policies, credentials by reference, detected gaps.
2. **World builder:** inspection evidence, build plan, service topology, current agent/task, validation results, repair history, published version.
3. **Scenario studio:** starting state, participant goals, roles, allowed tools, event triggers, expected/forbidden outcomes, train/holdout controls.
4. **Live run:** app/browser preview, agent lanes, event timeline, selected action details, current goal version, state differences, pending human decisions, cost/budget, pause/stop controls.
5. **Evaluation comparison:** same-suite baseline/candidate outcomes, per-case drilldown, constraint violations, recovery, interruptions, execution cost, environment errors.
6. **Training:** dataset version, base model, method, compute limits, rollout progress, actual checkpoint artifacts, held-out evaluation and promotion status.
7. **Artifacts/settings:** world downloads, trajectory exports, trace/checkpoint links, retention, credential profiles, project roles.

Decision display includes goal, current plan, chosen action, brief explanation, tool inputs/results with redaction, evidence, and observed outcome. This is an externally emitted audit summary, not access to hidden chain-of-thought. Do not synthesize a transcript and present it as a model's actual internal thoughts.

Use SSE for semantic events and periodic authorized screenshots for browser preview. Live video/remote desktop can be an execution-provider feature, not a requirement for the first reliable console. Native iframe embedding is only used for an owned app with compatible origin/frame policy and isolated authentication. Screenshots and recordings also need access control and redaction.

The production console lives in `web/`.

## 10. neatlogs and Entire

Instrument world build, scenario validation, episode execution, and improvement workflows. Use workflow/agent/tool/guardrail spans with world, run, episode, action, policy, and evaluator identifiers. Suppress or sanitize inputs/outputs before export; test secret/PII masking. Preserve full sensitive artifacts only in authorized storage when necessary. The Python SDK documents explicit spans and masking. [neatlogs Python](https://docs.neatlogs.com/sdk/python), [masking](https://docs.neatlogs.com/sdk/pii-redaction).

Rehearsal's own event store drives the UI and execution state. neatlogs supplies trace investigation and evidence links; it is not the episode database. A trace need not stay open for a multi-hour job: propagate trace context where supported and correlate bounded spans through stable run IDs.

Use cfo.ai to produce the business plan required by the hackathon: pricing per world build and per evaluation episode, model and compute costs per unit, hosting costs, revenue scenarios, and runway. Record the inputs and the resulting plan link in `docs/BUSINESS.md`.

Enable Entire for supported coding sessions during implementation. Link the failing run to the diagnosed defect, the code commit/checkpoint, and a comparable rerun. Entire captures development provenance, not application snapshots or episode reset. It can also capture the supported coding session used to implement a generated adapter, but arbitrary file writes are not automatically Entire checkpoints. [Entire checkpoints](https://entire.io/blog/the-entire-cli-how-it-works-and-where-its-headed).

Maintain two distinct improvement claims: (a) Rehearsal generated more faithful worlds/better graders after a compiler fix; (b) an agent performed better after a policy or weight update. Do not compare scores across changed graders and attribute the difference to the agent.

## 11. Repository and build sequence

Repository layout:

```text
rehearsal/core/             # typed world/scenario/event/action contracts
rehearsal/db/               # SQLAlchemy models, Alembic migrations, job queue
rehearsal/api/              # FastAPI REST, SSE, identity, static console
rehearsal/worker/           # job worker: builds, evaluations, exports, training
rehearsal/runner/           # container lifecycle, reset, action gateway, faults
rehearsal/evaluator/        # privileged read-only outcome checks
rehearsal/compiler/         # World Compiler agent: inspect -> package
rehearsal/agents/           # model driver, agent under test, participant, improver
rehearsal/providers/        # emulated payment/email/shipping dependencies
rehearsal/training/         # OpenEnv adapter, dataset export, Kaggle jobs
rehearsal/telemetry/        # neatlogs spans and masking
rehearsal/sdk/              # Python client and CLI
web/                        # Vite + React console and Canvas workspace
examples/                   # redistributable applications in different domains
tests/                      # contracts, integration, evaluation
infra/                      # local compose definitions
docs/                       # spec, quickstart, evidence, business plan inputs
```

Implementation order is dependency-driven, not a reduction to one industry:

1. Freeze typed contracts, event vocabulary, credential boundary, world manifest, and lifecycle states.
2. Implement source-backed runner, full-state reset, fake providers, scoped tool execution, receipts, and evaluator boundary.
3. Implement one complete compiler workflow: inspect, provision, validate, repair, publish.
4. Implement scenarios, multi-agent identities/messages, changing-goal scheduler, and episode persistence.
5. Connect the live console and SDK to real backend events; eliminate illustrative placeholders from production screens.
6. Add evaluation comparison, immutable artifacts, export/replay, masking, budgets, and failure recovery tests.
7. Add OpenEnv bridge, verified trajectory export, optional actual training worker, and held-out promotion evaluation.
8. Expand generic adapters and validate different applications without changing the core engine.
9. Add production multi-tenant isolation, operational limits, billing, organization controls, retention, and deployment hardening before commercial exposure.

Three-builder ownership: A owns core/compiler/job queue; B owns runtime/adapters/evaluator/training bridge; C owns UI/API integration/SDK documentation/evidence capture. Agree contracts first and integrate a real event stream early. Security/isolation decisions are shared interfaces, not a late handoff.

A general source-backed platform with several workflows can be a hackathon deliverable. Universal imports, a commercial multi-tenant service, arbitrary browser cloning, and validated RL improvements across domains are substantial subsequent work. Maintain the full architecture and report actual implementation coverage honestly rather than treating planned modules as shipped.

## 12. Acceptance and release evidence

- A source-backed app becomes a published, resettable world with explicit capabilities.
- At least two different example applications exercise the same engine contracts; each adapter's limitations are documented.
- Generated scenarios have reference trajectories and negative checks.
- Permission and goal revisions survive worker restart; effects are reconciled after unknown outcomes.
- Independent episodes cannot read or affect one another.
- The learner cannot access the hidden oracle or holdouts.
- UI events reconnect without duplicate actions; controls have real backend semantics.
- SDK and CLI can launch the same evaluation as the UI.
- Exported bundles run on a clean machine with documented prerequisites.
- Evaluation compares exact pinned versions, with denominators and environment errors reported.
- Training features distinguish prompt optimization, SFT, and actual RL; any claimed improvement has untouched evaluation evidence.
- Redaction checks cover telemetry, screenshots, event summaries, and artifacts.

Submission package: public repository and commits created during the eligible event window; architecture/quickstart; runnable local setup; licensed sample apps/fixtures; world bundle and replay instructions; hosted console or public sanitized replay; short demo video; before/after neatlogs traces; Entire checkpoint links; cfo.ai business plan; failure-recovery run; building-in-public links tagged #neatHack. Follow the organizer's current submission rules; the user's supplied dates and evidence requirements remain the planning reference.

Judge flow: connect supplied application -> show inspection/build -> reveal generated world -> run task with changing instruction -> observe failure diagnosis/recovery -> inspect state evidence -> compare pinned versions -> download runnable artifact. A retained recording is explicitly marked replay if a live run is unavailable. The public hosted demo uses bounded preapproved sample worlds; arbitrary repository execution stays behind appropriate isolation and access controls.

## 13. Final outcomes

For a product team: a reusable practice environment specific to its application, a map of observed agent failures, and evidence supporting or rejecting deployment of a candidate agent.

For an agent developer: repeatable tasks, machine-checkable outcomes, trajectory datasets, and optionally a trained policy/model artifact.

For real users: an opportunity for agent builders to catch mistakes involving changed instructions, privacy, repeated requests, and incomplete work before deployment. Simulated gains must be checked against real application behavior and eventually real user outcomes; no simulator can guarantee empathy or production correctness.
