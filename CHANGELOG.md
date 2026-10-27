# Changelog

Every release of `rehearsal-kit` has a section here. The publish workflow refuses a release whose version has no
section, so write it before tagging.

## 0.1.3

- `rehearsal-kit` is now also an npm package: the TypeScript SDK, the `rehearsal` CLI and the MCP server, with the
  same commands, tools and saved sign-in as the Python ones (`npm install rehearsal-kit`). Both packages are released
  together under one version; the server stays Python.
- Fix-my-agent loop (`rehearsal autofix`, `rh.profiles.autofix`, the MCP `fix_agent` tool): each round proposes a new
  agent version from failed train and dev episodes, rehearses it, and keeps it only if it verifies more episodes
  without a larger share of rule violations or false completions; the best version is then proven against the
  original on held-out jobs.
- Agent Factory (`rehearsal factory`, `rh.worlds.make_agent`): drafts an agent for a published world, hardens it with
  the fix loop, proves it on held-out jobs and packages a runnable agent with a proof report.
- CI checks: `rehearsal gate` passes or fails an agent change next to a baseline, and the GitHub Action
  (`uses: MitudruDutta/rehearsal@main`) runs it on pull requests.
- Why episodes failed: named causes per agent, most common first (`rehearsal runs failures`, `rh.runs.failures`,
  `GET /v1/runs/{id}/failures`), on the run page, in the MCP results and in the gate's report.
- Web research (`TAVILY_API_KEY`): a build studies how real people use the application and bases its jobs on what it
  finds, citing the pages. Without a key, or when the research cannot finish, jobs are planned from the source alone.
- Every role runs on NVIDIA Nemotron through Nebius Token Factory by default, routed by role
  (`REHEARSAL_MODEL_REASONER` is new); a chain entry can end in `#think` or `#nothink`. Builds, runs and fix loops
  show model usage by role.
- Builds survive more real applications: bounded API descriptions and source reads, a repair loop that keeps the
  runtime that got furthest across restarts, host-check refusals repaired with the real host names, and long JSON
  from a model repaired when an object in a list is left without its closing `}`.
- The `telemetry` extra and third-party tracing are removed; secrets are masked in one place.
- In the repository, the Python package moved to `rehearsal/py` and the npm package is in `rehearsal/ts`. From a
  checkout, install with `pip install -e './rehearsal/py[server,dev]'`.

## 0.1.2

- `rehearsal login` signs in through the browser: the terminal shows a code, you approve it in the console, and the
  terminal receives a "Build and evaluate" key. The key is created when the terminal collects it and is never stored
  readable. `--with-key` still pastes a key, for servers and CI.
- `rehearsal whoami` shows the server, workspace, key and where the sign-in comes from.
- `rehearsal --help` groups commands by task and describes every one; a mistyped command suggests the closest one.

## 0.1.1

- `rehearsal login` saves the server URL and an API key (readable by your user only); the CLI, the Python SDK and
  the MCP server use it when `REHEARSAL_API_KEY` and `REHEARSAL_URL` are not set. `rehearsal logout` removes it.
- The MCP server starts without a key and tells the assistant to ask for `rehearsal login`, instead of failing to
  connect.
- Agent plugin (`agent-plugin/`) for Claude Code, Codex, Cursor, Antigravity CLI and other agents: the Rehearsal skill plus the MCP
  server, started with `uvx` from PyPI.
- A write key can list what it changes; held-out jobs and verdicts still need the evaluator scope, which the
  console's "Build and evaluate" keys now carry.
- Database pool size is configurable (`REHEARSAL_DB_POOL_SIZE`, `REHEARSAL_DB_MAX_OVERFLOW`), for managed
  databases with a connection limit.
- Releases run the full test suite against PostgreSQL, refuse a version that is not higher than PyPI's, and start
  the built MCP server before uploading.

## 0.1.0

- First release: SDK, CLI, MCP server and agent skill; the server (`rehearsal-kit[server]`) with the World Compiler,
  workers, console, plans and Dodo Payments billing.
