import { test } from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { COMMANDS, GROUPS, parse } from "../dist/sdk/cli.js";
import { pythonSource, stub, tempDir } from "./stub.mjs";

const CLI = fileURLToPath(new URL("../dist/sdk/cli.js", import.meta.url));

/** Runs the built `rehearsal` command with a private sign-in file; resolves with its exit code and output. */
function rehearsal(args, { url, key = "rh_test_key", cwd } = {}) {
  const config = join(tempDir(), "config.json");
  const env = { ...process.env, REHEARSAL_CONFIG: config, REHEARSAL_URL: url ?? "", REHEARSAL_API_KEY: key ?? "" };
  return new Promise((resolve) => execFile(process.execPath, [CLI, ...args], { env, cwd, timeout: 20_000 },
    (err, stdout, stderr) => resolve({ code: err ? err.code : 0, stdout, stderr, config })));
}

test("every command of the Python CLI, in the same help groups", () => {
  const grouped = GROUPS.flatMap(([, names]) => names).sort();
  assert.deepEqual(grouped, Object.keys(COMMANDS).sort());
  const py = pythonSource("sdk/cli.py");
  if (!py) return;
  const names = [...py.matchAll(/\bcmd\("([\w-]+)"/g)].map((m) => m[1]).sort();
  assert.deepEqual(Object.keys(COMMANDS).sort(), names);
});

test("arguments parse like argparse: positionals, repeated flags, numbers, defaults", () => {
  assert.deepEqual(parse(["eval", "wv_1", "--profile", "a", "--profile", "b", "--split", "dev", "--repeats", "3"]).args,
                   { profile: ["a", "b"], split: ["dev"], repeats: 3, budget: undefined, watch: undefined, wv_id: "wv_1" });
  assert.equal(parse(["build", "app_1"]).args.scenarios, 8);
  assert.deepEqual(parse(["export", "run_1", "run_2"]).args.run_ids, ["run_1", "run_2"]);
  assert.equal(parse(["compare", "run_1"]).args.run_b, null);
  assert.equal(parse(["runs", "failures", "run_1"]).args.sub, "failures");
});

test("usage errors exit 2 with a suggestion", async () => {
  let r = await rehearsal(["biuld"]);
  assert.equal(r.code, 2);
  assert.match(r.stderr, /unknown command 'biuld'\. Did you mean 'build'\?/);
  r = await rehearsal(["build"]);
  assert.equal(r.code, 2);
  assert.match(r.stderr, /required: app_id/);
  r = await rehearsal(["build", "app_1", "--scenarios", "many"]);
  assert.match(r.stderr, /--scenarios must be a number/);
  r = await rehearsal(["runs"]);
  assert.match(r.stderr, /choose an action: show, watch, episodes, episode, failures/);
  r = await rehearsal([]);
  assert.equal(r.code, 2);
  assert.match(r.stdout, /Agents and evaluations:/);
});

test("server commands point to the Python server package", async () => {
  const r = await rehearsal(["worker", "--once"]);
  assert.equal(r.code, 1);
  assert.match(r.stderr, /pip install "rehearsal-kit\[server\]"/);
});

test("without a sign-in, commands say how to sign in", async () => {
  const r = await rehearsal(["worlds", "list"], { key: null, url: "http://127.0.0.1:9" });
  assert.equal(r.code, 1);
  assert.match(r.stderr, /Not signed in\. Run `rehearsal login`/);
});

test("API errors print the detail and a hint for the status", async () => {
  const s = await stub({ "GET /v1/jobs/job_x": () => [404, { detail: "job not found" }], "GET /v1/runs/run_x": () => [503, { detail: "busy" }] });
  try {
    let r = await rehearsal(["jobs", "show", "job_x"], { url: s.url });
    assert.equal(r.code, 1);
    assert.equal(r.stderr, "Error (404): job not found\nCheck the id: list what exists with 'rehearsal apps list', 'worlds list', 'profiles list' or 'runs show'.\n");
    r = await rehearsal(["runs", "show", "run_x"], { url: s.url });
    assert.match(r.stderr, /Error \(503\): busy\nThe server had a problem/);
  } finally { await s.close(); }
  const r = await rehearsal(["worlds", "list"], { url: "http://127.0.0.1:9" });
  assert.match(r.stderr, /Cannot reach Rehearsal at http:\/\/127\.0\.0\.1:9/);
});

test("client commands send the same requests as the Python CLI", async () => {
  const dir = tempDir();
  writeFileSync(join(dir, "prompt.md"), "Be careful.");
  const s = await stub({
    "GET /v1/applications": () => [{ id: "app_1", name: "shop", source: { kind: "git" }, notes: "n", extra: 1 }],
    "POST /v1/applications": (r) => ({ id: "app_2", ...r.body }),
    "POST /v1/world-builds": (r) => ({ job_id: "job_1", got: r.body }),
    "POST /v1/agent-profiles": (r) => ({ id: "ap_1", got: r.body }),
    "POST /v1/evaluations": (r) => ({ run_id: "run_1", got: r.body }),
    "POST /v1/factory": (r) => ({ job_id: "job_f", got: r.body }),
    "POST /v1/autofix": (r) => ({ job_id: "job_a", got: r.body }),
    "POST /v1/jobs/job_1/commands": (r) => ({ status: r.body.command }),
    "GET /v1/runs/run_1/failures": () => ({ "bot@v1": { causes: [] } }),
    "GET /v1/compare": (r) => ({ q: r.query }),
  });
  const run = async (...args) => { const r = await rehearsal(args, { url: s.url }); assert.equal(r.code, 0, r.stderr); return JSON.parse(r.stdout); };
  try {
    assert.deepEqual(await run("apps", "list"), [{ id: "app_1", name: "shop", source: { kind: "git" }, notes: "n" }]);
    const app = await run("apps", "add", "shop", "--git", "https://example.test/shop", "--commit", "abc", "--image", "web=img@sha256:1", "--image", "worker=img@sha256:2");
    assert.deepEqual(app.source, { kind: "git", url: "https://example.test/shop", commit: "abc" });
    assert.deepEqual(app.images, { web: "img@sha256:1", worker: "img@sha256:2" });
    assert.deepEqual((await run("build", "app_1", "--scenarios", "3", "--budget", "2.5")).got, { application_id: "app_1", scenario_target: 3, budget_usd: 2.5 });
    assert.deepEqual((await run("profiles", "create", "bot", "--prompt-file", join(dir, "prompt.md"), "--external")).got, { name: "bot", system_prompt: "Be careful.", driver: "external" });
    assert.deepEqual((await run("eval", "wv_1", "--profile", "ap_1", "--split", "holdout", "--repeats", "1")).got, { world_version_id: "wv_1", profile_ids: ["ap_1"], splits: ["holdout"], repeats: 1 });
    assert.deepEqual((await run("factory", "wv_1", "--rounds", "1")).got, { world_version_id: "wv_1", name: "", rounds: 1, repeats: 1 });
    assert.deepEqual((await run("autofix", "ap_1", "run_1", "--repeats", "2")).got, { profile_id: "ap_1", run_id: "run_1", rounds: 3, repeats: 2 });
    assert.deepEqual(await run("jobs", "pause", "job_1"), { status: "pause" });
    assert.deepEqual(await run("runs", "failures", "run_1"), { "bot@v1": { causes: [] } });
    assert.deepEqual((await run("compare", "run_1", "run_2")).q, { run_a: "run_1", run_b: "run_2" });
  } finally { await s.close(); }
});

test("watching a job prints one line per event in the Python format", async () => {
  const s = await stub({
    "POST /v1/world-builds": () => ({ job_id: "job_1" }),
    "GET /v1/jobs/job_1/events": (_, res) => {
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      res.end('data: {"event_id": 1, "created_at": "2026-10-27T10:11:12Z", "type": "compiler.phase.started", "summary": "plan started", "actor_id": "builder", "goal_version": 2}\n\n' +
              "event: stream.end\ndata: {}\n\n");
    },
  });
  try {
    const r = await rehearsal(["build", "app_1", "--watch"], { url: s.url });
    assert.equal(r.code, 0, r.stderr);
    assert.match(r.stdout, /\n10:11:12 compiler\.phase\.started {7}\[builder\] plan started \(goal v2\)\n$/);
  } finally { await s.close(); }
});

test("login with a key checks it, then saves it for this user only", async () => {
  const s = await stub({ "GET /v1/me": (r) => (r.headers.authorization === "Bearer rh_good_key" ? { organization: "Acme", project: "prj_1", scopes: ["admin"] } : [401, { detail: "bad key" }]) });
  try {
    let r = await rehearsal(["login", "--url", s.url, "--key", "not-a-key"], { key: null });
    assert.match(r.stderr, /keys start with rh_/);
    r = await rehearsal(["login", "--url", s.url, "--key", "rh_bad_key"], { key: null });
    assert.equal(r.code, 1);
    assert.ok(!existsSync(r.config), "a refused key is not saved");
    r = await rehearsal(["login", "--url", s.url + "/", "--key", "rh_good_key"], { key: null });
    assert.equal(r.code, 0, r.stderr);
    assert.match(r.stdout, /Signed in to Acme \(project prj_1\)/);
    assert.deepEqual(JSON.parse(readFileSync(r.config, "utf8")), { url: s.url, api_key: "rh_good_key" });
    assert.equal(statSync(r.config).mode & 0o777, 0o600);
  } finally { await s.close(); }
});

test("export-replay pages through the events and keeps the replayable ones", async () => {
  const events = Array.from({ length: 2500 }, (_, i) => ({ event_id: i + 1, type: i % 2 ? "compiler.tool" : "llm.call", episode_id: null }));
  const s = await stub({
    "GET /v1/streams/job_1/events/page": (r) => events.filter((e) => e.event_id > Number(r.query.cursor)).slice(0, Number(r.query.limit)),
  });
  try {
    const dest = join(tempDir(), "out", "replay.json");
    const r = await rehearsal(["export-replay", "job_1", dest], { url: s.url });
    assert.equal(r.code, 0, r.stderr);
    assert.match(r.stdout, /saved 1250 events/);
    const saved = JSON.parse(readFileSync(dest, "utf8"));
    assert.equal(saved.stream, "job_1");
    assert.ok(saved.events.every((e) => e.type === "compiler.tool"));
    assert.deepEqual(s.requests.map((q) => q.query.cursor), ["0", "2000", "2500"]);
  } finally { await s.close(); }
});

test("artifacts download writes the file, and skill install copies the skill", async () => {
  const s = await stub({ "GET /v1/artifacts/art_1/download": (_, res) => { res.writeHead(200); res.end(Buffer.from("PK zip")); } });
  const dir = tempDir();
  try {
    const r = await rehearsal(["artifacts", "download", "art_1", join(dir, "agent.zip")], { url: s.url });
    assert.equal(r.code, 0, r.stderr);
    assert.equal(readFileSync(join(dir, "agent.zip"), "utf8"), "PK zip");
    assert.ok(!existsSync(join(dir, "agent.zip.part")));
  } finally { await s.close(); }
  const r = await rehearsal(["skill", "install", "--dir", dir]);
  assert.equal(r.code, 0, r.stderr);
  assert.match(readFileSync(join(dir, "rehearsal", "SKILL.md"), "utf8"), /rehearsal/i);
});
