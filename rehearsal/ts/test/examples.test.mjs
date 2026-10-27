import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { Rehearsal } from "../dist/index.js";
import { exportExample, safeName } from "../dist/sdk/examples.js";
import { stub, tempDir } from "./stub.mjs";

const scenario = (slug, split, status = "approved") => ({ id: `sc_${slug}`, slug, split, status, family: "refund", spec: { title: `Title ${slug}`, goals: [1, 2] } });

test("an example holds the published world, the train jobs only, and the finished runs", async () => {
  const s = await stub({
    "GET /v1/world-versions/wv_1": () => ({
      version: 2, content_hash: "h1", capabilities: { tools: 1 }, validation: { repairs: [{ outcome: "repaired" }], rejected: { x: "unfair" } },
      provenance: { url: "https://example.test/shop", commit: "abc", spent_usd: 3.456, tokens: 12345, compiler_chain: "nebius:nemotron" },
      manifest: { name: "shop", services: [{ name: "web" }], roles: [{ name: "support" }], tools: [{ name: "refund", method: "POST", path: "/refunds", mutating: true, roles: ["support"] }] },
    }),
    "GET /v1/world-versions/wv_1/scenarios": () => [scenario("a", "train"), scenario("b", "holdout"), scenario("c", "dev"), scenario("d", "train", "rejected")],
    "GET /v1/runs": () => [
      { id: "run_1", world_version_id: "wv_1", status: "finished", config: { splits: ["holdout"] }, finished_at: "t",
        summary: { profiles: { "bot@v1": { overall: { success_rate: 0.5, successes: 1, finished: 2, hard_violation_episodes: 0, false_completions: 1, recovered: 0 } } } } },
      { id: "run_2", world_version_id: "wv_1", status: "running", config: {}, summary: {} },
    ],
  });
  const root = tempDir();
  try {
    const row = await exportExample(new Rehearsal({ apiKey: "rh_k", baseUrl: s.url }), "wv_1", root);
    assert.deepEqual(row, { application: "shop", domain: "", license: "", split: "development", status: "published", world_version: 2,
                            scenarios: 3, tools: 1, repairs: 1, spend_usd: 3.456, tokens: 12345 });
    const dest = join(root, "examples", "shop");
    assert.deepEqual(readdirSync(join(dest, "scenarios", "train")), ["a.json"]); // dev and held-out jobs stay private
    assert.deepEqual(readdirSync(join(dest, "runs")), ["run_1.json"]);
    const readme = readFileSync(join(dest, "README.md"), "utf8");
    assert.match(readme, /model spend \$3\.46, 12,345 tokens/);
    assert.match(readme, /\| `run_1` \| bot@v1 \| holdout \| 50% \(1\/2\) \| 0 \| 1 \| 0 \|/);
    assert.match(readme, /\| `refund` \| `POST \/refunds` \| support \|/);
    const index = JSON.parse(readFileSync(join(root, "examples", "index.json"), "utf8"));
    assert.deepEqual(index.applications, [row]);
    assert.ok(existsSync(join(root, "web", "public", "examples", "index.json")));
  } finally { await s.close(); }
});

test("file names from the server cannot leave the examples folder", () => {
  for (const bad of ["", ".", "..", "a/b", "a\\b", "a\0b"]) assert.throws(() => safeName(bad), /unsafe/);
  assert.equal(safeName("shop-1"), "shop-1");
});
