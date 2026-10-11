# Rehearsal documentation site: product requirements

Status: draft for review, 10 October 2026. Owner: the founders.

This document says what the documentation site must do for the people who read it, what it must contain, and how it must look. It is the PRD. `DOCS_SITE_PLAN.md` in this folder is the build plan: tooling, generators, CI gates, and estimates. Where the two disagree, section 14 lists the point as a decision.

Inputs:

- `REHEARSAL_SPEC.md` (the implementation specification), read in full.
- `DOCS_SITE_PLAN.md`, `PACKAGE.md`, the root `README.md`, `CHANGELOG.md`, and the agent skill in `rehearsal/assets/skill/`.
- The product itself at version 0.1.1: the CLI, the API schema, the MCP server, the console, and `rehearsal/billing.py`. Appendix A records what was counted, and how.
- One real installation of the product on a new machine on 10 October 2026. The problems it hit are in section 2 and appendix B.

---

## 1. Summary

Rehearsal needs a documentation site that a new user can follow, alone, from sign-up to a first verified result, and that answers each later question on one page.

The site will:

1. Teach the product through seven journeys (section 5). Six are required at launch, and each is tested with a person who has never used Rehearsal.
2. Contain only behaviour the product has today. Reference pages are generated from the code, and planned features carry a "Coming soon" label.
3. Look like the console: the same colours, fonts, and status meanings, arranged for reading (section 9).
4. Serve AI assistants as well as people: every page is available as Markdown, and the site publishes `llms.txt`.

The site is built in `docs/`, which today holds an unmodified Next.js starter. The launch set is 27 pages (section 7). The landing page's "Docs" link currently opens the server's generated API page, so the launch set also fixes that link.

---

## 2. The problem

### 2.1 What a new user finds today

- **The "Docs" link leads to an API listing.** The landing page links to `/docs` on the server, which is the automatically generated API page. It lists 68 operations and says nothing about what to do first.
- **Help is spread over six places.** The root README, `PACKAGE.md`, the agent skill and its five reference files, the agent plugin README, `rehearsal --help`, and the console itself. None links to the others in a reading order.
- **The specification is the wrong source for users.** It is an internal design document. It describes planned work beside shipped work, and several of its examples are marked "proposed". Section 6 lists where it differs from the product.

### 2.2 What went wrong in a real installation

Setting the product up on a new Windows machine on 10 October 2026 showed these problems. No page explained any of them at the time. Each one is now required content (appendix B).

| # | What happened | Why |
|---|---|---|
| 1 | The console showed a sign-in form and there was no account to sign in with | The console needs a person's account. Sign-up is closed by default. The account is made with `rehearsal users add` |
| 2 | A world build failed in its first step with `inspector: model unavailable` | No model provider key was configured |
| 3 | A world build failed with `Filename too long` while fetching the application's source | Windows limits paths to 260 characters unless long paths are enabled, and each source checkout sits under a 64-character folder name |
| 4 | Building the console from PowerShell failed with `'rm' is not recognized` | The build script uses `rm` and `cp`. It works from Git Bash |
| 5 | The Docker Compose stack refused to start | It needs a database password and a session secret first |
| 6 | After a Docker restart the API came back but the database did not | The compose file gives the database no restart policy |
| 7 | A build stayed queued | No worker was running. The worker is a separate service |

The root README now mentions items 1 to 5 and the worker, briefly. Item 6 is not written down anywhere. A README is also not where a user looks when a message appears on screen: the fix has to be findable by searching for the message.

### 2.3 What this costs

A user who cannot reach a first result leaves. A user who reaches one but does not understand how an episode is scored does not trust the result. An AI assistant that reads imprecise instructions spends the user's money on the wrong action. The documentation is the cheapest place to prevent all three.

---

## 3. Goals, non-goals, and measures

### 3.1 Goals

1. **First result without help.** A developer follows a quickstart and reaches a finished run with a verdict.
2. **One page per question.** Every console screen, CLI command, API operation, MCP tool, setting, and error has a page that explains it.
3. **Trust.** The site states exactly how scoring works, what touches the user's data, what costs money, and what each plan allows.
4. **Correct for machines.** An AI assistant can find the exact tool, argument, and cost rule it needs.
5. **Self-hosting.** A team can install, run, upgrade, and secure its own server from the docs.

### 3.2 Non-goals

- Marketing copy. The landing page does that.
- Internal design notes, the business plan, and release procedures. They stay in the repository (`docs1/` today).
- Describing features that are not built, except on one labelled roadmap page.
- A blog, a forum, or translated pages at launch.

### 3.3 Measures

The first six come from `DOCS_SITE_PLAN.md` section 3. The last two are new.

| Measure | Target in the first 3 months |
|---|---|
| Time from sign-up to a first finished run, following the console quickstart | under 15 minutes on a sample world |
| Support questions answered by linking an existing page | 80% |
| Pages with "Copy as Markdown" and an entry in `llms.txt` | 100% |
| Broken links and failing code samples in CI | 0 |
| Reference pages generated from code | 100% |
| "Was this page helpful?" | 80% yes; every "no" reviewed weekly |
| Pages that describe behaviour the product does not have | 0, checked at each release |
| Journeys in section 5 completed by a first-time user from the docs alone | J1 to J6 before launch; J7 before the depth phase ends |

---

## 4. Readers

| Reader | What they need to do | Their first three questions | Where they start |
|---|---|---|---|
| Agent developer (main reader) | Test an agent before launch, see why it failed, improve it | What is a practice world? How do I run my agent? Why did this episode fail? | Quickstart |
| AI coding assistant | Drive Rehearsal for a user through MCP | Which tool does this? What are its arguments? Must I ask before it spends money? | `llms.txt`, MCP reference, the skill |
| Platform or ML engineer | Put Rehearsal in CI; connect an agent written in another language | How do I authenticate? How do I submit actions? How do I fail a build on a low score? | API reference, CI guide |
| Product or QA lead | Decide whether an agent is ready | What does "verified" mean? Can I compare two versions? What does a failed check show? | Core concepts, Read results |
| Self-hoster or operator | Run the server, workers, and sandboxes | What do I need? How do I install it? How do I back it up and upgrade it? | Self-hosting |
| Buyer or security reviewer | Approve the product | Does it touch production? Where do keys live? What does each plan allow? | Security and trust, Plans |

---

## 5. Journeys the docs must carry

Each journey is a test. A person who has not used Rehearsal completes it using only the docs. Where they stop or ask a question, a page is wrong. J1 to J6 use only launch pages and must pass before launch. J7 needs pages from the depth phase.

| # | Journey | Reader | Pages, in order | Done when | Needed |
|---|---|---|---|---|---|
| J1 | First result in the console | Agent developer | What is Rehearsal → Quickstart: console → Read results | They open a failed episode and can say which check failed | Launch |
| J2 | First result from a terminal | Agent developer | Quickstart: CLI and Python → Sign in and keys → Read results | `rehearsal eval ... --watch` finishes and prints a summary | Launch |
| J3 | First result through an AI assistant | Agent developer with Claude Code, Codex, or Cursor | AI assistants: overview → their client's page → What costs money | The assistant runs an evaluation after asking before it spends | Launch |
| J4 | From a failure to a better agent | Agent developer | Read results → Improve an agent → Compare agents and runs | They compare two versions on held-out jobs and choose one | Launch |
| J5 | Test an agent they wrote themselves | Platform engineer | Bring your own agent → Errors | Their code completes one episode through the API. The guide must show the whole loop itself, because the full API reference comes later | Launch |
| J6 | Run their own server | Operator | Requirements → Install with Docker Compose → Sign in and keys → Troubleshooting | The console opens, they sign in, and a build starts | Launch |
| J7 | Gate a pull request on a score | Platform engineer | Use Rehearsal in CI → Access levels → Plans and limits | A CI job fails when the held-out score drops | Depth |

---

## 6. Using the specification as a source

The specification explains why the product works the way it does. That makes it the right source for concept pages. It is the wrong source for instructions and reference, because parts of it describe a proposal.

### 6.1 Rule

- **Concepts and reasoning** may be taken from the specification, rewritten for users, and checked against the product.
- **Commands, endpoints, arguments, settings, and limits** are never taken from the specification. They are generated from the code.

### 6.2 What each part of the specification becomes

"Checked" means the claim was compared with the product at 0.1.1 for this PRD.

| Specification section | Use in the docs | Status in the product (checked) | Treatment |
|---|---|---|---|
| Product; §13 Final outcomes | What is Rehearsal | Matches | Rewrite for users |
| §1 What an application becomes (runtime, state, actions, observations, reset, events, verifier, provenance) | Core concepts | Matches | One diagram and plain definitions |
| §1 Connection modes (source-backed, sandbox-backed, browser-backed, emulated) | Add an application | **Differs.** The API accepts only the source-backed mode | Document source-backed only. List the others on the roadmap page |
| §1 Compilation pipeline (9 steps) | Build a practice world | **Differs in naming.** The product's nine phases are inspect, plan, materialize, discover, seed, adapt, author, validate, package. Repair happens inside validate | Use the product's phase names, which the console shows |
| §2 Roles (inspector, builder, scenario designer, and others) | Build a practice world; How scoring works | Matches | Explain as "who does what" beside the build view |
| §3 One complete episode; changed-intent and race rules | Core concepts; Read results | Matches (`UNKNOWN` outcomes, `retry_operation` only where proven safe) | Use the worked example. Keep the status names exact |
| §4 Fidelity and grading (five properties; reward 1, 0, -1; train, dev, holdout) | How scoring works | **Partly.** The reward and the three splits match. A build checks that a world resets, that each job can be passed, and that careless attempts fail, and it records isolation facts. No comparison of behavioural fidelity was found in the code | This is the trust page. Describe the checks that run, with one real failed check. Do not claim all five properties |
| §5 Training (evaluation, policy optimisation, fine-tuning, reinforcement learning) | Improve an agent; Export data; Roadmap | **Partly built.** Evaluation, the improvement job, and dataset export exist. `rehearsal train` and the training endpoint answer "coming soon" | Document what exists. Label training "Coming soon" |
| §6 Technology and execution trust | Self-hosting: architecture; Security and trust | Matches in outline | Rewrite. Remove options that were not chosen |
| §7 Credential model | Sign in and keys; Access levels; Security | Matches for API keys and server-side provider keys. Bring-your-own-key storage is not confirmed as built | Document keys and access levels from the code |
| §7 "Proposed Python SDK" | None | **Differs.** The shipped client is `rehearsal.sdk.Rehearsal` with different calls | Do not copy. Generate the SDK reference |
| §7 "Proposed REST surface" | None | **Differs.** `POST /v1/runners/register` does not exist. Validation is at `/v1/world-versions/{id}/validate`, not `/v1/worlds/{version}/validate` | Do not copy. Generate from the API schema |
| §7 Portable artifact | Export data | **Partly built.** Bundles can be exported. `rehearsal run-bundle` is not implemented | Document export. Label replay "Coming soon" |
| §8 Event envelope | Reference: events | **Close.** The product sends `stream` where the specification has `run_id`, and adds a `data` field | Generate from the event types the product emits |
| §9 User interface (seven screens) | Guides, one per screen | **Differs.** The console has 12 screens (appendix A). There is no training screen or scenario studio | Follow the console as built |
| §10 tracing | Self-hosting: observability | Matches (optional, off without a key) | Document |
| §10 Recorder; §0 Hackathon fit; §11 Repository; §12 Acceptance | None | Internal | Not in the docs |

---

## 7. Content requirements

### 7.1 Priorities

- **P0, launch set (27 pages):** the pages journeys J1 to J6 need, plus the pages a reader needs to trust the product. The site does not launch without them.
- **P1, depth:** the rest of the guides, reference, and self-hosting.
- **P2, later:** pages that depend on features or decisions that do not exist yet.

The page list follows `DOCS_SITE_PLAN.md` section 5. This PRD adds priorities, the question each P0 page must answer, and four pages the plan does not have: Sign in and keys, What costs money, Run on Windows, and the roadmap of features not yet built.

### 7.2 Get started

| Page | Pri | The reader must be able to answer | Source of truth |
|---|---|---|---|
| What is Rehearsal | P0 | What is a practice world? Who decides whether my agent passed? What is this not? | Specification (Product, §1, §4), rewritten |
| Quickstart: console | P0 | How do I get a result in 10 minutes without writing code? | The console, walked through on a sample world |
| Quickstart: CLI and Python | P0 | How do I get the same result from a terminal or a script? | `rehearsal login`, CLI help, `rehearsal.sdk` |
| Quickstart: with an AI assistant | P0 | How do I install the plugin and what do I ask? | `agent-plugin/README.md`, the skill |
| Sign in and keys | P0 | What is the difference between my console account and an API key? Which access level do I need? How do I revoke a key? | `rehearsal/api/auth.py`, console API keys screen |
| Core concepts | P0 | What do application, world, world version, job, split, agent profile, run, episode, and verdict mean? | Specification §1 to §4, product names |
| How scoring works | P0 | How is an outcome decided? Why can't a model talk its way to a pass? What do "duplicate effect", "false completion", and "withdrawn job" mean? | `rehearsal/evaluator/`, specification §4 |
| What costs money | P0 | Which actions spend model budget? How much, roughly? How do I set a limit? What happens when I reach it? | `rehearsal/billing.py`, measured numbers with dates |

### 7.3 Guides

| Page | Pri | The reader must be able to answer |
|---|---|---|
| Add an application | P0 | What must my application have? How do I pin the source and the images? How do I state my policies? |
| Build a practice world | P0 | What happens in each of the nine phases? How long and how much? What do I do when a build fails, and when must I not restart? |
| Evaluate an agent | P0 | How do I choose jobs, splits, and repeats? How many episodes is that? How do I stop a run? |
| Read results | P0 | What does each verdict and ending mean? How do I read a failed check? Where is the timeline? |
| Improve an agent | P0 | What does the improvement step read, and what may it change? How do I check the new version fairly? |
| Compare agents and runs | P0 | Which runs can be compared, and why not across world versions? |
| Bring your own agent | P0 | What is the loop? What is an idempotency key for? What happens when my agent is slow? |
| Review the jobs in a world | P1 | How do I approve, reject, re-check, or propose a job? |
| Intervene during an episode | P1 | How do I change the request or inject a fault while it runs? |
| Use Rehearsal in CI | P1 | How do I fail a pull request on a held-out score? |
| Export data | P1 | How do I get verified trajectories and world bundles? |

### 7.4 AI assistants

| Page | Pri | Notes |
|---|---|---|
| Overview | P0 | What the plugin installs, signing in, what an assistant may do, and when it must ask |
| Claude Code, Codex, Cursor (one page each) | P0 | Install, sign in, verify, example prompts, uninstall |
| MCP tool reference | P0 | Generated. All 18 tools: purpose, arguments, result, errors, and whether the tool spends money |
| Other clients (Antigravity CLI, Copilot, Hermes, OpenClaw, and the rest) | P1 | Same template |
| The Rehearsal skill; Security model for assistants | P1 | Decision rules; why a key is never pasted into chat |

### 7.5 Reference

All generated unless marked.

| Page | Pri | Source |
|---|---|---|
| CLI | P0 | The argparse definitions (27 commands) |
| Errors | P0 | HTTP statuses with the CLI's hints; plan and capacity messages. Introduction written by hand |
| Plans and limits | P0 | `billing.PLANS`, so the page cannot disagree with enforcement |
| REST API | P1 | The API schema (68 operations in 28 groups) |
| Python SDK | P1 | `rehearsal.sdk` |
| Events | P1 | Event types the product emits, with one example each |
| Access levels | P1 | `auth.py` |
| Configuration | P1 | `config.py` and `.env.example` (36 settings) |
| Model providers and pricing | P1 | Provider chains and price sources |
| Glossary | P1 | Written by hand, linked from Core concepts |

### 7.6 Self-hosting

| Page | Pri | The reader must be able to answer |
|---|---|---|
| Requirements | P0 | Which operating system, how much memory and disk, which model key? Is Windows supported? |
| Install with Docker Compose | P0 | Which two secrets must I set? How do I start the database, the API, and the worker? How do I create the first admin and my sign-in? |
| Troubleshooting | P0 | Every entry in appendix B |
| Architecture | P1 | What are the API, the queue, the workers, and the sandboxes, and what scales how? |
| Workers and scaling | P1 | Why are my builds queued? How many workers do I need? |
| Run on Windows | P1 | How do I run Docker Engine in WSL, keep it running, and avoid the path limit? |
| Managed database; Sandboxes and isolation; Model providers; Observability; Backups; Upgrades; Hardening checklist | P1 | As listed in `DOCS_SITE_PLAN.md` section 5.5 |

### 7.7 Plans, trust, and the rest

| Page | Pri | Notes |
|---|---|---|
| Security and trust | P0 | Fictional data only, no production access, sandbox isolation, read-only checks, where keys live |
| Plans (hosted) | P1 | What an episode and a build count as, quiet hours on the free plan, top-ups, failed payments |
| Changelog | P1 | Rendered from `CHANGELOG.md` |
| Not built yet | P1 | One page for training, bundle replay, and the other connection modes. The only place planned features appear |
| FAQ | P2 | Grown from real questions, not written in advance |

---

## 8. Functional requirements

Each requirement can be tested. "Must" means launch depends on it.

### 8.1 Finding a page

| ID | Requirement | Pri |
|---|---|---|
| FR-1 | The header shows the site sections. The sidebar shows every page of the current section, with the current page marked. | Must |
| FR-2 | Search opens with `Ctrl K`, `⌘K`, or `/`, and from a visible field in the header. | Must |
| FR-3 | Search results are grouped by section and show the page title, the matching heading, and a line of text. Arrow keys and Enter work. | Must |
| FR-4 | Search finds exact strings a user would paste: an error message, a setting name such as `REHEARSAL_SIGNUP`, a CLI command, an API path, an MCP tool name. | Must |
| FR-5 | A search with no result offers the troubleshooting page and the three most-read pages. The query is recorded without identifying the user. | Should |
| FR-6 | Every page shows where it sits (breadcrumb) and links to the previous and next page of its section. | Must |
| FR-7 | Every heading has a stable link that can be copied. Old addresses redirect when a page moves. | Must |
| FR-8 | A page with more than two headings shows an "On this page" list that follows the scroll position. | Must |
| FR-9 | The page that does not exist offers search and the quickstarts. | Should |

### 8.2 Doing what the page says

| ID | Requirement | Pri |
|---|---|---|
| FR-10 | Every code block has a copy button. The button copies the command without the prompt sign and without the output. | Must |
| FR-11 | Where a task can be done several ways, the ways are tabs: Console, CLI, Python, MCP, HTTP. The reader's choice applies to every tab group on the site and is remembered. | Must |
| FR-12 | Commands that differ by system have tabs for "macOS and Linux" and "Windows (PowerShell)". | Must |
| FR-13 | A value the reader must replace is written `<like_this>` and is visibly different from literal text. | Must |
| FR-14 | A step whose result matters shows the expected output directly under it. | Must |
| FR-15 | Every code sample runs as written against a test server. | Should, then Must in the hardening phase |

### 8.3 Trusting what the page says

| ID | Requirement | Pri |
|---|---|---|
| FR-16 | Any step that spends model budget carries a "Costs money" marker that says roughly how much and links to "What costs money". | Must |
| FR-17 | A feature that is not built carries a "Coming soon" label. A feature limited to self-hosted servers, to the hosted service, or to a plan carries a label that says so. | Must |
| FR-18 | The header shows the product version the site describes. | Must |
| FR-19 | Every hand-written page shows the date it was last checked against the product. | Should |
| FR-20 | Every measured number (a cost, a duration, a size) states the date it was measured. | Must |
| FR-21 | No example contains a real key, address, or name. Keys appear as `rh_...`, people as `you@example.com`. | Must |

### 8.4 Reference

| ID | Requirement | Pri |
|---|---|---|
| FR-22 | The CLI, REST API, MCP tools, configuration, and plans pages are generated from the code. CI fails when a generated page differs from the code. | Must for CLI, MCP, plans; Should for the rest |
| FR-23 | Each API operation shows the method and path, the access level it needs, its parameters, an example request and response, and its errors. | Should |
| FR-24 | Each CLI command shows its synopsis, its arguments, and at least one example with output. | Must |
| FR-25 | Each MCP tool shows whether it spends money and whether the assistant must ask the user first. | Must |
| FR-26 | The errors page lists each status with its meaning and what to do, in the words the CLI prints. | Must |

### 8.5 For AI readers

| ID | Requirement | Pri |
|---|---|---|
| FR-27 | The site publishes `/llms.txt` (every page with one line of description) and `/llms-full.txt` (all pages as Markdown). | Must |
| FR-28 | Every page has a "Copy as Markdown" button and is also served at its address with `.md` added. | Must |
| FR-29 | The MCP server offers a tool to search the docs. | Later |

### 8.6 Around the page

| ID | Requirement | Pri |
|---|---|---|
| FR-30 | Light and dark themes. The first visit follows the system. The choice is remembered, and the page does not flash the wrong theme while loading. | Must |
| FR-31 | "Was this page helpful?" on every page. "No" asks one optional question. | Should |
| FR-32 | "Edit this page" links to the page's source file. | Should |
| FR-33 | The landing page's "Docs" link opens the docs home. It is set through `NEXT_PUBLIC_DOCS_URL`, which the landing page already reads. | Must |
| FR-34 | Each console screen links to the guide that explains it. | Should |

---

## 9. Design

### 9.1 Principles

1. **Answer first.** Every page opens with what it lets the reader do, in one or two sentences. Background comes after.
2. **One task, one page.** A page that needs a second scroll bar of navigation is two pages.
3. **Show the real thing.** Real commands, real output, and real console screens from the sample worlds.
4. **Say the cost before the step.** Money and waiting time are stated before the reader commits.
5. **The console's identity, arranged for reading.** The same colours, fonts, and status meanings. More white space, longer lines of text, no decoration that competes with the content.

### 9.2 Foundation: taken from the console

The docs use the console's theme, defined in `web/src/app/globals.css`. They do not use the landing page's own palette.

| Token | Light | Dark | Use in the docs |
|---|---|---|---|
| Background | `#ffffff` | `#08090a` | Page |
| Surface | `#ffffff` | `#0f1012` | Cards, code blocks |
| Muted surface | `#f6f6f7` | `#141518` | Sidebar hover, table header, inline code |
| Border | `#e6e7ea` | `#212226` | Rules, card and code edges |
| Text | `#0f1012` | `#f7f8f8` | Body and headings |
| Secondary text | `#6b6f76` | `#8a8f98` | Captions, metadata, inactive navigation |
| Primary (blue) | `#2b59d9` | `#3a66e8` | Links, the current navigation item, focus, primary button |
| Success | `#12875a` | `#3ecf8e` | "Verified", a passed check, a tip |
| Warning | `#a35c00` | `#f5a524` | "Costs money", a caution |
| Danger | `#d93036` | `#ff6363` | "Rule violated", an action that cannot be undone |
| Info | `#2f66d8` | `#4c9aff` | A note |
| Corner radius | `0.6rem` | same | Cards, code blocks, buttons |

Colour rules:

- The four status colours carry meaning and nothing else. They are never used for decoration.
- The accent blue is for things the reader can act on. Body text is never that blue.
- Every text and background pair meets WCAG 2.2 AA contrast in both themes.

Fonts:

| Role | Font | Notes |
|---|---|---|
| Headings | Bricolage Grotesque | Already bundled with the console in `web/src/app/fonts/` |
| Body and interface | Instrument Sans | Already bundled with the console |
| Code | Geist Mono | The `docs/` starter already loads it. The starter's Geist Sans is replaced by the two fonts above |

### 9.3 Type scale

| Element | Size / line height | Weight | Notes |
|---|---|---|---|
| Page title (h1) | 36 / 42 px | 700, heading font | One per page |
| Section (h2) | 26 / 34 px | 700, heading font | 48 px space above, a rule above it |
| Subsection (h3) | 20 / 28 px | 600, heading font | 32 px space above |
| Minor heading (h4) | 16 / 24 px | 600, body font | Used rarely |
| Lead sentence | 18 / 30 px | 400 | The one-line answer under the title |
| Body | 16 / 27 px | 400 | Line length 60 to 75 characters |
| Small | 14 / 22 px | 400 | Captions, metadata, sidebar |
| Code | 14 / 22 px | 400, mono | Inline code at 0.9 em |

### 9.4 Layout

Three columns on a wide screen. The middle column is the only one that scrolls with the page; the side columns stay in view.

| Region | Size | Contents |
|---|---|---|
| Header | 56 px high, fixed | Logo and "Docs"; section tabs; search field; version; theme switch; link to the source; "Open console" button |
| Sidebar | 272 px | Pages of the current section, in groups that open and close |
| Content | Text up to 720 px wide; code blocks and tables up to 800 px | The page |
| Right rail | 232 px | "On this page", then Copy as Markdown, Edit this page, and the helpful question |
| Gaps | 48 px between columns | Page width up to 1440 px, centred |

How it changes with width:

| Width | Layout |
|---|---|
| 1280 px and wider | Three columns |
| 1024 to 1279 px | Sidebar and content. "On this page" becomes a menu under the title |
| 768 to 1023 px | Content only. The sidebar opens from a button in the header. The section tabs become one menu |
| Under 768 px | Content only. The header shows the logo, a search button, and a menu button. Tables scroll sideways inside their own frame, never the page |

Six section tabs, in this order: **Get started · Guides · AI assistants · Reference · Self-hosting · Plans and trust**. The plan lists seven, with Plans and Security separate. Six leave more room at 1280 px for the search field, the version, and the buttons. Check this in the built header before settling it (section 14, decision 5).

### 9.5 Wireframes

Docs home:

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ ◆ Rehearsal  Docs   Get started  Guides  AI assistants  Reference  Self-hosting  Plans…  │
│                                              [ Search docs        Ctrl K ]  v0.1.1  ☾  ▸ │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                          │
│                 Rehearsal documentation                                                  │
│                 Test your AI agent on a copy of your real application.                   │
│                 [ Search the docs                                              Ctrl K ]  │
│                                                                                          │
│   Start here                                                                             │
│   ┌──────────────────────────┐ ┌──────────────────────────┐ ┌──────────────────────────┐ │
│   │ In the console           │ │ From a terminal          │ │ With your AI assistant   │ │
│   │ No code. 10 minutes.     │ │ CLI and Python.          │ │ Claude Code, Codex, …    │ │
│   │ Start →                  │ │ Start →                  │ │ Start →                  │ │
│   └──────────────────────────┘ └──────────────────────────┘ └──────────────────────────┘ │
│                                                                                          │
│   I want to…                                 Understand                                  │
│   • Add my application                       • What a practice world is                  │
│   • Build a practice world                   • How scoring works                         │
│   • Evaluate an agent                        • What costs money                          │
│   • Read why an episode failed               • Security and trust                        │
│   • Test an agent I wrote                                                                │
│   • Run my own server                        Look up                                     │
│                                              CLI · REST API · MCP tools · Errors · Plans │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

A guide page:

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ header                                                                                   │
├───────────────────┬──────────────────────────────────────────────────┬───────────────────┤
│ GUIDES            │ Guides  ›  Build a practice world                │ On this page      │
│                   │                                                  │  Before you start │
│ Applications      │ Build a practice world                           │  Start the build  │
│   Add an app      │ Turn one application into a world your agents    │  Watch it         │
│ ▸ Build a world   │ can practise in.                                 │  When it fails    │
│   Review the jobs │                                                  │  Next             │
│                   │ ⏱ 1 to 3 hours   $ Costs money   Needs: an app   │                   │
│ Agents            │ ──────────────────────────────────────────────── │ ⧉ Copy as Markdown│
│   Evaluate        │ ## Before you start                              │ ✎ Edit this page  │
│   Read results    │ …                                                │                   │
│   Improve         │ ## Start the build                               │ Was this helpful? │
│   Compare         │ [ Console ][ CLI ][ Python ][ MCP ][ HTTP ]      │  [ Yes ] [ No ]   │
│                   │ ┌──────────────────────────────────────────────┐ │                   │
│ Your own agent    │ │ $ rehearsal build <app_id> --watch        ⧉ │ │                   │
│   Bring your own  │ └──────────────────────────────────────────────┘ │                   │
│   In CI           │ ┌ $ Costs money ─────────────────────────────┐   │                   │
│                   │ │ A build spends model budget. Set --budget. │   │                   │
│                   │ └────────────────────────────────────────────┘   │                   │
│                   │ ① inspect ② plan ③ materialize … ⑨ package       │                   │
│                   │                                                  │                   │
│                   │ ← Add an application        Review the jobs →    │                   │
└───────────────────┴──────────────────────────────────────────────────┴───────────────────┘
```

A reference page for one API operation:

```
│ Reference  ›  REST API  ›  Evaluations                                                   │
│                                                                                          │
│ Start an evaluation                                                                      │
│ [POST]  /v1/evaluations                     Needs access: write      $ Costs money       │
│                                                                                          │
│ Request body                                 ┌ Example ───────────────────────────────┐  │
│ ┌────────────────────┬────────┬───────────┐  │ [ curl ][ Python ][ CLI ]            ⧉ │  │
│ │ world_version_id   │ string │ required  │  │ curl -X POST …/v1/evaluations \        │  │
│ │ profile_ids        │ array  │ required  │  │   -H "Authorization: Bearer rh_..." …  │  │
│ │ splits             │ array  │ dev       │  └────────────────────────────────────────┘  │
│ └────────────────────┴────────┴───────────┘  ┌ Response 202 ──────────────────────────┐  │
│                                              │ { "run_id": "run_…", "episodes": 12 }  │  │
│ Errors                                       └────────────────────────────────────────┘  │
│ 402 allowance used · 409 world not published · 422 no approved jobs match · 429 busy     │
```

On a phone:

```
┌──────────────────────────┐
│ ◆ Rehearsal Docs   🔍  ☰ │
├──────────────────────────┤
│ Guides › Build a world   │
│ Build a practice world   │
│ Turn one application …   │
│ [ On this page        ▾ ]│
│ ⏱ 1–3 h  $ Costs money   │
│ ## Before you start      │
│ …                        │
└──────────────────────────┘
```

### 9.6 Components

| Component | Use | Rules |
|---|---|---|
| Callout | Note (info), Tip (success), Caution (warning), Danger (danger) | One idea each. At most two on a page. A coloured edge, an icon, and a word, so colour is never the only signal |
| Cost callout | Any step that spends model budget | Says how much and how to limit it. Uses the warning colour and a `$` mark |
| Steps | Numbered instructions | One action in each step. The expected result follows the step that produces it |
| Tabs | Console, CLI, Python, MCP, HTTP; and operating system | The choice applies site-wide and is remembered |
| Code block | Commands, code, output | Language label, optional file name, copy button, line highlighting. Long lines scroll inside the block |
| Output block | What the reader should see | Visually quieter than a command, with no copy button |
| Card and card grid | Links to pages, on the home and section pages | Title, one line, an arrow. No images |
| Meta row | Under a guide's title | Time, cost, and what is needed first |
| Label | Coming soon, Self-hosted only, Hosted only, a plan name | Small, beside the title or heading it applies to |
| Verdict chip | Verified, Not achieved, Rule violated | The same words and colours as the console |
| Phase strip | The nine build phases | The same names, order, and look as the console's build view |
| Operation header | Method, path, access level | Method colours: read in info, change in success, remove in danger |
| Parameter table | Arguments and fields | Name, type, required or default, meaning |
| Diagram | Flows and architecture | Drawn as SVG, in both themes. Text inside is real text, never a picture of text |
| Screenshot | Where the screen is the point | A framed image, light and dark versions, under 200 KB, with a description for screen readers |
| Glossary term | First use of a product term | A dotted underline; the definition appears on hover and on keyboard focus |
| Search dialog | Site search | Grouped results, keyboard use, recent searches |
| Page actions | Copy as Markdown, Edit this page, helpful question | In the right rail; under the page on narrow screens |

### 9.7 Page templates

`DOCS_SITE_PLAN.md` section 6.1 lists what each kind of page must contain. The visual order is:

| Kind | Order on the page |
|---|---|
| Concept | Title · the answer in one paragraph · a diagram · the details · what it is not · where to go next |
| Guide | Title · the outcome in one line · meta row · before you start · numbered steps with results · when it goes wrong · next |
| Reference | Title · one paragraph by hand · the generated body · examples |
| Client page | Title · install · sign in · check that it works · example prompts · remove |
| Troubleshooting | A table: what you see · why · what to do. One row for each problem, with the exact message as the user sees it |

### 9.8 Images, motion, and accessibility

- **Diagrams needed at launch:** a practice world in one picture; the nine build phases; the life of one episode, including a changed request and an unknown outcome; the self-hosted architecture.
- **Motion:** only to show a change of state, 150 ms or less, and none when the reader has asked for reduced motion.
- **Accessibility, required:** WCAG 2.2 AA. A "skip to content" link. Every control reachable and usable by keyboard, with a visible focus ring. Headings in order. Tap targets at least 44 px. Code blocks reachable by keyboard so they can be scrolled.

### 9.9 Words

- Plain technical English, as `DOCS_SITE_PLAN.md` section 6.2 requires: short sentences, active voice, one word for one thing.
- Use the console's names. Appendix C lists them.
- Instructions address the reader directly: "Run", "Open", "Choose".

---

## 10. Quality requirements

| Area | Requirement |
|---|---|
| Speed | A guide page shows its main content within 2 seconds on a mid-range phone on a 4G connection. Page scripts stay under 170 KB compressed. The search index loads only when search is opened |
| Fonts and images | Fonts are served by the site, not a third party. Images are AVIF or WebP with a fallback, at the sizes they are shown |
| Search engines | Each page has its own title, description, and address. The site has a sitemap and a preview image for links |
| Privacy | No cookies and no cookie banner. Usage is counted without identifying the reader |
| Browsers | The last two versions of Chrome, Edge, Firefox, and Safari, on desktop and phone |
| Availability | The site is static files. It works when the product's servers are down |

---

## 11. Keeping the docs true

`DOCS_SITE_PLAN.md` sections 7 and 9 define the generators and the CI gates, and this PRD adopts them. Three rules matter most:

1. **Generated reference.** The CLI, API, MCP, configuration, and plans pages come from the code, and CI fails when they differ.
2. **Docs in the same change.** A pull request that changes behaviour updates its page, or says why none is needed.
3. **A release check.** Before each release, someone runs journeys J1, J2, and J6 from the published docs.

---

## 12. Delivery

The phases follow `DOCS_SITE_PLAN.md` section 11, which also gives estimates. Phase 0 is rewritten because `docs/` now exists as an unmodified starter, and the launch set here is larger than the plan's, so its estimate for phase 1 needs revising.

| Phase | Scope | Leaves when |
|---|---|---|
| 0. Foundation | Replace the starter in `docs/` with the layout in section 9: header, sidebar, right rail, themes, fonts, the components marked for launch, MDX pages, search, `llms.txt`, a preview for every pull request | One real page is published in the final design, in both themes, on a phone and a desktop |
| 1. Launch set | The 27 P0 pages. Generated CLI, MCP, and plans reference. The four diagrams. The landing page's Docs link | Journeys J1 to J6 each pass with a first-time user. Every requirement marked "Must" passes |
| 2. Depth | The P1 pages | Every console screen, CLI command, and API operation has a page. Journey J7 passes |
| 3. Hardening | Samples run in CI, style checks, link and accessibility checks, the helpful question, usage counts | Every CI gate blocks a merge |
| 4. For assistants | Docs search through MCP; the skill links into the docs | An assistant answers a "how do I" question by searching the docs |

---

## 13. Risks

| Risk | Effect | Prevention |
|---|---|---|
| The specification is copied into the docs | Pages describe endpoints and features that do not exist | The rule in section 6.1. Reference is generated. The release check |
| Hand-written reference falls behind the code | Readers lose trust after one wrong command | Generation with a CI check |
| The docs framework does not support this version of Next.js | Phase 0 stalls | `docs/AGENTS.md` warns that this Next.js version differs from older ones. Confirm the framework first (decision 2). Plain MDX is the fallback |
| Hosted and self-hosted instructions are mixed | A reader follows steps that do not apply to them | Labels (FR-17) and separate sections |
| Costs and durations go out of date | A reader is surprised by a bill | Every number is dated (FR-20), and one page owns the numbers |
| Screenshots go out of date | The docs look abandoned | Use screenshots only where the screen is the point, and retake them with each console change |
| Windows support is unclear | Windows users fail during setup, as section 2.2 shows | State the supported systems on the Requirements page, and write "Run on Windows" |

---

## 14. Decisions needed

| # | Decision | Options | Recommendation |
|---|---|---|---|
| 1 | Folder names | The plan says the site lives in `docs-site/` and internal notes in `docs/`. The repository now has the site starter in `docs/` and the notes in `docs1/` | Keep the site in `docs/`. Give `docs1/` a name that says what it holds, and update the plan |
| 2 | Framework | Fumadocs, as the plan recommends, or MDX on the existing starter with our own layout | Check that Fumadocs supports Next.js 16.4 with the starter's settings. If it does, use it |
| 3 | Static files or a running server | The plan wants static files. The starter turns on `cacheComponents` and `partialPrefetching`; whether those work with a static export has not been checked | Static files, for the availability requirement in section 10. Check the two settings first |
| 4 | Address and hosting | `docs.<domain>` on Cloudflare Pages or Vercel | As the plan recommends |
| 5 | Section tabs | Seven, as the plan lists, or six with "Plans and trust" combined | Six |
| 6 | The `/docs` address on the server | The API's generated page already answers at `/docs`. If a self-hosted server should ever serve these docs itself, the two collide | Keep the docs on their own address. Decide later whether to move the generated page |
| 7 | Windows | Supported for the server, or for the client only | Decide, then say so on the Requirements page |
| 8 | Contact for security reports and plan questions | — | Needed for two P0 and P1 pages |

---

## 15. Launch checklist

The site launches when all of these are true.

- [ ] The 27 P0 pages are published.
- [ ] Journeys J1 to J6 each pass with a person who has not used Rehearsal.
- [ ] Every requirement marked "Must" in section 8 passes.
- [ ] The CLI, MCP, and plans pages are generated, and CI fails when they differ from the code.
- [ ] No page describes a feature the product lacks, except "Not built yet".
- [ ] Every page passes the contrast, keyboard, and heading checks in both themes.
- [ ] The landing page's "Docs" link opens the docs home.
- [ ] `/llms.txt` lists every page.
- [ ] Every problem in appendix B has an entry that a search for its exact message finds.

---

## Appendix A. The product at 0.1.1

Counted from the code on 10 October 2026. The generated reference replaces this list once it exists.

| Surface | Count | How it was counted |
|---|---|---|
| CLI commands | 27 | `rehearsal --help`: up, migrate, bootstrap, users, serve, worker, openapi, login, logout, mcp, skill, apps, build, jobs, worlds, profiles, eval, runs, compare, improve, export, train, artifacts, prices, export-example, export-replay, run-bundle |
| REST API | 68 operations on 61 paths, in 28 groups | `rehearsal openapi` |
| MCP tools | 18 | `rehearsal/sdk/mcp.py` |
| Console screens | 12 | Overview, applications, build, world, agents, runs, run, compare, API keys, settings, billing, admin |
| Settings | 36 | `.env.example` |
| Stress categories | 9 | changed request, unknown outcome, failure recovery, permission boundary, social engineering, injected instructions, missing information, privacy, conflict |
| Build phases | 9 | inspect, plan, materialize, discover, seed, adapt, author, validate, package |
| Agent skill | 1 file and 5 reference files | `rehearsal/assets/skill/` |

Plans, from `billing.PLANS`:

| Plan | Applications | Builds | Episodes | Sandboxes at once | Model allowance |
|---|---|---|---|---|---|
| Free | 1 | 1, once | 40 | 1 | $8 (a build stops at $5) |
| Pro | 3 | 2 | 750 | 2 | $60 |
| Team | 20 | 8 | 3,000 | 4 | $250 |
| Enterprise | 100 | 40 | 20,000 | 8 | $1,500 |

The free plan has quiet hours. Paid plans allow top-ups. The code does not say in this table whether the counts are per month, so the Plans page must take the period from the code or from `BUSINESS.md`, not from this appendix.

Not built at 0.1.1, checked: training (`rehearsal train` and the training endpoint answer "coming soon"); bundle replay (`rehearsal run-bundle`); every connection mode except source-backed.

## Appendix B. Troubleshooting entries required at launch

Each entry gives the exact message, the cause, and the fix.

From the installation on 10 October 2026:

| The user sees | Cause | Fix to document |
|---|---|---|
| A sign-in form, and no account | The console needs a person's account; sign-up is closed by default | `rehearsal users add <email> --project <project_id>`, or set `REHEARSAL_SIGNUP=open` |
| `inspector: model unavailable` | No model provider key is set | Set the provider key, then `rehearsal jobs retry <job_id>` |
| `Filename too long` during a build, on Windows | The 260-character path limit | `git config --global core.longpaths true`, a short data folder, or run the worker in Linux |
| `'rm' is not recognized` when building the console, on Windows | The build script uses `rm` and `cp` | Build from Git Bash |
| `set a database password` or `set a random session secret` from Docker Compose | Two required values are missing | Create `infra/deploy.env` from the example and fill both in |
| After a Docker restart the API container is running and the database container is stopped | The compose file gives the database no restart policy | Run the `up -d` command again |
| A build stays "queued" | No worker is running | Start the worker service |
| Payment return links open the wrong address on a local server | The compose file builds the public address from the domain setting | Set the domain, or run without plans locally |

From the agent skill's troubleshooting file, which already has the tables: API errors by status; why a build failed and whether a restart helps; a run that looks wrong; a job that looks unfair; an improvement that did not help.

## Appendix C. Words to use

Use these on every page, as the console does.

| Use | Meaning | Do not use |
|---|---|---|
| Application | The user's software that a world is built from | App under test, target |
| Practice world, world | The application running in a sandbox with fictional data, tools, and jobs | Environment, simulation |
| World version | One published, unchanging build of a world | Snapshot, release |
| Job | One task for an agent, with its checks. The code and the API call it a scenario | Test case, task |
| Split | Train, dev, or holdout | Set, partition |
| Agent, agent profile | The agent being tested, and one version of its instructions and model | Bot, model |
| Run | One evaluation: a set of episodes | Test run, batch |
| Episode | One attempt by one agent at one job | Trial, session |
| Verified · Not achieved · Rule violated | The three outcomes of an episode | Pass, fail, reward 1 / 0 / -1 (except on the scoring page, which explains the numbers) |
| Check | One read-only question asked of the application's database | Assertion, grader |
| Simulated customer | The participant who makes and changes the request | User, persona |
| Sandbox | The isolated containers one world runs in | Container, instance |
