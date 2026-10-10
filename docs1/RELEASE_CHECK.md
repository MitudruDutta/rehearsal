# Release verification — 10 October 2026

The current working tree produces installable `rehearsal-kit` 0.1.0 wheel and source archives. They pass the packaging checks below and are suitable for an alpha release. This is not production sign-off: live PostgreSQL, Docker, payment reconciliation, and trace delivery remain unverified.

Existing working-tree changes were preserved. Nothing was staged, committed, pushed, or uploaded to PyPI. No application server, worker, real model workflow, or payment was started. Recorder work was stopped at the user's request.

## Confirmed faults fixed

| Area | Result |
| --- | --- |
| Spend accounting | New `ModelSpend` ledger dates charges independently of job creation. Hosted projects share their workspace allowance; self-hosted projects share the server cap. Reservations serialize before checking remaining allowance. Usage and admin reporting use the ledger. |
| Retry accounting | Failed jobs reserve their remaining budget again. Build retries respect active-build capacity. Run commands continue viable sibling shards after allowance or capacity refusals and preserve concrete errors when none can restart. |
| Payment reconciliation | Payment/subscription synchronization paginates. Multi-product credits remain idempotent. Refunds match exact payment references and distinct invoice lines. Recorded payment ownership prevents duplicate grants to another workspace sharing a historical customer. Unrelated database integrity failures are no longer acknowledged as duplicate webhooks. |
| API boundaries | Budgets reject negative and non-finite values; explicit zero stays zero. Upload authentication happens before body reads. Upload/webhook bodies are bounded even without a trustworthy Content-Length and behind an ASGI root path. Login throttling includes an IP-wide limit and expires inactive keys. |
| Pricing | Capped jobs require a usable price before calling a model. Invalid provider-reported costs fall back to known prices. Temporary price-fetch failures retain the previous quote and retry sooner. |
| Recovery | Pause/stop heartbeats commit lease renewal before propagating commands. Environment failures survive episode persistence. Recoverable interruptions retain their sandbox. Shards exhausted by worker loss return unfinished episodes to viable siblings. |
| Sandbox connectivity | Containerized workers reach their world proxy through its external bridge. Host workers retain loopback routing. Proxy credentials bypass environment HTTP proxies. Destroying a world detaches remaining worker endpoints. |
| Evaluator resource limits | SQLite probes have a 15-second progress deadline, 1,000-row limit, 1 MiB value/row length limit, and 4 MiB collected result limit. Aggregates still inspect all input rows. Temporary connection limits and authorizers are restored. |
| SDK and CLI | SSE reconnects after ordinary EOF using the latest cursor. Non-object JSON error responses raise the SDK's normal error. Zero/negative wait timeouts cannot reference an unassigned result. Missing MCP dependencies produce an installation hint. |
| Distribution | Alembic's template is packaged. All migrations compile offline. URL-encoded database passwords survive Alembic configuration. The console was rebuilt from current source, including Billing/Admin pages; existing fonts and their licenses are bundled locally. |

## Verification completed

| Check | Result |
| --- | --- |
| Isolated unit suite | **526 passed** on Python 3.12.15; mocked providers and isolated SQLite tables, no live services |
| Python 3.11 syntax | All 63 package modules parsed successfully; this does not replace a Python-version runtime matrix |
| Console | Production Webpack export and TypeScript checks passed; temporary worker-thread settings accommodated this runner's process/socket restrictions |
| Migrations | Offline upgrade SQL through `0010` compiled, including ledger creation/backfill; encoded-password configuration tested |
| Distributions | Source archive built; wheel built from that source archive; strict Twine checks passed for both |
| Archive contents | 221 wheel entries and 292 source-archive entries checked; current package files, console, catalog, Compose file, skills, migration scripts/template, and font licenses present |
| Clean client install | Fresh virtual environment, offline dependency installation, `pip check`, SDK/CLI smoke checks passed with optional server/MCP packages absent |
| Installed server package | API/worker/MCP imports, OpenAPI generation, and migration-head discovery passed against existing dependency installations; no service launched |
| Credentials | Tracing and Nebius keys configured in ignored, untracked `.env`; configured credential values absent from both archives |
| Git whitespace | `git diff --check` passed; staging area left unchanged |

Reproduce the isolated unit suite from the repository root:

```bash
source ~/python/bin/activate
TRACING_API_KEY='' DODO_PAYMENTS_API_KEY='' DODO_PAYMENTS_WEBHOOK_KEY='' \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python -B -m pytest tests/unit --confcutdir=tests/unit \
  -p no:cacheprovider -p pytest_asyncio.plugin -q
```

## Release files

Files are in ignored `dist/`:

| File | SHA256 |
| --- | --- |
| `rehearsal_kit-0.1.0-py3-none-any.whl` | `cf22793b63a6e9465f4aecf500c0d6badee391c1e9a5819c042212e01196a4a5` |
| `rehearsal_kit-0.1.0.tar.gz` | `f0aa246543b8e9bb5876d142d6ccd98f2c35ea8aa196b646269608a3a3937fda` |

PyPI upload was not attempted. Registry ownership and version availability are separate publishing checks.

## Deployment requirements and remaining limits

- Stop existing workers, apply `rehearsal migrate` through `0010`, then restart the API and workers. Old totals retain creation-month allocation because individual historical charge timestamps do not exist; new charges use their actual month.
- Model budgets stop further work at usage checkpoints. In-flight calls can overshoot; they are not a provider-side hard spending ceiling.
- Partial refunds retain credits until the corresponding invoice line is fully refunded. Ambiguous or renamed multi-product invoice lines require reconciliation rather than guessed revocation.
- Live PostgreSQL migration execution, locking/concurrency behavior, Docker networking and recovery, Dodo sandbox webhook/reconciliation flows, and Tracing dashboard delivery still need environment-level verification. Socket restrictions prevented live database checks; application launch was also excluded by instruction.
- Only Python 3.12 runtime behavior was exercised. Server extras used existing dependencies for import verification; a clean client installation was verified separately.
- Training models and standalone bundle replay remain outside this alpha's implemented features, as documented in the package README.
- `docs/BUSINESS.md` contains reported planning tool results; a verifiable plan link is still absent.
