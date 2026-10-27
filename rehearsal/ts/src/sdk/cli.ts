#!/usr/bin/env node
/**
 * The `rehearsal` command: the mirror of rehearsal/sdk/cli.py, with the same commands, arguments and messages.
 * Commands that run a Rehearsal server (serve, worker, up, migrate, bootstrap, users, openapi, prices) need the Python
 * server package, `pip install "rehearsal-kit[server]"`; this package is the client.
 */

import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, renameSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir, hostname, userInfo } from "node:os";
import { dirname, join, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

import { DEFAULT_URL, Rehearsal, RehearsalError, VERSION, configPath, env, saveLogin, savedLogin, type Json } from "./client.js";
import { assetsDir, exportExample } from "./examples.js";
import { UNFINISHED, run as runGate } from "./gate.js";

export const NOT_SIGNED_IN = `Not signed in. Run \`rehearsal login\`: it signs in to Rehearsal at ${DEFAULT_URL} through your browser ` +
  "(add `--url <address>` for a server of your own). In CI, set REHEARSAL_API_KEY.";

export const HINTS: Record<number, string> = {
  401: "Check REHEARSAL_API_KEY: the key is missing, mistyped, or revoked. Create one on the console's API keys page.",
  402: "The workspace's plan does not cover this. See the console's Billing page for what is left and how to get more.",
  403: "This API key's access does not allow that. Use a key with \"Build and evaluate\" or \"Full access\".",
  404: "Check the id: list what exists with 'rehearsal apps list', 'worlds list', 'profiles list' or 'runs show'.",
  409: "Not possible in the current state; the message above says why.",
  422: "Check the arguments.",
  429: "Too many jobs are running in this workspace. Wait for one to finish, or stop one.",
};

class Exit extends Error {
  constructor(message: string, readonly code = 1) { super(message); }
}

const fail = (message: string, code = 1): never => { throw new Exit(message, code); };
const print = (value: unknown) => console.log(JSON.stringify(value, null, 2));
const client = () => new Rehearsal();

function watchLine(ev: Json): string {
  const actor = ev.actor_id ? `[${ev.actor_id}] ` : "";
  const gv = ev.goal_version ? ` (goal v${ev.goal_version})` : "";
  return `${String(ev.created_at ?? "").slice(11, 19)} ${String(ev.type).padEnd(28)} ${actor}${ev.summary}${gv}`;
}

async function watch(stream: AsyncGenerator<Json>): Promise<void> {
  for await (const ev of stream) console.log(watchLine(ev));
}

const server = (explicit?: string | null) => (explicit || env("REHEARSAL_URL") || savedLogin().url || DEFAULT_URL).replace(/\/+$/, "");

async function signedIn(url: string, key: string): Promise<void> {
  const me = await new Rehearsal({ apiKey: key, baseUrl: url }).get("/v1/me"); // a wrong key or URL fails here with a clear message
  const path = saveLogin(url, key);
  console.log(`\n✓ Signed in to ${me.organization || "your workspace"} (project ${me.project}) at ${url}.`);
  console.log(`  Saved to ${path} (readable by you only). The CLI, the SDKs and the MCP server use it.`);
  console.log("  Next: rehearsal worlds list");
}

function hiddenInput(prompt: string): Promise<string> {
  return new Promise((resolveInput) => {
    const rl = createInterface({ input: process.stdin, output: process.stdout, terminal: true });
    (rl as any)._writeToOutput = (s: string) => { if (s.includes(prompt)) process.stdout.write(prompt); };
    rl.question(prompt, (answer) => { rl.close(); process.stdout.write("\n"); resolveInput(answer); });
  });
}

function openBrowser(url: string): boolean {
  const opener = process.platform === "darwin" ? ["open", url] : process.platform === "win32" ? ["cmd", "/c", "start", "", url] : ["xdg-open", url];
  try {
    spawn(opener[0], opener.slice(1), { detached: true, stdio: "ignore" }).unref();
    return true;
  } catch {
    return false;
  }
}

/** Browser sign-in by default: the terminal shows a code, the console approves it, the terminal receives a key.
 * --with-key pastes a key instead, for servers and CI where no browser is at hand. */
async function login(opts: { url?: string; withKey?: boolean; key?: string; noBrowser?: boolean }): Promise<void> {
  const url = server(opts.url);
  console.log(`Signing in to Rehearsal at ${url}` + (opts.url ? "" : "  (another server: rehearsal login --url <address>)"));
  if (opts.key || opts.withKey) {
    const key = (opts.key || (await hiddenInput("Paste an API key from the console's API keys page (input is hidden): "))).trim();
    if (!key.startsWith("rh_")) fail("That is not a Rehearsal API key; keys start with rh_.");
    return signedIn(url, key);
  }
  const who = `${userInfo().username}@${hostname()}`;
  let r: Response;
  try {
    r = await fetch(`${url}/v1/cli/logins`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ client: who }), signal: AbortSignal.timeout(30_000) });
  } catch (e) {
    return fail(`Cannot reach ${url} (${(e as Error).name}). Check the address, or use --url.`);
  }
  if (r.status === 404) { // a server older than browser sign-in
    console.log("This server does not offer browser sign-in yet; paste a key instead.");
    return login({ ...opts, withKey: true });
  }
  if (r.status >= 400) fail(`The server refused to start a sign-in (${r.status}): ${(await r.text()).slice(0, 200)}`);
  const start = await r.json() as Json;
  console.log("\nApprove this sign-in in your browser:");
  console.log(`  ${start.verification_url}`);
  console.log(`\nConfirmation code: ${start.user_code}  (the browser shows the same code)`);
  if (!opts.noBrowser && openBrowser(start.verification_url)) console.log("A browser window is opening. If it does not, open the link above.");
  process.stdout.write("\nWaiting for approval (Ctrl+C to cancel)");
  const deadline = Date.now() + start.expires_in * 1000;
  while (Date.now() < deadline) {
    await new Promise((res) => setTimeout(res, (start.interval ?? 2) * 1000));
    let poll: Json;
    try {
      poll = await (await fetch(`${url}/v1/cli/logins/poll`, { method: "POST", headers: { "Content-Type": "application/json" },
                                                               body: JSON.stringify({ device_code: start.device_code }), signal: AbortSignal.timeout(30_000) })).json() as Json;
    } catch {
      process.stdout.write("!"); // a network blip: keep waiting
      continue;
    }
    if (poll.status === "pending") { process.stdout.write("."); continue; }
    console.log();
    if (poll.status === "approved") return signedIn(url, poll.api_key);
    if (poll.status === "denied") fail("The sign-in was denied in the browser. Nothing was saved.");
    fail("The sign-in request expired or was already used. Run rehearsal login again.");
  }
  console.log();
  fail("No approval within 10 minutes. Run rehearsal login again.");
}

async function whoami(): Promise<void> {
  const source = env("REHEARSAL_API_KEY") ? "environment (REHEARSAL_API_KEY)" : Object.keys(savedLogin()).length ? `saved sign-in (${configPath()})` : null;
  if (!source) fail(NOT_SIGNED_IN);
  const c = client();
  const me = await c.get("/v1/me");
  console.log(`Server:     ${c.baseUrl}`);
  console.log(`Workspace:  ${me.organization} (project ${me.project})` + (me.plan ? `, ${me.plan} plan` : ""));
  console.log(`Key:        rh_${c.apiKey.split("_")[1]}_…  access: ${(me.scopes ?? []).join(", ")}`);
  console.log(`Signed in:  ${source}`);
}

// ---------------------------------------------------------------------------------------------- command table

type Opt = { type: "string" | "boolean"; multiple?: boolean; default?: string | boolean | string[]; help?: string; number?: boolean };
interface Cmd {
  summary: string;
  args?: string[]; // positional names; "name?" optional, "name+" one or more
  actions?: Record<string, { summary: string; args?: string[]; opts?: Record<string, Opt> }>;
  opts?: Record<string, Opt>;
  run: (a: Json) => Promise<number | void>;
}

const SERVER_ONLY = (name: string) => async () => fail(
  `'rehearsal ${name}' runs a Rehearsal server, which is the Python package:\n  pip install "rehearsal-kit[server]"\n  rehearsal ${name}\n` +
  "The TypeScript package is the client: it signs in to, builds on and evaluates with a running server.");

const COMING_SOON = (message: string) => async () => fail(message);

export const COMMANDS: Record<string, Cmd> = {
  up: { summary: "apply database migrations; starts a local database in Docker only when no cloud database is set", run: SERVER_ONLY("up") },
  migrate: { summary: "apply database migrations", run: SERVER_ONLY("migrate") },
  bootstrap: { summary: "create an organisation, project, and admin API key", opts: { org: { type: "string", default: "Local" }, project: { type: "string", default: "default" } }, run: SERVER_ONLY("bootstrap") },
  users: { summary: "console accounts (runs on the server)", actions: { add: { summary: "give a person access to a project's organisation", args: ["email"], opts: { name: { type: "string", default: "" }, project: { type: "string", help: "project id, as printed by bootstrap" }, role: { type: "string", default: "owner" }, "no-password": { type: "boolean", help: "the person signs in with Google only" } } } }, run: SERVER_ONLY("users") },
  serve: { summary: "run the API and console", opts: { host: { type: "string", default: "127.0.0.1" }, port: { type: "string", default: "7800" } }, run: SERVER_ONLY("serve") },
  worker: { summary: "run a job worker", opts: { kinds: { type: "string", default: "", help: "comma-separated job kinds" }, once: { type: "boolean", help: "exit when the queue is empty" } }, run: SERVER_ONLY("worker") },
  openapi: { summary: "print the OpenAPI document", run: SERVER_ONLY("openapi") },
  prices: { summary: "model prices from every source, for the configured model chains", run: SERVER_ONLY("prices") },
  login: {
    summary: "sign in: approve this terminal in your browser, or paste an API key",
    opts: { url: { type: "string", help: `Rehearsal server (default: REHEARSAL_URL, the last server you signed in to, or ${DEFAULT_URL})` },
            "with-key": { type: "boolean", help: "paste an API key instead of approving in the browser (servers, CI)" },
            key: { type: "string" }, "no-browser": { type: "boolean", help: "print the approval link instead of opening a browser" } },
    run: (a) => login({ url: a.url, withKey: a["with-key"], key: a.key, noBrowser: a["no-browser"] }),
  },
  logout: {
    summary: "forget the saved sign-in on this machine",
    run: async () => {
      if (!Object.keys(savedLogin()).length) return void console.log("Not signed in on this machine; nothing to remove.");
      rmSync(configPath(), { force: true });
      console.log("Signed out. The saved key is removed from this machine; revoke it on the console's API keys page to disable it everywhere.");
    },
  },
  whoami: { summary: "show the server, workspace and key this machine uses", run: () => whoami() },
  mcp: { summary: "run the MCP server for AI assistants (stdio; uses your rehearsal login)", run: async () => { await (await import("./mcp.js")).main(); return -1; } },
  skill: {
    summary: "install the Rehearsal skill for Claude Code and other agents", args: ["action"], opts: { dir: { type: "string", help: "skills folder (default ~/.claude/skills)" } },
    run: async (a) => {
      const skill = join(assetsDir(), "skill");
      if (a.action === "print") return void process.stdout.write(readFileSync(join(skill, "SKILL.md"), "utf8"));
      if (a.action !== "install") fail("argument action: choose from install, print", 2);
      const target = join(a.dir || join(homedir(), ".claude", "skills"), "rehearsal");
      mkdirSync(join(target, "references"), { recursive: true });
      writeFileSync(join(target, "SKILL.md"), readFileSync(join(skill, "SKILL.md")));
      for (const f of readdirSync(join(skill, "references")).filter((f) => f.endsWith(".md"))) writeFileSync(join(target, "references", f), readFileSync(join(skill, "references", f)));
      console.log(`installed ${target}`);
    },
  },
  apps: {
    summary: "add, list and upload applications",
    actions: {
      "import-catalog": { summary: "register the bundled catalog of open-source applications" },
      list: { summary: "applications in this workspace" },
      add: { summary: "add an application from a git repository or a local folder", args: ["name"],
             opts: { git: { type: "string" }, commit: { type: "string" }, path: { type: "string" }, image: { type: "string", multiple: true, default: [], help: "component=image@sha256:..." }, "policies-file": { type: "string" } } },
      upload: { summary: "upload a .tar.gz of an application's source", args: ["app_id", "archive"] },
    },
    run: async (a) => {
      const c = client();
      if (a.sub === "import-catalog") return print((await c.applications.importCatalog()).map((x) => pick(x, "id", "name", "notes")));
      if (a.sub === "list") return print((await c.applications.list()).map((x) => pick(x, "id", "name", "source", "notes")));
      if (a.sub === "add") {
        const source = a.git ? { kind: "git", url: a.git, commit: a.commit ?? null } : a.path ? { kind: "local_path", path: resolve(a.path) } : { kind: "upload" };
        const images = Object.fromEntries((a.image as string[]).map((i) => { const at = i.indexOf("="); return [i.slice(0, at), i.slice(at + 1)]; }));
        const policies = a["policies-file"] ? readFileSync(a["policies-file"], "utf8") : "";
        return print(await c.applications.create(a.name, source, images, policies));
      }
      return print(await c.applications.uploadSource(a.app_id, a.archive));
    },
  },
  build: {
    summary: "compile an application into a world", args: ["app_id"],
    opts: { model: { type: "string" }, budget: { type: "string", number: true }, scenarios: { type: "string", number: true, default: "8" }, watch: { type: "boolean" } },
    run: async (a) => {
      const c = client();
      const res = await c.worlds.build(a.app_id, { scenario_target: a.scenarios, ...(a.model ? { model: a.model } : {}), ...(a.budget !== undefined ? { budget_usd: a.budget } : {}) });
      print(res);
      if (a.watch) await watch(c.jobs.events(res.job_id));
    },
  },
  jobs: {
    summary: "follow and control builds and other long jobs",
    actions: Object.fromEntries(["show", "watch", "pause", "resume", "stop", "retry"].map((n) => [n, { summary: `${n} a job`, args: ["job_id"] }])),
    run: async (a) => {
      const c = client();
      if (a.sub === "show") return print(await c.jobs.get(a.job_id));
      if (a.sub === "watch") return watch(c.jobs.events(a.job_id));
      return print(await c.jobs.command(a.job_id, a.sub));
    },
  },
  worlds: {
    summary: "list practice worlds, their jobs, re-checks and bundles",
    actions: { list: { summary: "worlds and their versions" }, library: { summary: "ready-made worlds you can rehearse on without building one" },
               incident: { summary: "turn a production incident into a validated job in a world", args: ["wv_id"],
                           opts: { file: { type: "string", help: "the incident: what was asked, what the agent did, what should have happened" }, watch: { type: "boolean" } } },
               show: { summary: "one world version", args: ["wv_id"] },
               scenarios: { summary: "the jobs of a world version", args: ["wv_id"] }, validate: { summary: "re-check every job of a published world", args: ["wv_id"] },
               bundle: { summary: "export a portable world bundle", args: ["wv_id"], opts: { "include-images": { type: "boolean" } } } },
    run: async (a) => {
      const c = client();
      if (a.sub === "list") return print(await c.worlds.list());
      if (a.sub === "library") return print(await c.worlds.library());
      if (a.sub === "incident") {
        if (!a.file) fail("rehearsal worlds incident: the following arguments are required: --file", 2);
        const res = await c.worlds.reportIncident(a.wv_id, readFileSync(a.file, "utf8"));
        print(res);
        if (a.watch) { await watch(c.jobs.events(res.job_id)); print((await c.jobs.get(res.job_id)).result ?? {}); }
        return;
      }
      if (a.sub === "show") return print(await c.worlds.version(a.wv_id));
      if (a.sub === "scenarios") return print((await c.worlds.scenarios(a.wv_id)).map((s) => pick(s, "id", "slug", "family", "split", "status")));
      if (a.sub === "validate") return print(await c.worlds.validate(a.wv_id));
      return print(await c.worlds.bundle(a.wv_id, Boolean(a["include-images"])));
    },
  },
  profiles: {
    summary: "list and create agent profiles (agent versions)",
    actions: { list: { summary: "agent profiles and versions" },
               create: { summary: "create an agent profile", args: ["name"], opts: { "prompt-file": { type: "string" }, model: { type: "string" }, external: { type: "boolean", help: "actions come from your own agent through the API" },
                                                                                       endpoint: { type: "string", help: "test your own agent by its URL: an OpenAI-compatible endpoint that answers with tool calls" },
                                                                                       "endpoint-model": { type: "string", default: "", help: "the model name your endpoint expects, if any" },
                                                                                       "endpoint-key-env": { type: "string", help: "the environment variable holding your endpoint's API key (stored sealed on the server)" } } } },
    run: async (a) => {
      const c = client();
      if (a.sub === "list") return print((await c.profiles.list()).map((p) => pick(p, "id", "name", "version", "created_by")));
      const prompt = a["prompt-file"] ? readFileSync(a["prompt-file"], "utf8") : "";
      let endpoint: Json | undefined;
      if (a.endpoint) {
        const key = a["endpoint-key-env"] ? process.env[a["endpoint-key-env"]] ?? "" : "";
        if (a["endpoint-key-env"] && !key) fail(`${a["endpoint-key-env"]} is not set in this shell`);
        endpoint = { url: a.endpoint, model: a["endpoint-model"], ...(key ? { api_key: key } : {}) };
      }
      return print(await c.profiles.create(a.name, prompt, { ...(a.external ? { driver: "external" } : {}), ...(a.model ? { model: a.model } : {}), ...(endpoint ? { endpoint } : {}) }));
    },
  },
  eval: {
    summary: "evaluate agent profiles on a world version", args: ["wv_id"],
    opts: { profile: { type: "string", multiple: true }, split: { type: "string", multiple: true, default: [], help: "train, dev or holdout; default every split" },
            repeats: { type: "string", number: true, help: "default 2" }, budget: { type: "string", number: true }, watch: { type: "boolean" } },
    run: async (a) => {
      if (!a.profile?.length) fail("rehearsal eval: the following arguments are required: --profile", 2);
      const c = client();
      const res = await c.evaluations.create(a.wv_id, a.profile, a.split.length ? a.split : null, a.repeats ?? null, a.budget !== undefined ? { budget_usd: a.budget } : {});
      print(res);
      if (a.watch) { await watch(c.runs.events(res.run_id)); print((await c.runs.get(res.run_id)).summary); }
    },
  },
  runs: {
    summary: "follow runs and read their episodes",
    actions: { show: { summary: "status and scores of a run", args: ["run_id"] }, watch: { summary: "follow a run live", args: ["run_id"] },
               episodes: { summary: "one line per episode", args: ["run_id"] }, episode: { summary: "what happened in one episode", args: ["episode_id"] },
               failures: { summary: "why episodes failed: named causes per agent, with example episodes", args: ["run_id"] } },
    run: async (a) => {
      const c = client();
      if (a.sub === "show") return print(await c.runs.get(a.run_id));
      if (a.sub === "watch") return watch(c.runs.events(a.run_id));
      if (a.sub === "failures") return print(await c.runs.failures(a.run_id));
      if (a.sub === "episodes") return print((await c.runs.episodes(a.run_id)).map((e) => pick(e, "id", "scenario", "split", "profile", "status", "reward", "termination")));
      return print(await c.runs.episode(a.episode_id));
    },
  },
  compare: { summary: "compare agents within a run, or two runs on one world version", args: ["run_a", "run_b?"], run: async (a) => print(await client().evaluations.compare(a.run_a, a.run_b)) },
  improve: { summary: "propose a revised agent profile from train/dev failures", args: ["profile_id", "run_id"], run: async (a) => print(await client().post("/v1/improvements", { profile_id: a.profile_id, run_id: a.run_id })) },
  factory: {
    summary: "make a verified agent for a world: draft it, harden it, prove it on held-out jobs, package it", args: ["wv_id"],
    opts: { name: { type: "string", default: "", help: "the agent's name, lowercase with dashes (default: <world>-agent)" }, rounds: { type: "string", number: true, default: "3", help: "fix rounds, 1 to 5 (default 3)" },
            repeats: { type: "string", number: true, default: "1", help: "episodes per job in each rehearsal, 1 to 5 (default 1)" }, watch: { type: "boolean" } },
    run: async (a) => {
      const c = client();
      const res = await c.worlds.makeAgent(a.wv_id, { name: a.name, rounds: a.rounds, repeats: a.repeats });
      print(res);
      if (a.watch) {
        await watch(c.jobs.events(res.job_id));
        const result = (await c.jobs.get(res.job_id)).result ?? {};
        print(result);
        if (result.artifact_id) console.log(`Download the agent: rehearsal artifacts download ${result.artifact_id} agent.zip`);
      }
    },
  },
  autofix: {
    summary: "fix an agent in rounds, keep only versions that verify more, prove the best on held-out jobs", args: ["profile_id", "run_id"],
    opts: { rounds: { type: "string", number: true, default: "3", help: "1 to 5 (default 3)" }, repeats: { type: "string", number: true, default: "1", help: "episodes per job in each rehearsal, 1 to 5 (default 1)" }, watch: { type: "boolean" } },
    run: async (a) => {
      const c = client();
      const res = await c.profiles.autofix(a.profile_id, a.run_id, { rounds: a.rounds, repeats: a.repeats });
      print(res);
      if (a.watch) { await watch(c.jobs.events(res.job_id)); print((await c.jobs.get(res.job_id)).result ?? {}); }
    },
  },
  gate: {
    summary: "pass or fail an agent change in CI: rehearse it, next to a baseline, and judge the result", args: ["wv_id?"],
    opts: { profile: { type: "string", help: "the agent profile to test" },
            "prompt-file": { type: "string", help: "test a version of --name with these instructions (reused when unchanged)" },
            name: { type: "string", help: "the agent's name, with --prompt-file or --baseline-file" },
            baseline: { type: "string", help: "a profile to rehearse side by side; the change may not do worse" },
            "baseline-file": { type: "string", help: "the baseline as an instructions file, for example the one on the main branch" },
            split: { type: "string", multiple: true, default: [], help: "train, dev or holdout; default every split" },
            repeats: { type: "string", number: true, default: "1", help: "attempts at each job (default 1)" },
            "min-success": { type: "string", number: true, help: "fail below this verified success rate, 0 to 1" },
            "max-violations": { type: "string", number: true, default: "0", help: "fail above this many episodes with a rule violation (default 0)" },
            tolerance: { type: "string", number: true, default: "0", help: "how far below the baseline's success rate still passes, 0 to 1" },
            budget: { type: "string", number: true, help: "model spend in US dollars at which the run stops itself" },
            run: { type: "string", help: "judge this finished run instead of starting one" },
            timeout: { type: "string", number: true, default: "90", help: "minutes to wait for the run (default 90)" },
            report: { type: "string", help: "append the Markdown report to this file, for example $GITHUB_STEP_SUMMARY" } },
    run: async (a) => {
      try {
        return await runGate(client(), { wvId: a.wv_id, profile: a.profile, promptFile: a["prompt-file"], name: a.name, baseline: a.baseline, baselineFile: a["baseline-file"],
                                         split: a.split, repeats: a.repeats, minSuccess: a["min-success"], maxViolations: a["max-violations"], tolerance: a.tolerance,
                                         budget: a.budget, run: a.run, timeout: a.timeout, report: a.report });
      } catch (e) { // the check could not run, which is not the agent failing
        if (e instanceof RehearsalError || e instanceof TypeError) { console.error(`The gate could not run: ${e.message}`); return UNFINISHED; }
        throw e;
      }
    },
  },
  export: { summary: "export verified trajectories as a dataset", args: ["run_ids+"], opts: { split: { type: "string", multiple: true, default: [] } },
            run: async (a) => print(await client().post("/v1/dataset-exports", { run_ids: a.run_ids, splits: a.split.length ? a.split : ["train"] })) },
  artifacts: {
    summary: "list and download exported files",
    actions: { list: { summary: "exported files" }, download: { summary: "download one exported file", args: ["artifact_id", "dest"] } },
    run: async (a) => {
      const c = client();
      if (a.sub === "list") return print(await c.get("/v1/artifacts"));
      const bytes = await c.download(`/v1/artifacts/${a.artifact_id}/download`);
      const dest = resolve(a.dest);
      const tmp = `${dest}.part`;
      try { writeFileSync(tmp, bytes); renameSync(tmp, dest); } finally { if (existsSync(tmp)) unlinkSync(tmp); }
      console.log(`saved ${a.dest}`);
    },
  },
  "export-example": { summary: "write examples/<app>/ from a published world version and its runs", args: ["wv_id"], run: async (a) => print(await exportExample(client(), a.wv_id)) },
  "export-replay": {
    summary: "save a job's or run's recorded events (already redacted) as a replay file", args: ["stream", "dest"], opts: { episode: { type: "string", help: "only this episode's events (runs)" } },
    run: async (a) => {
      const c = client();
      let events: Json[] = [];
      let cursor = 0;
      for (;;) {
        const page: Json[] = await c.get(`/v1/streams/${a.stream}/events/page`, { cursor, limit: 2000 });
        if (!page.length) break;
        events = events.concat(page);
        cursor = page[page.length - 1].event_id;
      }
      events = events.filter((e) => REPLAY_TYPES.has(e.type) && (!a.episode || e.episode_id === a.episode));
      mkdirSync(dirname(resolve(a.dest)), { recursive: true });
      writeFileSync(a.dest, JSON.stringify({ stream: a.stream, events }));
      console.log(`saved ${events.length} events to ${a.dest}` + (events.length ? "" : " (a replay holds build and episode activity; this job or run has none yet)"));
    },
  },
  train: { summary: "train a model on a world with reinforcement learning", args: ["wv_id"],
           opts: { "base-model": { type: "string", default: "Qwen/Qwen3-1.7B" }, rounds: { type: "string", default: "2" }, rollouts: { type: "string", default: "4" }, "serve-url": { type: "string", default: "http://127.0.0.1:8001/v1" } },
           run: COMING_SOON("Training a model on your practice worlds (reinforcement learning) is coming soon. Every episode already ends with a verified score from the application's database; today you can export verified episodes as a dataset with `rehearsal export`, and improve an agent's instructions with `rehearsal improve`.") },
  "run-bundle": { summary: "start a world from an exported bundle on your own machine", args: ["bundle"],
                  run: COMING_SOON("Starting a world from a bundle on your own machine is coming soon. Today, evaluate the published world through the server: rehearsal eval <world_version_id> --profile <agent_id>.") },
};

const REPLAY_TYPES = new Set(["compiler.tool", "compiler.note", "compiler.submit.accepted", "compiler.submit.rejected", "compiler.phase.started", "compiler.phase.completed",
  "compiler.repair", "compiler.validation", "world.published", "episode.started", "customer.message", "agent.reply", "message.sent",
  "notification", "agent.decision", "goal.revised", "fault.injected", "permission.changed", "action.succeeded", "action.failed",
  "action.unknown", "action.rejected", "episode.claimed_complete", "episode.finished"]);

export const GROUPS: [string, string[]][] = [
  ["Start", ["login", "whoami", "logout"]],
  ["Applications and worlds", ["apps", "build", "worlds", "jobs"]],
  ["Agents and evaluations", ["profiles", "eval", "runs", "compare", "improve", "autofix", "factory", "gate"]],
  ["Data", ["export", "artifacts", "export-example", "export-replay"]],
  ["AI assistants", ["mcp", "skill"]],
  ["Run your own server", ["serve", "worker", "up", "migrate", "bootstrap", "users", "openapi", "prices"]],
  ["Coming soon", ["train", "run-bundle"]],
];

function pick(o: Json, ...keys: string[]): Json {
  return Object.fromEntries(keys.map((k) => [k, o[k] ?? null]));
}

export function helpText(): string {
  const width = Math.max(...Object.keys(COMMANDS).map((n) => n.length)) + 2;
  return "usage: rehearsal <command> [options]\n\nRehearse AI agents on a sandboxed copy of your application.\n\n" +
    GROUPS.map(([title, names]) => `${title}:\n` + names.map((n) => `  ${n.padEnd(width)}${COMMANDS[n].summary}`).join("\n")).join("\n\n") +
    "\n\nGet started: rehearsal login, then rehearsal worlds list.\nHelp for one command: rehearsal <command> --help\n";
}

function commandHelp(name: string, cmd: Cmd): string {
  const lines = [`usage: rehearsal ${name}${cmd.actions ? " <action>" : ""}${(cmd.args ?? []).map((a) => ` <${a}>`).join("")} [options]`, "",
                 cmd.summary[0].toUpperCase() + cmd.summary.slice(1) + "."];
  if (cmd.actions) lines.push("", "actions:", ...Object.entries(cmd.actions).map(([n, a]) => `  ${n.padEnd(16)}${a.summary}`));
  const opts = Object.entries(cmd.opts ?? {});
  if (opts.length) lines.push("", "options:", ...opts.map(([n, o]) => `  --${n}${o.type === "string" ? ` <${n}>` : ""}`.padEnd(28) + (o.help ?? "")));
  return lines.join("\n") + "\n";
}

function closest(word: string, choices: string[]): string | undefined {
  const dist = (a: string, b: string) => {
    const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++) d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    return d[a.length][b.length];
  };
  const best = choices.map((c) => [dist(word, c), c] as const).sort((x, y) => x[0] - y[0])[0];
  return best && best[0] <= Math.max(2, Math.floor(word.length / 3)) ? best[1] : undefined;
}

/** Parses one command line into its named arguments; numbers come back as numbers. */
export function parse(argv: string[]): { name: string; args: Json } {
  const [name, ...rest] = argv;
  const cmd = COMMANDS[name];
  if (!cmd) {
    const close = closest(name, Object.keys(COMMANDS));
    fail(`rehearsal: unknown command '${name}'.${close ? ` Did you mean '${close}'?` : ""} Run 'rehearsal --help' to see every command.`, 2);
  }
  let positionals = [...rest];
  let spec: { args?: string[]; opts?: Record<string, Opt> } = cmd;
  const out: Json = {};
  if (cmd.actions && !rest.includes("--help")) {
    const sub = positionals[0];
    if (!sub || !cmd.actions[sub]) fail(`rehearsal ${name}: choose an action: ${Object.keys(cmd.actions).join(", ")}`, 2);
    out.sub = sub;
    spec = { args: cmd.actions[sub].args, opts: { ...(cmd.opts ?? {}), ...(cmd.actions[sub].opts ?? {}) } };
    positionals = positionals.slice(1);
  }
  const options: Record<string, { type: "string" | "boolean"; multiple?: boolean }> = { help: { type: "boolean" } };
  for (const [k, o] of Object.entries(spec.opts ?? {})) options[k] = { type: o.type, ...(o.multiple ? { multiple: true } : {}) };
  let parsed;
  try {
    parsed = parseArgs({ args: positionals, options, allowPositionals: true, strict: true });
  } catch (e) {
    return fail(`rehearsal ${name}: ${(e as Error).message}`, 2);
  }
  if (parsed.values.help) throw new Exit(commandHelp(name, cmd), 0);
  for (const [k, o] of Object.entries(spec.opts ?? {})) {
    let v: any = (parsed.values as Json)[k] ?? o.default;
    if (o.number && v !== undefined) {
      const n = Number(v);
      if (Number.isNaN(n)) fail(`rehearsal ${name}: --${k} must be a number`, 2);
      v = n;
    }
    out[k] = v;
  }
  const pos = parsed.positionals;
  for (const [i, raw] of (spec.args ?? []).entries()) {
    const opt = raw.endsWith("?"), many = raw.endsWith("+"), key = raw.replace(/[?+]$/, "");
    if (many) { if (!pos.slice(i).length) fail(`rehearsal ${name}: the following arguments are required: ${key}`, 2); out[key] = pos.slice(i); break; }
    if (pos[i] === undefined && !opt) fail(`rehearsal ${name}: the following arguments are required: ${key}`, 2);
    out[key] = pos[i] ?? null;
  }
  return { name, args: out };
}

export async function main(argv = process.argv.slice(2)): Promise<number> {
  try {
    if (!argv.length || argv[0] === "--help" || argv[0] === "-h") { process.stdout.write(helpText()); return argv.length ? 0 : 2; }
    if (argv[0] === "--version") { console.log(`rehearsal-kit ${VERSION}`); return 0; }
    const { name, args } = parse(argv);
    const code = await COMMANDS[name].run(args);
    return typeof code === "number" ? code : 0;
  } catch (e) {
    if (e instanceof Exit) { (e.code === 0 ? process.stdout : process.stderr).write(e.message.endsWith("\n") ? e.message : e.message + "\n"); return e.code; }
    if (e instanceof RehearsalError) {
      const hint = HINTS[e.status] ?? (e.status >= 500 ? "The server had a problem; try again, and check the server log if it persists." : "");
      process.stderr.write(`Error (${e.status}): ${typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail)}` + (hint ? `\n${hint}` : "") + "\n");
      return 1;
    }
    if (e instanceof Error && e.message.includes("REHEARSAL_API_KEY")) { process.stderr.write(NOT_SIGNED_IN + "\n"); return 1; }
    if (e instanceof TypeError && /fetch failed/.test(e.message)) {
      process.stderr.write(`Cannot reach Rehearsal at ${server()} (${(e.cause as Error)?.name ?? "connection error"}). Check the URL (\`rehearsal login --url ...\`) and that the server is running.\n`);
      return 1;
    }
    if (e instanceof Error && e.name === "TimeoutError") { process.stderr.write("Rehearsal did not answer in time. Try again; long work runs as jobs, so check 'rehearsal jobs show JOB_ID'.\n"); return 1; }
    throw e;
  }
}

// Run when executed as the `rehearsal` command (not when imported by tests or code).
const invoked = (() => { try { return realpathSync(process.argv[1]); } catch { return ""; } })();
if (invoked === fileURLToPath(import.meta.url)) {
  main().then((code) => { if (code >= 0) process.exitCode = code; });
}
