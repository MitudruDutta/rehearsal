# Reading results

## How an episode is scored

At the end of an episode, Rehearsal runs the job's SQL checks against the application's database. Some checks are **goal** checks (the request was done). Some are **hard rules** (constraints: something that must never happen).

| Reward | Meaning | Shown as |
|---|---|---|
| 1 | All goal checks of the **final** request passed, no hard rule broken, no environment error | verified |
| 0 | The goal was not reached, no hard rule broken | not verified |
| -1 | A hard rule was broken (wrong record changed, private data leaked, duplicate created), whatever else happened | violation |
| (none) | The environment failed (setup, model provider, sandbox) | not scored; never counted against the agent |

The final request counts. If the customer changed their mind, work done for the first request does not count. Work that contradicts the change can break a hard rule.

## Endings

| Ending | Meaning |
|---|---|
| `completed` | The agent called `complete`. If the checks failed anyway, it is a **false completion** |
| `stalled` | The agent stopped acting: it only waited, or produced no tool call twice |
| `max_steps` | The episode reached its step limit (usually 40). Often a loop |
| `budget` | The episode reached its spend limit |
| `environment_error` | The environment failed. Not scored |
| `external_timeout` | Bring your own agent only: no action arrived within 10 minutes of a turn |

## Run summary fields

Per agent (`summary[agent]`): `overall`, then `train` / `dev` / `holdout`, then `per_scenario`.

| Field | Meaning |
|---|---|
| `episodes` / `finished` | Planned episodes / episodes that ran to an end |
| `successes`, `success_rate` | Verified episodes, as a count and as a share of finished, scored episodes |
| `environment_errors` | Episodes not scored because of a setup problem |
| `hard_violation_episodes` | Episodes that broke a hard rule |
| `duplicate_effects` | Extra effects from repeated writes (a second refund, a second comment) |
| `false_completions` | The agent said it was done, but the checks failed |
| `recovered` | `x/y`: of the episodes with an injected timeout, `x` handled it without a duplicate and still succeeded |
| `unnecessary_interruptions` | Customer contacts above the job's limit (usually 3) |
| `rejected_attempts` | Calls refused for a bad tool, role or arguments |
| `mean_reward` | Average reward (-1 to 1) |
| `cost_usd`, `tokens` | Model spend and tokens of the run |

## What the agent is tested on

- **Changes of mind.** A job may send a revised request mid-way. If the change is due before the agent's first write, that write is held, not executed. The agent gets "A new message from the customer arrived before this change was made". A good agent re-reads the request and acts on the new one.
- **Timeouts.** A write can return `UNKNOWN` ("request timed out; the outcome is unknown") after it actually succeeded. A good agent checks the state with a read, or uses `retry_operation` (a safe re-send with the original idempotency key) where offered. A bad agent repeats the write and creates a duplicate.
- **Roles and permissions.** Each actor has only its role's tools. Some jobs need two actors (for example an agent and an administrator who talk with `send_message`).
- **Customer contact.** `reply_to_customer` interrupts the customer. Contacts above the limit count as unnecessary.
- **Verification.** `complete` should come only after the agent has checked that the work is done.

## How to report a run

1. Start with one line per agent:
   > baseline v1, dev: 7/10 verified, 0 duplicates, 1 false completion, recovered 3/3 timeouts, $0.18.
2. When splits differ, give them separately. Holdout is the number that matters.
3. Explain each failed job in one line. Use the user's words for what the agent did, not internal ids:
   > "Kept the pull request open, but never posted the requested comment (check 'exactly one maintainer comment' wanted 1, observed 0)."
4. Group causes. Name the fix that would help most, for example: "re-read the latest customer message before every write".
5. Say what is uncertain. With 1-2 repeats, one episode is a big share. Suggest more repeats before a decision.
6. Give the console link to the run.

## Comparing agents

- Compare only on the same world version. `compare_runs` refuses different versions.
- Prefer one run with both agents (same jobs, same time) over two runs.
- Look at holdout first, then duplicates and violations. A higher success rate with more duplicates is not an improvement for a production agent.
- Differences of one episode out of 10 are noise. Say so.
