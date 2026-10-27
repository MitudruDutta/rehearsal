// The TypeScript client against a local stand-in for the Rehearsal API.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { after, before, test } from "node:test";

import { Rehearsal, RehearsalError } from "../dist/index.js";

const seen = [];
let server, rh, streamCalls = 0, jobPolls = 0, actionPolls = 0;

before(async () => {
  server = createServer(async (req, res) => {
    let body = "";
    for await (const chunk of req) body += chunk;
    const url = new URL(req.url, "http://x");
    seen.push({ method: req.method, path: url.pathname, query: Object.fromEntries(url.searchParams), auth: req.headers.authorization, body: body ? JSON.parse(body) : undefined });
    const json = (status, data) => { res.writeHead(status, { "Content-Type": "application/json" }); res.end(JSON.stringify(data)); };
    if (url.pathname === "/v1/factory") return json(202, { job_id: "job_1", episodes: 11 });
    if (url.pathname === "/v1/autofix") return json(202, { job_id: "job_2", episodes: 8 });
    if (url.pathname === "/v1/runs/run_1/failures") return json(200, { "agent@v1": { failed: 2, causes: [{ cause: "duplicate", count: 2 }] } });
    if (url.pathname === "/v1/runs/missing") return json(404, { detail: "run not found" });
    if (url.pathname === "/v1/broken") { res.writeHead(502); return res.end("<html>bad gateway</html>"); }
    if (url.pathname === "/v1/jobs/job_1") return json(200, { id: "job_1", status: ++jobPolls < 3 ? "running" : "succeeded" });
    if (url.pathname === "/v1/episodes/ep_1/actions" && req.method === "POST") return json(202, { accepted: true });
    if (url.pathname === "/v1/episodes/ep_1/actions/key-1") return json(200, ++actionPolls < 2 ? { status: "pending" } : { status: "done", result: { ok: true } });
    if (url.pathname === "/v1/jobs/job_1/events") {
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      if (++streamCalls === 1) {  // the first connection ends after one event
        res.write('data: {"event_id": 5, "type": "compiler.phase.started"}\n\n');
        return res.end();  // the server goes away mid-stream, without stream.end
      }
      res.write('data: {"event_id": 6, "type": "compiler.phase.completed"}\n\n');
      res.write("event: stream.end\ndata: {}\n\n");
      return res.end();
    }
    json(404, { detail: `no route ${url.pathname}` });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  rh = new Rehearsal({ apiKey: "rh_test", baseUrl: `http://127.0.0.1:${server.address().port}/` });
});

after(() => server.close());

test("requests carry the key and JSON bodies, and new features use their endpoints", async () => {
  assert.deepEqual(await rh.worlds.makeAgent("wv_1", { name: "desk-agent", rounds: 2 }), { job_id: "job_1", episodes: 11 });
  assert.equal((await rh.profiles.autofix("prof_1", "run_0")).job_id, "job_2");
  assert.equal((await rh.runs.failures("run_1"))["agent@v1"].causes[0].cause, "duplicate");
  const factory = seen.find((r) => r.path === "/v1/factory");
  assert.equal(factory.auth, "Bearer rh_test");
  assert.deepEqual(factory.body, { world_version_id: "wv_1", name: "desk-agent", rounds: 2, repeats: 1 });
  assert.deepEqual(seen.find((r) => r.path === "/v1/autofix").body, { profile_id: "prof_1", run_id: "run_0", rounds: 3, repeats: 1 });
});

test("errors keep the server's detail, and an HTML error page is cut short", async () => {
  await assert.rejects(rh.get("/v1/runs/missing"), (err) => err instanceof RehearsalError && err.status === 404 && err.detail === "run not found");
  await assert.rejects(rh.get("/v1/broken"), (err) => err.status === 502 && err.detail.startsWith("<html>"));
});

test("an event stream reconnects from the last event id and stops at stream.end", async () => {
  const types = [];
  for await (const ev of rh.jobs.events("job_1")) types.push(ev.type);
  assert.deepEqual(types, ["compiler.phase.started", "compiler.phase.completed"]);
  const cursors = seen.filter((r) => r.path === "/v1/jobs/job_1/events").map((r) => r.query.cursor);
  assert.deepEqual(cursors, ["0", "5"]);
});

test("waiting helpers poll until there is an answer", async () => {
  assert.equal((await rh.jobs.wait("job_1", { pollMs: 5 })).status, "succeeded");
  assert.deepEqual(await rh.external.act("ep_1", "agent", "close_ticket", { id: 7 }, "key-1"), { ok: true });
  assert.deepEqual(seen.find((r) => r.path === "/v1/episodes/ep_1/actions").body, { actor: "agent", tool: "close_ticket", args: { id: 7 }, idempotency_key: "key-1" });
});

test("a key is required", () => {
  const saved = process.env.REHEARSAL_API_KEY;
  delete process.env.REHEARSAL_API_KEY;
  assert.throws(() => new Rehearsal(), /no Rehearsal API key/);
  process.env.REHEARSAL_API_KEY = "${REHEARSAL_API_KEY}"; // an unexpanded placeholder counts as unset
  assert.throws(() => new Rehearsal(), /no Rehearsal API key/);
  if (saved === undefined) delete process.env.REHEARSAL_API_KEY; else process.env.REHEARSAL_API_KEY = saved;
});

test("stopping early closes the stream, so the process can exit", async () => {
  const before = streamCalls;
  for await (const ev of rh.jobs.events("job_1")) { assert.ok(ev.type); break; }
  assert.equal(streamCalls, before + 1); // one connection, no reconnect after the caller left
});
