# Running Rehearsal locally

How to run the API, console and workers on your machine for development. Run every command from the repository
root.

## What runs where

| Part | How it runs | Address |
|---|---|---|
| Database | Supabase (cloud), from `REHEARSAL_DATABASE_URL` in `.env` | `db.<project-ref>.supabase.co` |
| API and console | Docker container `rehearsal-dev-api-1` (or `rehearsal serve` from source) | http://localhost:7800 |
| Workers | Processes on the host; they start sandboxes with the host's Docker | logs in `var/logs/` |
| Console dev server (optional) | `pnpm dev` in `web/`; proxies `/v1` to port 7800 | http://localhost:3000 |
| Test database | Local PostgreSQL in Docker, used only by the test suite | `127.0.0.1:5433` |

> **The cloud database is shared.** Local development reads and writes the same Supabase database as the hosted
> service, and `rehearsal migrate` changes its schema. Do not experiment with data you would not put in production.
> The test suite never touches it: `tests/conftest.py` always uses the local `rehearsal_test` database.

## First-time setup

1. Prerequisites: Python 3.11 or later, Docker, Node.js 22 with pnpm, and `uv` (for the agent plugin).
2. Install the package in editable mode:

   ```bash
   python -m venv ~/python && source ~/python/bin/activate
   pip install -e '.[dev,mcp,telemetry]'
   ```

3. Create `.env` from the example and fill it in. It is gitignored; never commit it.

   ```bash
   cp .env.example .env
   ```

   - `REHEARSAL_DATABASE_URL`: the Supabase URL for the `rehearsal` role (ask a maintainer). Keep
     `sslmode=verify-full` and the `sslrootcert=infra/certs/supabase-prod-ca-2021.crt` part.
   - `REHEARSAL_DB_POOL_SIZE=2` and `REHEARSAL_DB_MAX_OVERFLOW=3`: Supabase allows 60 connections, and every
     process (the API and each worker) can open up to 5.
   - Model provider keys (`NEBIUS_API_KEY`, `LITELLM_API_KEY`, ...), `GOOGLE_CLIENT_ID` for console sign-in,
     `TRACING_API_KEY` for traces.
   - Leave `REHEARSAL_PLANS=off` unless you are working on plans and billing. With it on, set the
     `DODO_PAYMENTS_*` test-mode values.

4. Apply the database migrations:

   ```bash
   rehearsal migrate
   ```

## Start the API and console (Docker)

```bash
docker build -t rehearsal:dev .
docker compose -f infra/compose.dev.yaml up -d --force-recreate
```

Open http://localhost:7800. The image builds the console from `web/`, so this serves the current UI. Check the
database it uses:

```bash
docker logs rehearsal-dev-api-1 2>&1 | grep database
# Rehearsal API on http://127.0.0.1:7800, database db.<project-ref>.supabase.co
```

After pulling new commits, rebuild and recreate:

```bash
git pull && docker build -t rehearsal:dev . && docker compose -f infra/compose.dev.yaml up -d --force-recreate
```

If the browser still shows the old page, hard-refresh it (Ctrl+Shift+R).

### Without Docker

```bash
(cd web && pnpm install && pnpm build)   # copies the console into rehearsal/api/static
rehearsal serve                          # http://127.0.0.1:7800
```

## Start the workers

Builds and evaluations run only when workers are running. Start them on the host, with the Python environment
active:

```bash
mkdir -p var/logs
for i in 1 2 3 4; do nohup rehearsal worker --kinds evaluation,improvement,dataset_export,bundle_export >> var/logs/worker-eval$i.log 2>&1 & done
for i in 1 2; do nohup rehearsal worker --kinds world_build >> var/logs/worker-build$i.log 2>&1 & done
nohup rehearsal worker --kinds world_validate >> var/logs/worker-validate.log 2>&1 &
```

Each worker logs the database it uses on its first line (`head -1 var/logs/worker-eval1.log`). Workers load the
code once at start, so restart them after pulling or editing Python code:

```bash
pkill -f 'rehearsal worke[r]'   # the brackets stop pkill from matching its own shell
```

Then start them again with the commands above.

## Console development with hot reload

```bash
cd web && pnpm install && pnpm dev
```

Open http://localhost:3000. API calls go to the server on port 7800, so keep it running.

## Sign in from the CLI

```bash
rehearsal login --url http://localhost:7800
rehearsal whoami
```

The browser opens the console; approve the code shown in the terminal. Without a browser, use
`rehearsal login --url http://localhost:7800 --with-key` and paste a key from the console's **API keys** page.

## Run the tests

The integration tests need the local test database on port 5433. `rehearsal up` starts it only when the database
URL points at this machine, so pass the local URL explicitly:

```bash
REHEARSAL_DATABASE_URL=postgresql+psycopg://rehearsal:rehearsal@127.0.0.1:5433/rehearsal rehearsal up
pytest -q
python scripts/build_agent_plugin.py --check
(cd web && pnpm build)
```

When PostgreSQL on port 5433 is not running, the integration tests are skipped, not failed: check the summary line.

## Stop everything

```bash
docker compose -f infra/compose.dev.yaml down
pkill -f 'rehearsal worke[r]'
```

After a reboot the API container starts again by itself (`restart: unless-stopped`). Start the workers again, and
start the test database with `docker start rehearsal-postgres-1`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `certificate verify failed` when connecting to Supabase | Keep `sslrootcert=` in the URL pointing at `infra/certs/supabase-prod-ca-2021.crt`. A stray `~/.postgresql/root.crt` is used otherwise. |
| `remaining connection slots are reserved` | Too many processes. Lower the worker count or `REHEARSAL_DB_MAX_OVERFLOW`. |
| Port 7800 is in use | Another server is running: `docker ps` and `ss -ltnp | grep 7800`. |
| Jobs stay queued | No worker for that job kind is running, or it runs old code. Check `var/logs/worker-*.log` and restart the workers. |
| Console shows the old UI | Rebuild the image and recreate the container, then hard-refresh. |
