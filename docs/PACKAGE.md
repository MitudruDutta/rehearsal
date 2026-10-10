# rehearsal-kit

Rehearse AI agents on a sandboxed copy of your own application before they reach production.

Rehearsal starts your real application from its published container images in an isolated network with fictional data, writes jobs for your agent to do, and decides each outcome by reading the application's own database. It reports what agents get wrong in practice: duplicate side effects after a timeout, acting on a request the customer already changed, claiming "done" when the records disagree.

## Install

The client (Python SDK and `rehearsal` CLI) talks to a Rehearsal server:

```bash
pip install rehearsal-kit
```

To run the server, workers, and sandboxes yourself:

```bash
pip install "rehearsal-kit[server]"          # add [telemetry] for Neatlogs tracing (Python 3.11–3.13)
```

Python 3.11 or newer. Running a server needs Linux with Docker; the client runs anywhere.

## Use a Rehearsal server

Create a project and an API key in the console, then:

```bash
export REHEARSAL_URL=https://your-rehearsal-server
export REHEARSAL_API_KEY=rh_...

rehearsal apps add my-app --git https://github.com/you/app --commit <sha> \
  --image web=registry.example.com/app@sha256:<digest>
rehearsal build <app_id> --watch            # compile a practice world
rehearsal profiles create support-agent --prompt-file prompt.md --model nebius:deepseek-ai/DeepSeek-V4.1-Flash
rehearsal eval <world_version_id> --profile <profile_id> --watch
```

From Python:

```python
from rehearsal.sdk import Rehearsal

rh = Rehearsal()  # reads REHEARSAL_URL and REHEARSAL_API_KEY
app = rh.applications.create("my-app", {"kind": "git", "url": "https://github.com/you/app", "commit": "<sha>"},
                             images={"web": "registry.example.com/app@sha256:<digest>"})
build = rh.worlds.build(app["id"])
rh.jobs.wait(build["job_id"])
```

Bring your own agent, in any language, through the episode API: read `rh.external.observation(episode_id)` and send tool calls with `rh.external.act(...)`.

## Run your own server

```bash
rehearsal up          # local PostgreSQL in Docker, then migrations
rehearsal bootstrap   # organisation, project, and the first admin key
rehearsal serve       # API and console on http://127.0.0.1:7800
rehearsal worker      # builds and evaluations; needs Docker access
```

Configure model providers with environment variables (`REHEARSAL_MODEL_COMPILER`, `REHEARSAL_MODEL_AGENT`, and the provider keys they name). The worker executes application images and controls Docker, so run it on a dedicated machine.

## Status

Alpha. World compilation, evaluation, comparison, and improvement work end to end; training a model with reinforcement learning is coming soon, and standalone bundle replay is not part of this release.
