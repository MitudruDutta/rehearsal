# Rehearsal

Turn an authorized application into an executable practice environment for AI agents.

Rehearsal starts your real application in an isolated Docker sandbox with fictional data, writes jobs for an agent to do, and decides each outcome with read-only checks against the application's own database. No model grades the result.

The Python package contains a FastAPI control plane, PostgreSQL job queue, Docker sandbox runner, world compiler, episode engine, deterministic evaluator, improvement worker, and SDK/CLI. The Next.js console exports static files served by the API. Training jobs and standalone bundle replay are not implemented in this release.

## Requirements

- Python 3.11–3.13
- Docker with Compose, with the daemon running
- Node 22 or newer and pnpm 10, only to build the console from source
- A key for a model provider. `.env.example` uses Nebius; Groq, OpenRouter, Google, OpenAI, Anthropic, and local or custom OpenAI-compatible endpoints are also supported.

The server and worker are supported on Linux. The CLI and SDK client run anywhere. See [Windows](#windows) for what differs there.

## Quick start

Run every command from the repository root. The application reads `.env` from the working directory; existing shell variables take precedence.

```bash
# 1. Install
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[server,telemetry,dev]'

# 2. Configure
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"    # use the output as REHEARSAL_SESSION_SECRET
# Edit .env: set REHEARSAL_SESSION_SECRET and the key for your model provider (NEBIUS_API_KEY).

# 3. Build the console (once, and again after changes under web/)
cd web && pnpm install --frozen-lockfile && pnpm build && cd ..

# 4. Database, admin key, and a console login
rehearsal up                                             # PostgreSQL in Docker on 127.0.0.1:5433, then migrations
rehearsal bootstrap                                      # prints the project id and the admin API key, shown once
export REHEARSAL_URL=http://127.0.0.1:7800                # this server: the CLI's default is the hosted service
export REHEARSAL_API_KEY=rh_...
rehearsal users add you@example.com --project prj_...    # asks for a password of 10 or more characters

# 5. Run, in two terminals with the environment activated
rehearsal serve                                          # API and console on http://127.0.0.1:7800
rehearsal worker                                         # builds and evaluations; needs Docker
```

Open http://127.0.0.1:7800 and sign in with the account from step 4. The console needs a person's account; an API key does not sign in to it. `rehearsal users add` creates that login and attaches the person to the bootstrap project, so the console and the CLI see the same data. Sign-up is open by default: an account made on the sign-in page starts a new organisation of its own. Set `REHEARSAL_SIGNUP=closed` to turn that off.

Keep API keys in `.env`, which is ignored by git. Do not leave `REHEARSAL_SESSION_SECRET` at the example value: it signs the console's session cookies.

Without pnpm installed, `npx --yes pnpm@10.33.0` works in place of `pnpm`. The Dockerfile builds the console automatically.

## First world and evaluation

```bash
rehearsal apps import-catalog                        # eight pinned open-source applications
rehearsal apps list                                  # note an application id
rehearsal build APP_ID --watch                       # compiles a practice world; spends model budget
rehearsal worlds list                                # note the published world version id
rehearsal worlds scenarios WV_ID
rehearsal profiles create support-agent              # add --prompt-file FILE for your own instructions
rehearsal eval WV_ID --profile PROFILE_ID --split dev --watch
rehearsal runs episodes RUN_ID
rehearsal runs episode EPISODE_ID                    # actions, messages, and which checks failed
rehearsal improve PROFILE_ID RUN_ID                  # proposes the next agent version from train and dev failures
rehearsal eval WV_ID --profile NEW_PROFILE_ID --split holdout --watch
rehearsal compare RUN_A RUN_B                        # two runs on the same world version
```

To add your own application, pin its source commit and its published images:

```bash
rehearsal apps add my-app --git https://github.com/you/app --commit <full commit sha> \
  --image web=registry.example.com/app@sha256:<digest> --policies-file policies.md
```

Other commands:

| Command | Purpose |
|---|---|
| `rehearsal jobs show\|watch\|pause\|resume\|stop\|retry JOB_ID` | Inspect and control a job. `retry` continues a failed job from its last checkpoint |
| `rehearsal worlds validate WV_ID` | Re-check every job of a published world |
| `rehearsal worlds bundle WV_ID` | Export a world bundle; fetch it with `rehearsal artifacts list` and `download` |
| `rehearsal export RUN_ID` | Export verified trajectories as a dataset |
| `rehearsal prices` | Model prices and their sources for the configured chains |
| `rehearsal mcp` | MCP server for AI assistants; needs `pip install -e '.[mcp]'` |
| `rehearsal skill install` | Install the agent skill into `~/.claude/skills` |
| `rehearsal openapi` | Print the OpenAPI document |

`rehearsal --help` lists everything. `rehearsal train` and `rehearsal run-bundle` exist but report that they are not implemented.

If no model provider is configured, a build fails in its first phase with `inspector: model unavailable`. Set the key, then `rehearsal jobs retry JOB_ID`.

A Python client is in `rehearsal.sdk`; see [PACKAGE.md](PACKAGE.md). To drive episodes with your own agent, see [examples/agents/langgraph_react.py](examples/agents/langgraph_react.py).

## Configuration

`.env.example` documents the available settings. The main ones:

| Variable | Default | Purpose |
|---|---|---|
| `REHEARSAL_SESSION_SECRET` | a built-in development value; set your own | Signs console session cookies |
| `REHEARSAL_DATABASE_URL` | local PostgreSQL on port 5433 | Control-plane database; the default matches `rehearsal up` |
| `REHEARSAL_DATA_DIR` | `./var` | Source checkouts, snapshots, artifacts |
| `REHEARSAL_SOURCE_ROOTS` | `./examples` | Directories the worker may read local sources from |
| `REHEARSAL_MODEL_COMPILER`, `_AGENT`, `_PARTICIPANT`, `_IMPROVER` | see `.env.example` | Model fallback chains, written `provider:model[,provider:model...]` |
| `NEBIUS_API_KEY` and other provider keys | none | One key for each provider the chains name |
| `NEATLOGS_API_KEY` | none | Enables tracing; everything runs without it |
| `REHEARSAL_SIGNUP` | `open` | Anyone can create a workspace from the console. `closed` turns that off |
| `REHEARSAL_MAX_ACTIVE_BUILDS`, `REHEARSAL_MAX_ACTIVE_RUNS` | `0` (no limit) | Jobs one workspace may run at once |
| `REHEARSAL_RUN_PARALLEL`, `REHEARSAL_BUILD_PARALLEL` | `4` | Evaluation shards per run; scenarios validated at once in a build |
| `REHEARSAL_MONTHLY_ALLOWANCE_USD` | `0` (no limit) | Model spend a workspace may use per month |
| `REHEARSAL_URL`, `REHEARSAL_API_KEY` | `https://rehearsalkit.xyz`, none | Used by the CLI and SDK client; set `REHEARSAL_URL` for a server of your own |

The [self-hosting pages](docs/content/self-hosting/) of the documentation site cover installing with Docker Compose, upgrades, and troubleshooting.

The worker controls Docker and executes application source; use a dedicated runner. Restrict local sources with `REHEARSAL_SOURCE_ROOTS`. Admin keys have full access; scoped keys require `read`/`write` for ordinary operations, `evaluator` for private evaluation data, and `agent` for external-agent observations/actions. Evaluator mutations also require `write`.

## Console development

```bash
cd web
pnpm dev        # http://localhost:3000, proxying /v1 and /downloads to the API on port 7800
```

`pnpm build` writes the static export to `web/out` and copies it to `rehearsal/api/static`, where the API serves it.

## Tests

```bash
# Unit tests: no services needed
NEATLOGS_API_KEY='' PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/unit --confcutdir=tests/unit -p no:cacheprovider -p pytest_asyncio.plugin -q

# Integration tests: need `rehearsal up` running and, for the sandbox test, Docker
python -m pytest tests/integration

# Console typecheck
cd web && ./node_modules/.bin/tsc --noEmit --incremental false
```

The integration tests use a separate `rehearsal_test` database. The sandbox test starts a real Gitea container and pulls its image on the first run.

## Deploy on one host

`infra/compose.full.yaml` defines the complete stack: PostgreSQL, migrations, the API with the console, and workers.

```bash
cp infra/deploy.env.example infra/deploy.env      # fill in the password, session secret, and keys
docker compose -f infra/compose.full.yaml --env-file infra/deploy.env up -d
docker compose -f infra/compose.full.yaml --env-file infra/deploy.env exec api rehearsal bootstrap
docker compose -f infra/compose.full.yaml --env-file infra/deploy.env up -d --scale worker=6
```

Add `--profile public` with `REHEARSAL_DOMAIN` set to serve HTTPS through Caddy. The worker mounts the host's Docker socket, so run this stack on a dedicated machine. For arbitrary third-party repositories, use per-job VM isolation.

## Windows

The API, the database, and both integration test suites run on Windows with Docker Desktop. A complete world build on Windows is untested; use Linux or WSL2 if one fails.

- Activate with `.\.venv\Scripts\Activate.ps1`, copy the settings with `Copy-Item .env.example .env`, and set variables with `$env:REHEARSAL_API_KEY = "rh_..."`.
- Run `git config --global core.longpaths true` before the first build. Source checkouts sit under a long directory name, and without this setting a build fails with `Filename too long`.
- Build the console from Git Bash. The build script uses `rm` and `cp`, which PowerShell and `cmd` do not provide.
- Run the test commands above from Git Bash as well. The unit tests that create symbolic links need Developer Mode or an elevated shell; without it they fail with `WinError 1314`.

## Tracing and development provenance

Neatlogs uses the OpenAI-compatible client wrapper, with separate workflow roots for compilation, evaluation, and improvement. Workers initialize tracing once and flush on shutdown. The endpoint is `https://ingest.neatlogs.com`; keys are read from the environment. Secret masking applies before trace export.

Entire is configured in `.entire/settings.json` with automatic session pushing disabled and checkpoints stored as git refs. `.claude/settings.json` connects Claude Code's hooks to the `entire` CLI; each hook does nothing when the CLI is not installed. For Codex, approve the installed hooks through `/hooks`. No Entire checkpoints are recorded in this repository yet.

## Documentation

- [docs/](docs/): the documentation site: quickstarts, guides, reference, and self-hosting.
- [PACKAGE.md](PACKAGE.md): the package description shown on PyPI, with client and SDK usage.
