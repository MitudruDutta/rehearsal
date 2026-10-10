# How Rehearsal makes money

Inputs for, and results of, the cfo.ai business plan (pricing, costs, revenue, runway). Unit costs below are **measured** on this deployment (October 2026: four published worlds, about 60 evaluation episodes). Revenue and runway figures are **assumptions** modelled in cfo.ai. The chosen pricing is Option C adjusted (see below).

## The one-line pitch

**A dress rehearsal for your AI agent:** Rehearsal builds a working copy of your application with fictional data, puts your agent through real jobs, and tells you, with evidence from the application's own database, whether the agent is ready to ship.

## The problem we sell against

Teams are putting agents inside their own products: support desks, admin consoles, commerce back offices, internal tools. The agent passes the demo and then fails in ways only the real application exposes:

- it retries a write after a timeout and creates a duplicate refund, email, or record;
- it keeps executing the customer's first request after the customer changed their mind;
- it reports "done" when the records say otherwise;
- it touches the wrong record, or one its role should not touch.

Today teams choose between testing on production (unsafe), mocks (they agree with whatever the agent does), or hand-building a staging harness per application (weeks of engineering, rarely kept up to date). Rehearsal's World Compiler builds that harness automatically and proves every test can be passed and can be failed.

## Who buys

| | |
|---|---|
| **Ideal customer** | A software company with a product that has a web API and a database, putting an LLM agent into that product in the next two quarters. 20 to 500 engineers. |
| **Economic buyer** | VP Engineering or Head of AI/Platform who must sign off that the agent is safe to launch. |
| **Daily user** | The engineers building the agent; QA and platform engineers who own staging. |
| **Trigger** | An agent launch date, an incident caused by an agent, or a customer asking "how do you know it won't do X?". |
| **Second segment** | Agent vendors (support, ops, sales agents) who must prove their agent works in each customer's application before a deal closes. For them a world per customer is a sales tool. |

## Why us, and what we are not

- **Not a general benchmark.** Benchmarks measure skill on someone else's tasks. Rehearsal measures your agent on your application, with your rules.
- **Not observability.** Tracing tools (we use neatlogs) explain failures after they happen. Rehearsal finds them before launch, and neatlogs traces of every rehearsal make them easy to diagnose. The two are complementary.
- **Not a hand-built harness.** The compiler builds, seeds, adapts, writes, and validates the world, and repairs its own failures; humans approve scenarios rather than write them.
- **Evidence over opinions.** Success is decided by read-only checks against the application's database and the emulated-dependency journal. No LLM judges the outcome.

## Product packaging

| Package | What ships | Who it is for |
|---|---|---|
| **Open-source core** | `pip install rehearsal-kit`, the CLI, the console, the runner, world bundles. Self-hosted, bring your own model key. | Individual engineers and teams evaluating; drives adoption. |
| **Team (hosted)** | We run the sandboxes and the console; shared readiness board, run history, improvement agent, exports. | Product teams without a spare runner VM. |
| **Enterprise** | Runner inside the customer's cloud account (VPC), SSO, audit export, retention controls, private held-out evaluation of third-party agents, support targets. | Regulated or large customers; agent vendors certifying per customer. |
| **World bundles** | A portable, versioned practice world (images, snapshot, tools, train scenarios). Dev and held-out scenarios ship separately to evaluators. | Sharing a world with a vendor, or reproducing a result on a clean machine. |

Distribution today: the Python package, the `rehearsal` container image (`Dockerfile`), and a single-host stack (`infra/compose.full.yaml`).

## Pricing (chosen: Option C adjusted)

The value metric is **world builds** and **episodes rehearsed**: they grow with how seriously a team tests, and they are what costs us money. Applications cost nothing until they are built, so the number of applications is a secondary limit. Customers use only a Rehearsal API key; all model calls run on Rehearsal's model account, so model cost is our cost of revenue.

**Option A (founder's proposal), with build and episode limits added so every plan stays profitable**

| Plan | Price | Applications | World builds | Episodes | Parallel sandboxes | Our cost at full use |
|---|---|---|---|---|---|---|
| Free (one time) | $0 | 1 | 1 (up to 5 jobs, stops at $5) | 100 | 1 | about $7 |
| Starter | $25 per month | 5 | 2 per month | 500 per month | 2 | about $20 |
| Team | $100 per month | 20 | 6 per month | 2,000 per month | 4 | about $70 |
| Enterprise | negotiated | custom | custom | custom | own runner (VPC) | custom |

**Option B (healthier margin)**

| Plan | Price | Applications | World builds | Episodes | Parallel sandboxes | Our cost at full use |
|---|---|---|---|---|---|---|
| Free (one time) | $0 | 1 | 1 (up to 5 jobs, stops at $5) | 100 | 1 | about $7 |
| Pro | $39 per month | 5 | 3 per month | 1,000 per month | 2 | about $35 |
| Team | $149 per month | 20 | 8 per month | 4,000 per month | 4 | about $120 |
| Enterprise | negotiated, from $3,000 per month | custom | custom | custom | own runner (VPC), SSO, own model key | custom |

**Option C adjusted (chosen 10 October 2026: most users with a healthy margin)**

| Plan | Price | Applications | World builds | Episodes | Parallel sandboxes |
|---|---|---|---|---|---|
| Free (forever) | $0 | 1 | 1 (stops at $5) | 40 per month, queued to quiet hours | 1 |
| Pro | $29 per month | 3 | 2 per month | 750 per month | 2 |
| Team | $149 per month | 20 | 8 per month | 3,000 per month | 4 |
| Enterprise | negotiated, from $3,000 per month | custom | custom | custom | own runner (VPC), SSO, own model key |

Yearly billing gives two months free. Extra use is sold as top-ups for the current month, paid up front: $15 per world build, $30 per 1,000 episodes. Prepaid top-ups replace metered overage, so no customer gets a bill they did not expect and we carry no unpaid usage. Free episodes run in quiet hours, when runner machines are idle and off-peak model prices apply. The 25% discount with the customer's own model key is planned, not built: it needs per-workspace model keys.

How the plans are enforced (`rehearsal/billing.py`, on when `REHEARSAL_PLANS=on`): every limit is checked in the API under a lock on the workspace row, so concurrent requests, also on several API replicas, cannot go over. Episodes count from the moment a run is queued; episodes of a stopped run that never started are not counted. A failed build is retried for free. Each plan also has a monthly model-spend safety net (free $8, Pro $60, Team $250) that covers re-checks and improvements. Free workspaces: one per account, one per browser, three per network address a month. Operator admins (`REHEARSAL_ADMIN_EMAILS`, Google sign-in only) can put any workspace on any plan, change single limits, and grant extra builds or episodes. Payments run through Dodo Payments; webhooks only trigger a re-read of the subscription from the Dodo API, so repeated or out-of-order events cannot leave a workspace on the wrong plan.

Options A and B were modelled first:

Overage for options A and B: $15 per extra world build, $40 per extra 1,000 episodes. Costs "at full use" assume every included build and episode is used; most customers use far less, so real margins are higher. Free-trial abuse is limited by Google sign-in, one trial per device and IP address, and optionally a card check before the free build. Every job has a hard spend cap, and each workspace has a monthly cap, so no account can spend more than its plan.

Price anchor: an engineer spending two weeks building and maintaining a test harness for one application costs roughly $8,000 to $12,000 fully loaded (assumption: $200k to $300k per year).

## Unit economics (measured)

| Unit | Model cost | Time | Evidence |
|---|---|---|---|
| World build, small app (Gitea, 5 jobs) | $1.70 (2.8M tokens) | about 1 hour | build job of world version 3 |
| World build, medium app (Mattermost 8 jobs, WordPress 14 jobs) | $3.29 and $3.46 (8.7M to 10.8M tokens) | 1.5 to 2 hours | build jobs |
| World build, large app (Chatwoot, 7 jobs) | $8.84 (22.7M tokens), plus $6.26 for a first attempt that failed | about 3 hours | build jobs |
| Failed builds before the stop-early guard | $6.98 (Vikunja), $7.38 (Saleor) | hours | build jobs; a step now stops after the same problem three times, so failures cost less |
| Episode (one agent attempt at one job) | $0.016 to $0.018 | 20 to 60 seconds | runs on Gitea (10 episodes, $0.157 to $0.166) and Mattermost (16 episodes, $0.285) |
| Evaluation run, 10 episodes | about $0.17 | 2.7 minutes with 4 parallel sandboxes (6.4 minutes before parallel runs) | Gitea run |
| Live fairness check per job, at build time | about $0.03 | about 1 minute | new; not yet measured on a full build |
| Runner VM (8 vCPU, 32 GB) | – | about $192 per month (about $0.27 per hour); holds about 2 builds and 4 sandboxes at once | DigitalOcean list price via a price tracker |

Model prices in use (Nebius Token Factory): DeepSeek V4.1 Flash $0.30 input / $1.20 output per million tokens (compiler); GLM 5.3 Flash $0.15 / $0.50 (agent and simulated customer). Ollama Cloud and the DeepSeek API sell the same model at the same price, or at half price off-peak.

Model cost is never taken from a single hard-coded price. Every call is charged from, in order: the cost the provider returned for that request; the serving provider's own published price list; or a `pricing.yaml` entry that names its source and date. The source is recorded with the cost. `rehearsal prices` (and `GET /v1/pricing`) shows the market range for the same model across every host listed on OpenRouter. Plan with three cases:

| Case | Model price used |
|---|---|
| Low | cheapest listed host (OpenRouter lists DeepSeek V4.1 Flash from $0.08 / $0.31), or off-peak first-party pricing |
| Base | the provider we actually run on (recorded per call) |
| High | most expensive listed host, or a stronger model tier |

Cost levers not yet used: prompt caching and shorter transcripts (an episode now sends about 100,000 tokens because the conversation is resent each turn; caching could roughly halve episode cost), and a cheaper model for the simulated customer.

## cfo.ai plan (built with Ari, 10 October 2026)

Ari built a 24-month model (October 2026 to September 2028) from the measured unit costs above, with six scenarios: each pricing option crossed with the conservative, base and upside customer cases. Ari checked the key figures twice: an independent script recomputed the forecast, and a spot check confirmed each case reaches its month-12 customer target.

| Base case (30 self-serve + 3 enterprise at month 12) | Option A ($25 / $100) | Option B ($39 / $149) |
|---|---|---|
| Monthly revenue, month 24 | $34.2k | $40.9k |
| Revenue over 24 months | $321k | $372k |
| Gross profit over 24 months | $209k | $218k |
| Gross margin | 65.1% | 58.5% |
| First profitable month | month 4 | month 4 |
| Lowest cash balance | $8.0k | $8.1k |

| Other cases | Option A | Option B |
|---|---|---|
| Conservative: lowest cash balance | −$8.5k | −$8.1k |
| Conservative: first profitable month | month 12 | month 12 |
| Upside: cash in month 24 | $551k | $579k |

**Ari's recommendation: Option B, with smaller episode allowances** (Pro 750 episodes, Team 3,000). Each self-serve customer brings about $64 a month after usage costs under B against $46 under A, so B stays ahead even if its higher prices lose up to about 28% of customers. B as written includes twice the episodes, and episodes drive extra runner machines (22 by month 24 against 14), which eats most of the gain; the smaller allowances add about $15.6k of gross profit over B as written and lift gross margin to about 63%.

**The finding that matters more than price:** costs are small (about $2k a month), so the first $3,000 enterprise deal makes Rehearsal profitable almost on its own. It lands in month 4 in the base case and month 12 in the conservative case; in the conservative case cash runs out under either option with a $15k buffer. Landing enterprise pilots early moves break-even; pricing barely does.

**Second round: Option C (for the most users and paying customers).** Option C makes the free plan permanent and Pro cheaper, to win more users. Ari modelled it against B with smaller allowances, in the base case, assuming 25% more paying self-serve customers than B, three times more free users, and episode cost halved from January 2027 in every scenario.

| Base case, month 24 | B, smaller allowances | C as first proposed | C adjusted (chosen) |
|---|---|---|---|
| Active users | 1,139 | 3,319 | 3,319 |
| Paying customers | 163 | 207 | 207 |
| Revenue over 24 months | $371k | $379k | $385k |
| Gross margin | 69.6% | 47.6% (below the 60% target) | 60.9% |
| Lowest cash balance | $8.1k | $4.9k | $7.3k |
| Cash in month 24 | $225k | $148k | $202k |

C as first proposed gave free users 100 episodes a month and 40% off for an own model key. About 3,100 active free users at 100 episodes cost about $5.6k a month and need 38 runner machines against 18, which pulls margin below 60%. C adjusted gives free users 40 episodes queued to quiet hours and 25% off for an own model key, and keeps margin above 60%.

**Ari's recommendation: C adjusted** for the most users with healthy profit: about three times the active users of B and 27% more paying customers, for about $23k less cash at month 24. Choose B with smaller allowances only if profit matters more than reach.

What to watch:
- In the upside case, C adjusted drops below 60% margin at about 10,000 free users; cut free episodes or ask for a card before that.
- The growth assumption is generous: 25% more paying customers from three times more free users implies about 0.8% conversion. At 2% conversion, C has about 90 paying self-serve customers by month 12 but a 51.6% margin.
- Yearly plans are modelled as monthly payments, so real cash is better than shown.
- In the conservative case every option runs $7k to $12k short before the first enterprise deal: that is a funding question, not a pricing one.

Estimates still to be corrected by the founders: pay of $700 a month each plus 10% overhead, tools $150 a month, hosting $100 a month plus $2 per paying customer, other admin $200 a month, starting cash $15,000, self-serve churn 3% a month, free-user drop-off 10% a month, and payment fees 3.5%.

## Go-to-market

1. **Design-partner pilots (months 0 to 3).** Five teams shipping an agent into their own product. Four weeks each: we compile their application, rehearse their agent, and hand over the readiness report and the world bundle. Success = the pilot team changes something about their agent or their launch because of a Rehearsal finding.
2. **Public readiness reports (continuous).** Rehearse popular open-source agents against popular open-source applications (Gitea, Mattermost, WordPress and Chatwoot today) and publish the results with the world bundles. Each report is a reproducible demo and an inbound channel.
3. **Open-source adoption.** Self-hosting is free; teams upgrade when they want hosted sandboxes, sharing, history, or VPC deployment.
4. **Integrations.** neatlogs traces of every rehearsal; verified trajectory export for teams that train their own models (training models on practice worlds with reinforcement learning is coming soon; every episode already ends with a verified reward); a CI step that rehearses the agent on every pull request that changes its prompt or tools.
5. **Agent vendors as a channel.** A vendor that rehearses its agent in each prospect's application closes faster and becomes a repeat buyer of worlds.

**Sales motion.** Bottom-up: an engineer runs the open-source CLI on their own application, shares the readiness board, and the team upgrades. Top-down for Enterprise: a pilot sponsored by the person signing off the agent launch.

## Revenue scenarios for the first 12 months (assumptions)

| Scenario | Team customers at month 12 | Enterprise customers at month 12 | Monthly recurring revenue at month 12 |
|---|---|---|---|
| Conservative | 10 | 1 | $8,000 |
| Base | 30 | 3 | $24,000 |
| Upside | 80 | 8 | $64,000 |

These were the first inputs to cfo.ai and assumed an early $499 Team plan. The cfo.ai results above replace them: with Option C adjusted, the base case reaches about 207 paying customers and $385k revenue over 24 months.

## Costs and runway inputs (assumptions)

| Item | Monthly |
|---|---|
| Founding team (2 to 3 people, modest salaries) | $15,000 to $30,000 |
| Hosted runners and database (pilot scale) | $500 to $2,000 |
| Model usage beyond what customers pay for (demos, public reports) | $200 to $1,000 |
| Tools, domains, legal | $500 |

Runway = cash ÷ (monthly costs − monthly revenue). Enter the team's actual cash and salaries into cfo.ai; the tables above are starting points, not facts.

## Risks and how we answer them

| Risk | Answer |
|---|---|
| Model providers or agent frameworks add their own testing | We test in the customer's own application with deterministic checks; a framework's test kit tests the framework's world. |
| Applications that do not run in containers | Browser-backed and sandbox-account connection modes are in the architecture; we start with containerised web apps, which covers most SaaS back ends. |
| Compiling an unseen application fails | The compiler reports exactly which capability is missing; held-out results on an application never inspected during development must still be produced and published, including failures. |
| Security review blocks adoption | Fictional data only, no production access, network-isolated sandboxes, read-only checks, and a VPC runner for Enterprise. |

## What to enter into cfo.ai

Business model: SaaS with an open-source core, usage-based overage. Pricing: Option C adjusted above (A and B were modelled for comparison). Cost of revenue: measured cost per world build ($1.70 to $8.84, base case $5) and per episode ($0.02), plus runner hours ($0.27 each). Customer acquisition: pilots and open-source conversion (assume 2% of active self-hosted teams convert per month). Headcount: founding team. Cash on hand: actual figure.
