# Rehearsal

Turn an authorized application into an executable practice environment for AI agents.

The Python package contains a FastAPI control plane, PostgreSQL job queue, Docker sandbox runner, world compiler, episode engine, deterministic evaluator, improvement worker, and SDK/CLI. The Next.js console exports static files served by the API. Training jobs and standalone bundle replay are not implemented in this release.

## Local setup

Use Python 3.11–3.13, Docker with Compose, and the environment selected for this workspace:

```bash
source ~/python/bin/activate
python -m pip install -e '.[telemetry,dev]'
```

The application reads `.env` from the working directory; existing shell variables take precedence. Keep API keys in that ignored file. Configure `NEBIUS_API_KEY`, the `REHEARSAL_MODEL_*` chains, and `TRACING_API_KEY` there. Use a random `REHEARSAL_SESSION_SECRET`. `.env.example` documents the available settings.

When ready to launch, initialize the database and create an admin key:

```bash
rehearsal up
rehearsal bootstrap
```

Save the returned `REHEARSAL_API_KEY` locally. Run `rehearsal serve` and `rehearsal worker` in separate activated shells. Open http://127.0.0.1:7800. To build the console from source, run `pnpm install --frozen-lockfile` and `pnpm build` inside `web/` before starting the API. The Dockerfile builds the console automatically; `infra/compose.full.yaml` defines the complete stack.

The worker controls Docker and executes application source; use a dedicated runner. Restrict local sources with `REHEARSAL_SOURCE_ROOTS`. Admin keys have full access; scoped keys require `read`/`write` for ordinary operations, `evaluator` for private evaluation data, and `agent` for external-agent observations/actions. Evaluator mutations also require `write`.

## Tracing and development provenance

Tracing uses the OpenAI-compatible client wrapper, with separate workflow roots for compilation, evaluation, and improvement. Workers initialize tracing once and flush on shutdown. The endpoint is `https://example.invalid keys are read from the environment. Secret masking applies before trace export.

Recorder is enabled locally for Codex with automatic session pushing disabled. Approve the installed hooks through Codex `/hooks`. Checkpoint capture also requires an initial Git anchor commit. No commit, staging, or push was performed during this setup, so checkpoint capture is still pending.

`docs/BUSINESS.md` contains inputs for planning tool, not evidence of a generated planning tool plan. A real plan link and hackathon demo/replay evidence remain to be supplied.

## Verification without starting services

```bash
source ~/python/bin/activate
TRACING_API_KEY='' PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/unit --confcutdir=tests/unit -p no:cacheprovider -p pytest_asyncio.plugin -q
cd web
./node_modules/.bin/tsc --noEmit --incremental false
```

Integration tests require PostgreSQL and, for sandbox tests, Docker. They are separate from the unit command above.

The [implementation specification](docs/REHEARSAL_SPEC.md) includes planned capabilities as well as implemented behavior. It is not a claim that every feature or submission artifact is complete.
