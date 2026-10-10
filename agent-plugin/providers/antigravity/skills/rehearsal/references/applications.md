# Applications and world builds

## What makes a good application

- **Open source**, in a public git repository, with a pinned commit (a full SHA, not a branch).
- **Runs in containers**, with images you can pin by digest (`image:tag@sha256:...`). List every service: the app, its database, its worker, its cache.
- **Has an HTTP API** (REST or GraphQL) that staff use. A published API description (OpenAPI, GraphQL schema) helps a lot.
- **Has a database Rehearsal can read** (PostgreSQL, MySQL/MariaDB or SQLite). Checks run there.
- **Works without outside services**: email, payment and webhooks are emulated or blocked.
- Has roles (administrator, agent, customer) and staff workflows where mistakes matter.

Examples that work: Gitea, Mattermost, WordPress, Chatwoot.

## Adding one

```text
add_application(
  name="mattermost",
  repository_url="https://github.com/mattermost/mattermost",
  commit="<full sha>",
  images={"mattermost": "mattermost/mattermost-team-edition:10.5@sha256:...", "postgres": "postgres:16@sha256:..."},
  policies="Never post a customer's account number in a public channel. Only administrators create users."
)
```

Policies are optional. They turn into hard rules in the jobs. Write them as you would tell a new employee.

Never put real customer data, real credentials or production URLs into an application. Worlds use fictional data only.

## What a build does

| Step | What happens | Typical time |
|---|---|---|
| inspect | Reads the repository: services, configuration, roles, workflows | 2-5 min |
| plan | Writes how to run the app in the sandbox | 3-10 min |
| materialize | Starts the app, repairs the configuration until it is healthy | 1-25 min |
| discover | Finds the API description | under 1 min |
| seed | Creates fictional data and one account with a lasting API credential per role | 7-80 min |
| adapt | Turns API operations into agent tools, and tests each one live | 10-70 min |
| author | Plans the jobs, then writes them in parallel (customer, revisions, faults, checks, a reference solution, wrong solutions) | 5-20 min |
| validate | For each job: the checks fail when nothing is done; the reference passes; every wrong solution fails; the replay is the same; a live agent can pass or fails for its own reasons. Unfair jobs are repaired or withheld | 10-60 min |
| package | Snapshots the world and publishes the version | under 5 min |

A build costs about $3-8 in model calls. It stops itself at its budget. A step that keeps hitting the same problem stops early, so a failed build costs less than a full one.

## After the build

- `list_scenarios` shows the jobs and splits. A world with 6-8 approved jobs over train, dev and holdout is normal. Fewer is fine when some jobs were withheld as unfair.
- The world version is pinned: content hash, images and data. Results on the same version stay comparable for months.
- When the application changes (new release), build a new version. Old results stay attached to the old version.

## Removing an application

Done in the console (Applications, bin icon). Running builds stop. Finished runs stay in the history. The name becomes free again.
