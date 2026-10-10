# Changelog

Every release of `rehearsal-kit` has a section here. The publish workflow refuses a release whose version has no
section, so write it before tagging.

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
