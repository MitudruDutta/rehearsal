# Documentation website plan

Status: proposal, 10 October 2026. Owner: the founders. This plan covers what the Rehearsal documentation site is for, who reads it, what every page contains, how it is built and kept true, and the order to build it in.

## 1. Purpose

The documentation site has four jobs, in priority order:

1. **Get a new user to a first verified result fast.** A developer signs up, connects an application or uses a sample world, runs an agent, and reads why an episode failed, without help from us.
2. **Let AI assistants use Rehearsal correctly.** Claude Code, Codex, Cursor, Hermes, OpenClaw and other agents read the docs (through the skill, `llms.txt`, and a docs search tool) and drive Rehearsal through MCP. The docs must be as precise for them as for people.
3. **Make the product trustworthy.** Explain exactly how scoring works, what touches the user's data (nothing in production), what costs money, and what each plan allows. Unclear docs cost trust.
4. **Let teams self-host and operate it.** Requirements, deployment, scaling, backups, upgrades, security hardening.

Non-goals: marketing copy (the landing page does that), internal design notes (stay in `docs/` in the repository), and blog posts.

## 2. Readers

| Reader | What they want | Where they start |
|---|---|---|
| Agent developer (main reader) | Test their agent before launch; see failures; improve it | Quickstart, then Guides |
| AI coding assistant | Exact tool names, arguments, errors, costs; what to ask the user before spending | Skill, MCP reference, `llms.txt` |
| Platform or ML engineer | CI gating on held-out scores, API, SDK, bring-your-own agent | API and SDK reference, CI guide |
| Product or QA lead | Readiness board, what "verified" means, comparisons | Concepts, Reading results |
| Self-hoster or operator | Run the server, workers and sandboxes; managed database; limits | Self-hosting |
| Buyer or security reviewer | Data handling, isolation, plans, enterprise | Security and trust, Plans |

## 3. Success measures

| Measure | Target in the first 3 months |
|---|---|
| Time from sign-up to first finished run, for users who follow the Quickstart | under 15 minutes on a sample world |
| Support questions answered by an existing page (we link a page instead of writing a new answer) | 80% |
| Pages with a working "Copy as Markdown" and an entry in `llms.txt` | 100% |
| Broken links and failing code samples in CI | 0 (CI blocks the merge) |
| Reference pages generated from code, not written by hand (API, CLI, MCP tools, configuration) | 100% |
| "Was this page helpful?" score | 80% yes or better; every "no" reviewed weekly |

## 4. Technology

### 4.1 Recommendation: Fumadocs on Next.js, static export

| Option | For | Against | Verdict |
|---|---|---|---|
| **Fumadocs** (Next.js, MDX) | Same stack as the console (Next.js, React, Tailwind, shadcn/ui): shared theme, fonts and components. OpenAPI pages generated from our schema. Built-in search (Orama). Static export. Free, open source | We maintain it ourselves | **Chosen** |
| Mintlify | Fastest to set up, polished, hosted, API playground | Paid as the team grows; theme separate from the console; less control over generated pages | Good fallback if time is short |
| Docusaurus | Mature, versioning built in | React but a different stack; heavier theme work to match the console | No |
| Starlight (Astro) | Very fast, good defaults | Different stack from the console; components not shared | No |
| Nextra | Next.js, simple | Fewer reference generators than Fumadocs | No |

### 4.2 Building blocks

- **Location:** `docs-site/` in this repository, as a pnpm workspace package next to `web/`. Docs change in the same pull request as the code they describe.
- **Content:** MDX in `docs-site/content/docs/`, one file per page, front matter with `title`, `description`, `audience`, `last_reviewed`.
- **Theme:** the console's Studio theme tokens (colors, radius), fonts (Bricolage Grotesque for headings, Instrument Sans for body; both already bundled with OFL licenses), dark and light mode.
- **Search:** Orama (built in, runs in the browser, no account). Later: Algolia DocSearch (free for open-source projects) if search quality needs it.
- **Code blocks:** syntax highlighting (Shiki), copy button, tabs for "Console / CLI / Python / MCP / HTTP", and tabs per AI client.
- **Diagrams:** hand-made SVG in both themes for the architecture, the World Compiler phases, the episode lifecycle and the job queue. No diagram images of text.
- **Hosting:** Cloudflare Pages or Vercel, static files, at `docs.<domain>`. A preview deploy for every pull request. `sitemap.xml`, `robots.txt`, Open Graph images per page.
- **Analytics:** privacy-friendly (Plausible or Umami), no cookies, no cookie banner. Track page views, search terms with no results, and the helpful votes.
- **Feedback:** "Was this page helpful?" on every page; "no" opens a short form or a prefilled GitHub issue with the page URL.

## 5. Information architecture

Top navigation: **Get started · Guides · AI assistants · Reference · Self-hosting · Plans · Security**. A version badge shows the current package version (from `pyproject.toml`).

Every page below lists its purpose and the sections it must contain. "Generated" means the page body comes from code (section 7).

### 5.1 Get started

| Page | Purpose | Sections |
|---|---|---|
| What is Rehearsal | One page that answers "what, why, how" | The question it answers; a practice world in one diagram; what "verified" means; what it is not (not an LLM judge, not production testing); next steps |
| Quickstart: console (10 minutes) | First run without code | Sign in with Google; pick a sample world or add an application; run the baseline agent; read the readiness board; open a failed episode; next steps |
| Quickstart: CLI and Python | Same result from a terminal | `pip install rehearsal-kit`; `rehearsal login`; `rehearsal worlds list`; `rehearsal eval`; `rehearsal runs watch`; the same in Python with `Rehearsal()` |
| Quickstart: with your AI assistant | Same result by asking Claude Code, Codex or another agent | Install the plugin for your client (tabs); `rehearsal login`; example prompts; what the assistant asks before spending |
| Core concepts | The vocabulary, once | Application; world and world version; job (scenario) and split (train, dev, holdout); agent profile and version; run; episode; verified, rule violated, not achieved; simulated customer and goal revisions; faults and the default stress layer; stress categories; readiness |
| How scoring works | The trust page | Read-only SQL checks against the app's own database; why no model grades results; duplicate side effects; false completion; held-out jobs; live fairness audit at build time and what "withdrawn" means; worked example with a real failed check |

### 5.2 Guides

| Page | Sections |
|---|---|
| Add an application | Requirements (containers, HTTP or GraphQL API, SQLite/PostgreSQL/MySQL); public git repository at a pinned commit; pinned images with digests; owner policies in plain words; upload a source archive; remove an application; plan limits |
| Build a practice world | What the World Compiler does, phase by phase (inspect, plan, materialize, discover, seed, adapt, author, validate, package); typical time and cost by app size (measured table); watching a build; budget and spend cap; what to do when a build fails (restart from the last step, when not to restart); plan limits and the free build |
| Review the jobs in a world | Job list, splits, stress labels; approve and reject; re-check a published world; why a job was withdrawn; propose your own job |
| Evaluate an agent | Choose world version, agents, splits, repeats; default stress layer; episode count and cost formula; sandboxes and parallel shards; quiet hours on the free plan; stop, pause, restart a run |
| Read results | Readiness verdicts; per-split and per-category scores; endings; failed checks with observed vs wanted; duplicate effects; faults; the episode timeline and the live room view |
| Improve an agent | How the improvement agent uses train and dev failures only; review the proposed version; evaluate both on holdout; keep or discard |
| Compare agents and runs | Within one run; across runs on the same world version; why different world versions are not comparable |
| Bring your own agent | The external-turn loop (observation, action, idempotency key); LangGraph example; OpenAI Agents SDK example; a 40-line plain HTTP loop; acting as the agent from an AI assistant (MCP `waiting_turns` and `take_action`); rules: one action per turn, timeouts |
| Intervene during an episode | Send a customer message or change the goal live; when it is useful |
| Use Rehearsal in CI | GitHub Actions example: run holdout on every pull request that changes the agent, fail below a score, post the summary; API key with the right access stored as a secret; cost control |
| Export data | Verified trajectories as a dataset; world bundles; replay files |
| Training (coming soon) | What exists today (verified rewards, dataset export) and what is planned |

### 5.3 AI assistants

| Page | Sections |
|---|---|
| Overview | What the plugin installs (skill + MCP server); `rehearsal login`; client matrix; what an assistant may do; cost confirmations |
| Claude Code | Marketplace install; optional plugin options in `/config`; verify with `/mcp`; example prompts; uninstall |
| Codex | Marketplace install; verify; example prompts |
| Cursor | Local plugin install; verify; MCP settings alternative |
| Antigravity CLI (formerly Gemini CLI) | `agy plugin install` of the Antigravity bundle; MCP-only setup in `mcp_config.json` |
| GitHub Copilot (CLI and VS Code) | Copilot CLI marketplace; VS Code `.vscode/mcp.json` |
| Hermes Agent | Plugin folder; `hermes mcp add` or `~/.hermes/config.yaml`; skill folder |
| OpenClaw | Plugin folder; `openclaw mcp add` or `openclaw.json`; `skills.load.extraDirs` |
| Goose, Factory Droid, Augment, Grok Build, Devin, Qwen Code | One short section each with the install command |
| Windsurf, Cline, Roo Code, Kiro, Zed, Claude Desktop | MCP JSON per client; skill install with `rehearsal skill install --dir` |
| MCP tool reference (generated) | All 18 tools: purpose, arguments with types, return shape, errors, whether it spends money, example call |
| The Rehearsal skill | What it teaches; the decision rules (ask before spending, never restart twice for the same error); install for skill-only clients |
| Security model for assistants | Keys and access levels; why the key is never pasted into chat; revoking; plan limits as a hard stop |

### 5.4 Reference

| Page | Source |
|---|---|
| REST API (69 operations in groups: auth, applications, world builds, worlds and scenarios, jobs and events, agent profiles, evaluations and runs, episodes and external agents, improvements and exports, artifacts, usage and billing, admin) | Generated from the FastAPI OpenAPI schema (`rehearsal openapi`) |
| Python SDK | Generated from docstrings and signatures of `rehearsal.sdk` |
| CLI | Generated from the argparse definitions (`rehearsal <command> --help`) |
| MCP tools | Generated from the FastMCP server's tool list and docstrings |
| Events (SSE) | Generated from the event types the engine and workers emit, with example payloads |
| Errors | Every HTTP status with its meaning and the CLI hint (from `rehearsal/sdk/cli.py` HINTS); 402 plan and allowance messages; 429 capacity messages |
| Access levels (scopes) | admin, write, read, evaluator, agent; what each implies; which console option creates which |
| Configuration | Generated from `rehearsal/config.py` and `.env.example`: every variable, default, and what it changes (the 29 `REHEARSAL_*`, `DODO_*`, `GOOGLE_*` and provider variables) |
| Plans and limits | Generated from `rehearsal/billing.py` `PLANS`, so the docs can never disagree with enforcement |
| Model providers and pricing | Provider chains; where each price comes from (provider-reported, price list, override); `rehearsal prices` |
| Glossary | One line per term, linked from Core concepts |

### 5.5 Self-hosting

| Page | Sections |
|---|---|
| Architecture | API, PostgreSQL job queue, workers, sandboxes, console; one diagram; what scales how |
| Requirements | Linux with Docker; CPU and memory per build and per sandbox (measured); disk for snapshots |
| Install with Docker Compose | `infra/compose.full.yaml`, `deploy.env`, Caddy and TLS, first admin |
| Use a managed database | Supabase (role and schema, never `public`; verified TLS with the bundled CA; connection limits and pool settings), Neon and others; what not to use and why (scale-to-zero with an always-polling queue) |
| Workers and scaling | Worker kinds; parallel shards and build lanes; leases and restarts; per-workspace limits |
| Sandboxes and isolation | Network without internet, resource limits, cleanup sweep, what an agent can and cannot reach |
| Model providers | Configure chains; keys; fallbacks; cost recording |
| Observability | neatlogs traces; logs; health endpoint |
| Backups and restore | Nightly `pg_dump` to object storage; the data folder (snapshots, artifacts); restore drill |
| Upgrades | `rehearsal migrate`; release notes; rollback |
| Hardening checklist | Session secret, sign-up mode, admin emails, trusted proxies, HTTPS only, key scopes |

### 5.6 Plans, billing, security, and the rest

- **Plans (hosted):** Free, Pro, Team, Enterprise; what counts as an episode or build; quiet hours; top-ups; failed builds are restarted for free; what happens when a payment fails (grace period, on hold); invoices and the payment portal; FAQ.
- **Security and trust:** fictional data only, no production access; sandbox isolation; read-only checks; secrets handling (keys hashed at rest, provider keys server-side); data retention; responsible disclosure contact.
- **Changelog:** rendered from `CHANGELOG.md`.
- **Roadmap:** training (coming soon), docs search tool, more sample worlds.
- **FAQ and Troubleshooting:** the troubleshooting tables from the skill, extended with screenshots.

## 6. Page templates and writing rules

### 6.1 Templates

| Type | Required parts |
|---|---|
| Concept | One-paragraph answer first; diagram if there is a flow; "what it is not"; links to guides |
| Guide | Goal in one line; prerequisites; numbered steps with one action each; expected result after key steps; troubleshooting; next steps |
| Reference | Generated body; one human-written intro paragraph; examples for every operation |
| Client page (AI assistants) | Install; sign in; verify; example prompts; uninstall |

### 6.2 Writing rules

- **ASD-STE100 Simplified Technical English** for all prose: one idea per sentence, short sentences, active voice, imperative instructions, the same word for the same thing on every page.
- Name things the way the console names them ("world", "job", "episode", "Build and evaluate").
- Every code sample runs as written; placeholders look like `<world_version_id>`.
- Costs and times come from measured numbers with the date measured.
- Never document behavior that the code does not have; mark planned features "coming soon".
- Screenshots only where the UI is the point, captured from the sample worlds, refreshed with each console change.

A Vale configuration in CI enforces the vocabulary list and flags passive voice and long sentences.

## 7. Single source of truth

Hand-written reference pages drift. These are generated in CI and committed only as build output:

| Content | Generator | Drift check in CI |
|---|---|---|
| REST API | `rehearsal openapi` → `fumadocs-openapi` | OpenAPI file regenerated and compared |
| CLI | Script walks the argparse parser | Regenerated and compared |
| MCP tools | Script imports `build_server()` and lists tools with their schemas | Regenerated and compared |
| Configuration | Script reads `Settings` fields and `.env.example` comments | Regenerated and compared |
| Plans and limits | Script reads `billing.PLANS` | Regenerated and compared |
| Skill and client install commands | `agent-plugin/README.md` and the skill files, included directly | Already checked by `scripts/build_agent_plugin.py --check` |
| Changelog | `CHANGELOG.md` | Included directly |

Code samples: every Python and shell sample in guides is extracted and run in CI against a test server with a published sample world (the same PostgreSQL service the Tests workflow uses). A sample that fails blocks the merge.

## 8. Built for AI readers

- `/llms.txt`: an index of every page with a one-line description; `/llms-full.txt`: all pages as plain Markdown.
- Every page has a "Copy as Markdown" button and is also served at `<page>.md`.
- A `search_docs` MCP tool in the Rehearsal MCP server (later phase), so an assistant can search the docs while it works, like Dodo's knowledge server.
- The skill links to the matching docs pages for depth, so the skill stays short.
- Stable page URLs and anchors; old URLs redirect.

## 9. Quality gates (CI, on every pull request that touches docs or code)

1. Docs site builds (static export).
2. Generated references match the code (section 7).
3. Link check (internal and external) with lychee.
4. Code samples run (section 7).
5. Vale style checks.
6. Accessibility check on built pages (axe): headings, contrast, alt text.
7. Preview deploy link posted on the pull request.

The pull request template gets a checkbox: "Docs updated, or not needed because …".

## 10. Versioning

Until 1.0, the site documents the latest release only, and the changelog says what changed. From 1.0, the site keeps one folder per minor version for the API and SDK reference, with a version switcher; guides stay unversioned unless behavior differs.

## 11. Delivery plan

| Phase | Scope | Estimate | Exit criteria |
|---|---|---|---|
| 0. Scaffold | `docs-site/` with Fumadocs, theme from the console, navigation, search, Cloudflare Pages preview deploys, `llms.txt` | 1 day | Empty site deploys on every pull request |
| 1. Launch set | What is Rehearsal; three Quickstarts; Core concepts; How scoring works; AI assistants overview and the Claude Code, Codex, Cursor, Hermes and OpenClaw pages; MCP and CLI reference (generated); Plans | 3 to 4 days | A new user reaches a first run from the docs alone; references generated and drift-checked |
| 2. Depth | All Guides; REST API and SDK reference; Configuration; Errors; Self-hosting; Security and trust; remaining client pages | 1 to 2 weeks | Every console screen and CLI command has a page that explains it |
| 3. Hardening | Code samples run in CI; Vale; link and accessibility checks; feedback widget; analytics | 3 to 4 days | All gates in section 9 block merges |
| 4. Assistant-first | `search_docs` MCP tool; per-page Markdown; skill links into docs | 2 to 3 days | An assistant answers a "how do I" question by searching the docs through MCP |
| 5. Scale | Versioned reference from 1.0; translations if users need them | later | — |

## 12. Decisions needed from the founders

1. Domain for the docs (`docs.<domain>`), and the product domain itself.
2. Hosting: Cloudflare Pages (recommended: free, fast, preview deploys) or Vercel.
3. Fumadocs (recommended) or Mintlify if launch time matters more than cost and control.
4. Whether the agent plugin moves to its own repository (`rehearsal-agent-plugin`), which several clients need for one-command installs; the docs would then link there.
5. Support contact for the "Security" and "Plans" pages.
