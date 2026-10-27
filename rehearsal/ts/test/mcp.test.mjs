import { test } from "node:test";
import assert from "node:assert/strict";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import { Rehearsal } from "../dist/index.js";
import { buildServer } from "../dist/sdk/mcp.js";
import { pythonSource, stub } from "./stub.mjs";

async function connect(client) {
  const [a, b] = InMemoryTransport.createLinkedPair();
  await buildServer(client).connect(a);
  const mcp = new Client({ name: "test", version: "0" });
  await mcp.connect(b);
  return mcp;
}

const text = (res) => JSON.parse(res.content[0].text);

test("the same tools, with the same arguments, as the Python MCP server", async (t) => {
  const mcp = await connect(new Rehearsal({ apiKey: "rh_k", baseUrl: "http://127.0.0.1:9" }));
  const { tools } = await mcp.listTools();
  const ts = Object.fromEntries(tools.map((x) => [x.name, Object.keys(x.inputSchema.properties ?? {}).sort()]));
  assert.equal(tools.length, 20);
  const py = pythonSource("sdk/mcp.py");
  if (!py) return t.skip("the Python package is not in this checkout");
  const expected = {};
  for (const m of py.matchAll(/@mcp\.tool\(\)\s+def (\w+)\(([^)]*)\)/g)) {
    expected[m[1]] = [...m[2].matchAll(/(?:^|,)\s*(\w+)\s*:/g)].map((p) => p[1]).sort();
  }
  assert.deepEqual(ts, expected);
  await mcp.close();
});

test("tools call the API and return its answer as JSON text", async () => {
  const s = await stub({
    "GET /v1/applications": () => [{ id: "app_1", name: "shop", source: { kind: "git" }, notes: "", secret: "not shown" }],
    "POST /v1/world-builds": (r) => ({ job_id: "job_1", got: r.body }),
    "POST /v1/episodes/ep_1/actions": () => ({ accepted: true }),
    "GET /v1/episodes/ep_1/actions/:any": () => ({}),
  });
  try {
    const mcp = await connect(new Rehearsal({ apiKey: "rh_k", baseUrl: s.url }));
    assert.deepEqual(text(await mcp.callTool({ name: "list_applications", arguments: {} })), [{ id: "app_1", name: "shop", source: { kind: "git" }, notes: "" }]);
    await mcp.callTool({ name: "build_world", arguments: { application_id: "app_1", scenarios: 4 } });
    const build = s.requests.find((r) => r.path === "/v1/world-builds").body;
    assert.equal(build.application_id, "app_1");
    assert.equal(build.scenario_target, 4);
    const bad = await mcp.callTool({ name: "job_status", arguments: {} }); // a missing argument is refused before any request
    assert.equal(bad.isError, true);
    await mcp.close();
  } finally { await s.close(); }
});

test("without a sign-in, tools explain how to sign in instead of failing to start", async () => {
  const before = { key: process.env.REHEARSAL_API_KEY, config: process.env.REHEARSAL_CONFIG };
  delete process.env.REHEARSAL_API_KEY;
  process.env.REHEARSAL_CONFIG = "/nonexistent/rehearsal/config.json";
  try {
    const mcp = await connect();
    const res = await mcp.callTool({ name: "list_worlds", arguments: {} });
    assert.equal(res.isError, true);
    assert.match(res.content[0].text, /not signed in.*rehearsal login/s);
    await mcp.close();
  } finally {
    before.key === undefined ? delete process.env.REHEARSAL_API_KEY : (process.env.REHEARSAL_API_KEY = before.key);
    before.config === undefined ? delete process.env.REHEARSAL_CONFIG : (process.env.REHEARSAL_CONFIG = before.config);
  }
});
