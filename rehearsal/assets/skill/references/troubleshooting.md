# Troubleshooting

First rule: **a restart repeats the same work. It helps only when the cause has gone away.** If the same step fails twice for the same reason, stop restarting and tell the user.

## API errors

| Code | Meaning | Do this |
|---|---|---|
| 401 | Key missing, wrong or revoked | Check that `REHEARSAL_API_KEY` is set. Ask the user for a new key from the API keys page. Never print the key |
| 403 | The key's access does not allow this (for example a read-only key starting a build) | Ask the user for a key with "Build and evaluate" access |
| 404 | Wrong id, or the item belongs to another workspace, or the application was removed | List again (`list_worlds`, `list_agents`) and use an id from the list |
| 402 | Monthly model allowance used up | Do not retry. `workspace_status` shows the renewal date. The user can stop a running job to free its unspent budget |
| 409 | Not possible in the current state: world not published, job already finished, wrong turn for a bring-your-own action | Read the message. Check the state, then do the right next step |
| 422 | Bad arguments, or no approved jobs match the chosen splits | Check `list_scenarios` and the arguments |
| 429 | Too many jobs in progress for this workspace | Wait for one to finish, or ask the user to stop one |

## A world build failed

`job_status(job_id)` gives `error` and `completed_steps`. The first step that is not completed failed.

| Error says | Cause | Restart helps? | Do this |
|---|---|---|---|
| worker stopped, lease lost, sandbox removed | The machine running it stopped | Yes | `control_job(job_id, "retry")` |
| rate limit, model unavailable | Model provider busy | Yes, after a few minutes | Wait 5 minutes, then retry |
| billing, spend limit | Provider account problem on the server | No | Tell the user; the server operator must fix it |
| budget | The build reached its budget | No | Start a new build with a higher `budget_usd`, if the user agrees |
| "the same problem came back N times" | The compiler hit the same wall repeatedly | No | Tell the user the step and the reason. Usually the application needs a fix: images, missing setup, an unsupported login method |
| sign-in tokens stopped working, invalid token, expired, 401 | The world's saved logins expire | No | A build normally goes back to its seed step by itself. If it still failed, start a **new build** (`build_world` again) |
| could not be started, exited during startup, OOM | The app does not start in the sandbox | Once at most | Check that every image is listed and pinned, and that the app needs no outside service. Tell the user what the error names |
| no scenario passed validation | No job could be made fair and checkable | No | Tell the user. Often the tools cannot do the app's main tasks |

Never restart a build more than once without a change in between.

## A run looks wrong

| Symptom | Likely cause | Do this |
|---|---|---|
| Many episodes "not scored / setup problem" | Environment, not the agent | Read `environment_error` in `episode_details`. If the model provider was down, run again later. Do not count these against the agent |
| Run stays `running` with no progress | Workers are busy with other jobs | `job_status(job_id)` from `run_evaluation`. Tell the user it is queued |
| Bring-your-own episodes end with `external_timeout` | The user's agent did not answer within 10 minutes | Make sure the agent loop is running and calling `waiting_turns` |
| Every agent fails the same job in the same way | The job may be unfair | See below |

## Job looks unfair

A job is unfair when a careful agent cannot pass it. Look for this evidence in `episode_details`:

- **A check rejects correct work.** The agent did what the customer asked, but the check wanted one exact record. For example, a reply under an old message instead of the customer's new one.
- **A needed fact was not available.** The agent needed an id or name that no tool of its role returns and nobody stated. For example, a private channel that no listing tool shows.
- **Every action failed the same way**, for example "permission denied" or "signature has expired". That is the environment, not the agent.

If you find this:

1. Tell the user which job, and why, with the evidence.
2. Do not count it when you judge the agent.
3. Suggest `recheck_world(world_version_id)`. It tries each job with a live agent and withdraws jobs that are unfair (about $0.03 per job; ask first).

If the agent simply made a mistake (acted on the old request, gave up, repeated a write), the job is fair. Say so.

## The improvement did not help

- Compare on holdout with 2+ repeats before you decide.
- When the new version is worse, keep the old one. Profiles are versioned, nothing is lost.
- When all failures are environment errors or unfair jobs, there is nothing to learn. Do not run `improve_agent`.
