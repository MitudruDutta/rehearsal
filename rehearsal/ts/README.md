# rehearsal-kit

Rehearse AI agents on a sandboxed copy of your own application before they reach production.

Rehearsal starts your real application from its published container images in an isolated network with fictional data, writes jobs for your agent to do, and decides each outcome by reading the application's own database. It reports what agents get wrong in practice: duplicate side effects after a timeout, acting on a request the customer already changed, claiming "done" when the records disagree.

This is the TypeScript edition of `rehearsal-kit`. It has the same SDK, `rehearsal` command and MCP server as the Python package on PyPI, with the same commands, arguments and messages.

## Install

```bash
npm install rehearsal-kit      # or: pnpm add rehearsal-kit / bun add rehearsal-kit
npx rehearsal-kit --help       # the `rehearsal` command, without installing
```

Node.js 20 or newer. The package is the client: it talks to a Rehearsal server, the hosted service at https://rehearsalkit.xyz or one of your own. Running a server is the Python package, `pip install "rehearsal-kit[server]"`.

## Use Rehearsal

Sign in to the hosted service, or to a server of your own with `--url`:

```bash
rehearsal login                               # opens the console in your browser; approve the code shown
# rehearsal login --url https://your-rehearsal-server

rehearsal apps add my-app --git https://github.com/you/app --commit <sha> \
  --image web=registry.example.com/app@sha256:<digest>
rehearsal build <app_id> --watch            # compile a practice world
rehearsal profiles create support-agent --prompt-file prompt.md --model nebius:deepseek-ai/DeepSeek-V4.1-Flash
rehearsal eval <world_version_id> --profile <profile_id> --watch
```

The CLI, both SDKs and the MCP server share one sign-in, saved in `~/.config/rehearsal/config.json` (readable by you only). In CI, set `REHEARSAL_URL` and `REHEARSAL_API_KEY` instead.

From TypeScript:

```ts
import { Rehearsal } from "rehearsal-kit";

const rh = new Rehearsal(); // your sign-in, or REHEARSAL_URL and REHEARSAL_API_KEY (in CI)
const app = await rh.applications.create("my-app", { kind: "git", url: "https://github.com/you/app", commit: "<sha>" },
                                         { web: "registry.example.com/app@sha256:<digest>" });
const build = await rh.worlds.build(app.id);
await rh.jobs.wait(build.job_id);

for await (const event of rh.jobs.events(build.job_id)) console.log(event.type, event.summary);
```

Bring your own agent, in any language, through the episode API: read `rh.external.observation(episodeId)` and send tool calls with `rh.external.act(...)`.

## Gate agent changes in CI

`rehearsal gate` rehearses an agent change next to a baseline and exits 0 when it passes, 1 when it fails, and 2 when the run did not finish:

```bash
rehearsal gate <world_version_id> --prompt-file prompt.md --name support-agent \
  --baseline-file baseline/prompt.md --min-success 0.8 --report "$GITHUB_STEP_SUMMARY"
```

## AI assistants

`rehearsal mcp` runs the MCP server over stdio, with the same twenty tools as the Python server. In Claude Code:

```bash
claude mcp add rehearsal -- npx -y rehearsal-kit mcp
rehearsal skill install        # the Rehearsal skill, into ~/.claude/skills
```

To embed it, `import { buildServer } from "rehearsal-kit/mcp"`.

## Build from source

From `rehearsal/ts` in the repository:

```bash
pnpm install --frozen-lockfile
pnpm test        # builds, then runs the tests
npm pack --dry-run
```

The build copies the application catalog and the agent skill from the Python package, so both packages ship the same files.

## Status

Alpha. World compilation, evaluation, comparison, improvement, the Agent Factory and the CI gate work end to end; training a model with reinforcement learning is coming soon.
