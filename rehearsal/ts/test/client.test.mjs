import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { Rehearsal, RehearsalError, DEFAULT_URL } from "../dist/index.js";
import { configPath, env, saveLogin, savedLogin } from "../dist/sdk/client.js";
import { stub, tempDir } from "./stub.mjs";

function withEnv(vars, fn) {
  const before = Object.fromEntries(Object.keys(vars).map((k) => [k, process.env[k]]));
  for (const [k, v] of Object.entries(vars)) v === undefined ? delete process.env[k] : (process.env[k] = v);
  try { return fn(); } finally { for (const [k, v] of Object.entries(before)) v === undefined ? delete process.env[k] : (process.env[k] = v); }
}

test("requests carry the key, JSON bodies and query parameters", async () => {
  const s = await stub({
    "POST /v1/world-builds": (r) => ({ job_id: "job_1", got: r.body }),
    "GET /v1/streams/job_1/events/page": (r) => [{ event_id: 1, q: r.query }],
  });
  try {
    const c = new Rehearsal({ apiKey: "rh_a_b", baseUrl: s.url + "/" });
    assert.equal(c.baseUrl, s.url);
    const res = await c.worlds.build("app_1", { scenario_target: 3 });
    assert.deepEqual(res.got, { application_id: "app_1", scenario_target: 3 });
    assert.equal(s.requests[0].headers.authorization, "Bearer rh_a_b");
    assert.equal(s.requests[0].headers["content-type"], "application/json");
    const page = await c.get("/v1/streams/job_1/events/page", { cursor: 5, limit: 2000, skip: undefined });
    assert.deepEqual(page[0].q, { cursor: "5", limit: "2000" });
  } finally { await s.close(); }
});

test("errors keep the status and the server's detail", async () => {
  const s = await stub({
    "GET /v1/jobs/job_x": () => [404, { detail: "job not found" }],
    "GET /v1/runs/run_x": (_, res) => { res.writeHead(502, { "Content-Type": "text/html" }); res.end("<html>" + "x".repeat(1000)); },
  });
  try {
    const c = new Rehearsal({ apiKey: "rh_k", baseUrl: s.url });
    await assert.rejects(c.jobs.get("job_x"), (e) => e instanceof RehearsalError && e.status === 404 && e.detail === "job not found");
    await assert.rejects(c.runs.get("run_x"), (e) => e instanceof RehearsalError && e.status === 502 && e.detail.length === 300);
  } finally { await s.close(); }
});

test("sign-in is saved for this user only and shared with the Python CLI's file", () => {
  const dir = tempDir();
  withEnv({ REHEARSAL_CONFIG: join(dir, "nested", "config.json"), REHEARSAL_API_KEY: undefined, REHEARSAL_URL: undefined }, () => {
    assert.deepEqual(savedLogin(), {});
    const path = saveLogin("https://example.test//", "rh_saved_key");
    assert.equal(path, configPath());
    assert.equal(statSync(path).mode & 0o777, 0o600);
    assert.deepEqual(JSON.parse(readFileSync(path, "utf8")), { url: "https://example.test", api_key: "rh_saved_key" });
    const c = new Rehearsal();
    assert.equal(c.apiKey, "rh_saved_key");
    assert.equal(c.baseUrl, "https://example.test");
    withEnv({ REHEARSAL_API_KEY: "rh_env", REHEARSAL_URL: "${user_config.url}" }, () => { // environment wins; an unexpanded placeholder is unset
      const e = new Rehearsal();
      assert.equal(e.apiKey, "rh_env");
      assert.equal(e.baseUrl, "https://example.test");
    });
    writeFileSync(path, "[1,2]");
    assert.deepEqual(savedLogin(), {});
  });
});

test("without any key the client says how to sign in", () => {
  withEnv({ REHEARSAL_CONFIG: join(tempDir(), "none.json"), REHEARSAL_API_KEY: undefined }, () => {
    assert.throws(() => new Rehearsal(), /rehearsal login/);
    assert.equal(env("REHEARSAL_API_KEY"), undefined);
    assert.equal(new Rehearsal({ apiKey: "rh_x" }).baseUrl, DEFAULT_URL);
  });
});

test("event streams reconnect from the last event and stop at stream.end", async () => {
  let calls = 0;
  const s = await stub({
    "GET /v1/jobs/job_1/events": (r, res) => {
      calls++;
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      if (r.query.cursor === "0") { // first connection drops after one event and half of another
        res.write('event: compiler.note\ndata: {"event_id": 7, "type": "compiler.note"}\n\n');
        res.end('data: {"event_id": 8');
      } else {
        assert.equal(r.query.cursor, "7");
        res.end('data: {"event_id": 8, "type": "world.published"}\n\nevent: stream.end\ndata: {}\n\n');
      }
    },
  });
  try {
    const c = new Rehearsal({ apiKey: "rh_k", baseUrl: s.url });
    const seen = [];
    for await (const ev of c.jobs.events("job_1")) seen.push(ev.event_id);
    assert.deepEqual(seen, [7, 8]);
    assert.equal(calls, 2);
  } finally { await s.close(); }
});

test("an HTTP error on a stream is raised, not retried", async () => {
  const s = await stub({ "GET /v1/runs/run_1/events": () => [403, { detail: "no access" }] });
  try {
    const c = new Rehearsal({ apiKey: "rh_k", baseUrl: s.url });
    await assert.rejects(async () => { for await (const _ of c.runs.events("run_1")); }, (e) => e.status === 403);
  } finally { await s.close(); }
});

test("source uploads are multipart, and downloads return the bytes", async () => {
  const dir = tempDir();
  const archive = join(dir, "app.tar.gz");
  writeFileSync(archive, Buffer.from([0x1f, 0x8b, 0x08, 0x00]));
  const s = await stub({
    "POST /v1/applications/app_1/source": (r) => ({ ok: r.headers["content-type"].startsWith("multipart/form-data"), body: r.body }),
    "GET /v1/artifacts/art_1/download": (_, res) => { res.writeHead(200, { "Content-Type": "application/zip" }); res.end(Buffer.from([1, 2, 3])); },
  });
  try {
    const c = new Rehearsal({ apiKey: "rh_k", baseUrl: s.url });
    const res = await c.applications.uploadSource("app_1", archive);
    assert.ok(res.ok);
    assert.match(res.body, /filename="app.tar.gz"/);
    assert.deepEqual([...(await c.download("/v1/artifacts/art_1/download"))], [1, 2, 3]);
  } finally { await s.close(); }
});

test("bring-your-own agents act once per idempotency key and wait for the result", async () => {
  let polls = 0;
  const s = await stub({
    "POST /v1/episodes/ep_1/actions": (r) => ({ accepted: r.body.idempotency_key }),
    "GET /v1/episodes/ep_1/actions/k1": () => (++polls < 2 ? { status: "pending" } : { status: "done", result: { ok: true } }),
  });
  try {
    const c = new Rehearsal({ apiKey: "rh_k", baseUrl: s.url });
    assert.deepEqual(await c.external.act("ep_1", "support", "refund", { id: 1 }, "k1", 5), { ok: true });
    assert.deepEqual(s.requests[0].body, { actor: "support", tool: "refund", args: { id: 1 }, idempotency_key: "k1" });
  } finally { await s.close(); }
});
