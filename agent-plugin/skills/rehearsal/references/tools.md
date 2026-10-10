# Tools reference

Every MCP tool, what it returns, and the CLI and Python equivalents. Calls use the API key's permissions. A key with "Read only" access can call only the read tools.

Python: `from rehearsal.sdk import Rehearsal; rh = Rehearsal()` reads `REHEARSAL_API_KEY` and `REHEARSAL_URL`.

## Workspace

### `workspace_status()`
- Returns:
  - `usage`: `month`, `spent_usd`, `by_kind`, `allowance_usd` (null = no limit), `left_usd`, `renews` (date).
  - Counts of applications, published world versions and agents.
  - Console link.
- Use first, to check the key and the allowance.
- CLI: none. Python: `rh.get("/v1/usage")`.

## Applications

### `list_applications()`
- Returns `id`, `name`, `source` (repository, commit), `notes`.
- CLI: `rehearsal apps list`. Python: `rh.applications.list()`.

### `add_application(name, repository_url, commit="", images=None, policies="")`
- `images` maps each service name to a pinned image: `{"web": "chatwoot/chatwoot:v4.1.0@sha256:..."}`. Give a digest (`@sha256:...`) so the world is reproducible.
- `policies`: rules agents must follow, in plain words. Scenarios turn them into hard rules. Example: "Never share a customer's account number in a public channel."
- The name must be unique in the workspace.
- CLI: `rehearsal apps add NAME --git URL --commit SHA --image web=IMAGE@sha256:... [--policies-file FILE]`.
- Python: `rh.applications.create(name, {"kind": "git", "url": url, "commit": sha}, images, policies)`.
- `rehearsal apps import-catalog` adds the pinned open-source applications Rehearsal is tested on.

## Worlds

### `build_world(application_id, scenarios=8, budget_usd=None)` (spends money)
- Returns `job_id`, `world_id`, `world_version_id`, `version`, `watch` (console link).
- `scenarios`: number of jobs to write, 5-8 is typical. Fewer is faster and cheaper.
- `budget_usd`: the build stops itself at this spend. Without it, the build may use what is left of the allowance.
- CLI: `rehearsal build APP_ID [--scenarios 8] [--budget 6] [--watch]`. Python: `rh.worlds.build(app_id, scenario_target=8)`.

### `job_status(job_id)`
- Returns:
  - `kind`: `world_build`, `evaluation`, `improvement` or `world_validate`.
  - `status`: `queued`, `running`, `paused`, `succeeded`, `failed` or `cancelled`.
  - `attempts`, `spent_usd`, `completed_steps`, `result`, `error` (shortened).
- Poll a build every ~10 minutes, an improvement every ~20 seconds.
- CLI: `rehearsal jobs show JOB_ID` / `rehearsal jobs watch JOB_ID`. Python: `rh.jobs.get(job_id)`, `rh.jobs.wait(job_id)`.

### `control_job(job_id, command)`
- `pause`: stops at the next safe point and keeps the sandbox.
- `resume`: continues a paused job.
- `stop`: cancels. The sandbox is removed within a minute.
- `retry`: restarts a failed or stopped job from its last saved step. Finished steps are not repeated.
- CLI: `rehearsal jobs pause|resume|stop|retry JOB_ID`.

### `list_worlds()`
- Returns, per world, its versions: `world_version_id`, `version`, `status` (`building`, `published`, `failed`, `cancelled`). Use the highest published version unless the user names one.
- CLI: `rehearsal worlds list`.

### `list_scenarios(world_version_id)`
- Returns `id`, `slug`, `title`, `split`, `status`. Only `approved` jobs are evaluated.
- CLI: `rehearsal worlds scenarios WV_ID`.

### `recheck_world(world_version_id)` (spends money)
- Replays every job deterministically, then tries each once with a live agent. A job that is unfair to a live agent is withdrawn.
- Use it when a world was built before live checks existed, or when jobs look unfair.
- CLI: `rehearsal worlds validate WV_ID`.

## Agents

### `list_agents()`
- Returns `id`, `name`, `version`, `driver` (`llm` = Rehearsal runs the model; `external` = bring your own), `created_by` (`user` or `improver`).
- CLI: `rehearsal profiles list`.

### `create_agent(name, instructions="", model=None, bring_your_own=False)`
- `instructions` becomes the system prompt. It may use `{actor_id}`, `{role}` and `{instructions}` (the job's role instructions). Without `{instructions}`, the job's role instructions are added at the end. Empty means the platform default.
- `model`: a model chain on the server, for example `nebius:zai-org/GLM-5.3-Flash`. Leave it empty for the server default.
- A second profile with the same name becomes version 2. Versions are kept, so results stay comparable.
- CLI: `rehearsal profiles create NAME [--prompt-file FILE] [--model M] [--external]`.

## Evaluations

### `run_evaluation(world_version_id, agent_ids, splits=["dev"], repeats=1, budget_usd=None)` (spends money)
- Returns `run_id`, `job_id`, `episodes`, `shards` (how many sandboxes run in parallel), `watch`.
- Several agents in one run share the same jobs and world version, so the comparison is fair.
- CLI: `rehearsal eval WV_ID --profile ID [--profile ID2] --split dev --repeats 2 [--watch]`.

### `run_results(run_id)`
- Returns `status`, `summary` (per agent: `overall`, then per split, then `per_scenario`; fields in results.md) and one line per episode: `id`, `split`, `scenario`, `status`, `verified`, `ending`.
- CLI: `rehearsal runs show RUN_ID`, `rehearsal runs episodes RUN_ID`, `rehearsal runs watch RUN_ID`.

### `episode_details(episode_id)`
- Returns:
  - `goals` (the request and its revisions), `status`, `ending`, `verified`.
  - `environment_error`.
  - `failed_checks` (`check`, `observed`, `wanted`).
  - `duplicate_effects`, `false_completion`.
  - `actions`: `actor: tool(args) -> STATUS [fault]`.
  - The last 30 `messages`.
  - Console link.
- Action status:
  - `SUCCEEDED`, `FAILED`.
  - `REJECTED`: bad tool, role or arguments.
  - `UNKNOWN`: timed out; the outcome is unknown, and the write may have happened.
- CLI: `rehearsal runs episode EP_ID`.

### `improve_agent(agent_id, run_id)` (spends a little)
- Returns a job. On success, `result` has the new `profile_id`, `version` and `rationale`. It uses only failed `train`/`dev` episodes of approved jobs.
- CLI: `rehearsal improve PROFILE_ID RUN_ID`.

### `compare_runs(run_a, run_b=None)`
- With one run: compares the agents in it. With two: both must use the same world version, otherwise the graders differ and the API refuses.
- CLI: `rehearsal compare RUN_A [RUN_B]`.

## Bring your own agent

### `waiting_turns(run_id, wait_s=30)`
- Returns the episodes that wait for an action: `episode_id`, `actor` (who you play), `new_messages` (since your last action), and `tools` (`name`, `description`, `parameters` as JSON Schema).
- Waits up to `wait_s` (at most 120) for a turn. An empty list after a wait means no turn is waiting. The run may be finished: check `run_results`.

### `take_action(episode_id, actor, tool, arguments={})`
- Sends one action and returns the tool's result (waits up to 90 seconds).
- The actor and tool must match the current turn.
- One action per turn. Then call `waiting_turns` again.

Details and the loop: bring-your-own-agent.md.

## Other CLI commands

| Command | What it does |
|---|---|
| `rehearsal export RUN_ID... [--split train]` | Export verified trajectories as a dataset |
| `rehearsal train` | Coming soon: train a model on a world with reinforcement learning. Says so and exits |
| `rehearsal worlds bundle WV_ID [--include-images]` | Export a world to run offline; the file appears under Settings, Exports |
| `rehearsal run-bundle FILE` | Start an exported world on this machine (needs Docker) |
| `rehearsal artifacts list` / `download ID DEST` | List and download exports |
| `rehearsal skill install` | Install this skill into `~/.claude/skills/rehearsal/` |
| `rehearsal mcp` | Run the MCP server (stdio) |
