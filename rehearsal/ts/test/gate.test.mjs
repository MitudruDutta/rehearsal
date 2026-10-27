import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { Rehearsal } from "../dist/index.js";
import { FAILED, PASSED, UNFINISHED, report, run, verdict } from "../dist/sdk/gate.js";
import { stub, tempDir } from "./stub.mjs";

const agg = (o) => ({ success_rate: 0.8, successes: 8, finished: 10, hard_violation_episodes: 0, false_completions: 0, duplicate_effects: 0, environment_errors: 0, ...o });
const summary = (cand, base) => ({ profiles: { "bot@v2": { overall: agg(cand) }, ...(base ? { "bot@v1": { overall: agg(base) } } : {}) } });

test("verdict: nothing scored fails with the reason", () => {
  const [ok, checks] = verdict({ profiles: { "bot@v2": { overall: agg({ success_rate: null }) } } }, "bot@v2");
  assert.equal(ok, false);
  assert.match(checks[0][1], /nothing was scored/);
});

test("verdict: required success rate and rule violations", () => {
  assert.equal(verdict(summary({}), "bot@v2", null, { minSuccess: 0.8 })[0], true);
  const [ok, checks] = verdict(summary({ hard_violation_episodes: 2 }), "bot@v2", null, { minSuccess: 0.9 });
  assert.equal(ok, false);
  assert.deepEqual(checks.map((c) => c[0]), [false, false]);
  assert.equal(checks[0][1], "verified success 80%, required 90%");
  assert.equal(checks[1][1], "2 episodes broke a rule, at most 0 allowed");
});

test("verdict: nothing may get worse than the baseline, within the tolerance", () => {
  assert.equal(verdict(summary({ success_rate: 0.7 }, { success_rate: 0.8 }), "bot@v2", "bot@v1")[0], false);
  const [ok, checks] = verdict(summary({ success_rate: 0.7 }, { success_rate: 0.8 }), "bot@v2", "bot@v1", { tolerance: 0.1 });
  assert.equal(ok, true);
  assert.match(checks[1][1], /vs 80% for the baseline, 10% tolerance/);
  assert.equal(verdict(summary({ duplicate_effects: 1 }, {}), "bot@v2", "bot@v1")[0], false);
});

test("report: a table for both agents, the checks, and the named causes", () => {
  const s = summary({}, { success_rate: 0.5, successes: 5 });
  const [ok, checks] = verdict(s, "bot@v2", "bot@v1");
  const text = report(s, "bot@v2", "bot@v1", ok, checks, "http://x/app/run/?id=run_1", "", [{ label: "Acted twice", count: 1, fix: "Check first." }]);
  assert.match(text, /^### Rehearsal gate: passed/);
  assert.match(text, /\| Verified success \| 80% \(8\/10\) \| 50% \(5\/10\) \|/);
  assert.match(text, /- PASS: verified success 80% vs 50% for the baseline/);
  assert.match(text, /- Acted twice: 1 episode\. Check first\./);
});

function gateServer(finalRun, profiles = []) {
  return stub({
    "GET /v1/agent-profiles": () => profiles,
    "POST /v1/agent-profiles": (r) => ({ id: `ap_${r.body.name}_new`, name: r.body.name, version: 3, spec: { system_prompt: r.body.system_prompt } }),
    "POST /v1/evaluations": (r) => ({ run_id: "run_1", episodes: 4, got: r.body }),
    "GET /v1/runs/run_1": () => finalRun,
    "GET /v1/runs/run_1/failures": () => [403, { detail: "evaluator access needed" }],
  });
}

test("run: reuses the version with the same instructions, rehearses next to the baseline, appends the report", async () => {
  const dir = tempDir();
  writeFileSync(join(dir, "new.md"), "be careful");
  writeFileSync(join(dir, "old.md"), "be fast");
  const profiles = [{ id: "ap_old", name: "bot", version: 1, spec: { system_prompt: "be fast" } },
                    { id: "ap_new", name: "bot", version: 2, spec: { system_prompt: "be careful" } }];
  const s = await gateServer({ status: "finished", summary: summary({}, { success_rate: 0.5 }) }, profiles);
  const out = [], err = [];
  try {
    const code = await run(new Rehearsal({ apiKey: "rh_k", baseUrl: s.url }),
                           { wvId: "wv_1", promptFile: join(dir, "new.md"), baselineFile: join(dir, "old.md"), name: "bot", report: join(dir, "summary.md"), minSuccess: 0.6 },
                           { out: (x) => out.push(x), err: (x) => err.push(x), pollS: 0 });
    assert.equal(code, PASSED);
    const evaluation = s.requests.find((r) => r.path === "/v1/evaluations").body;
    assert.deepEqual(evaluation, { world_version_id: "wv_1", profile_ids: ["ap_new", "ap_old"], repeats: 1 });
    assert.ok(!s.requests.some((r) => r.method === "POST" && r.path === "/v1/agent-profiles"), "no new version for unchanged instructions");
    assert.match(readFileSync(join(dir, "summary.md"), "utf8"), /Rehearsal gate: passed/);
    assert.match(err.join("\n"), /rehearsing bot@v2 next to bot@v1: 4 episodes/);
    assert.match(out[0], /\/app\/run\/\?id=run_1/);
  } finally { await s.close(); }
});

test("run: a failing change exits 1, an unfinished run exits 2, missing arguments exit 2", async () => {
  const quiet = { out: () => {}, err: () => {}, pollS: 0 };
  const p = await stub({
    "GET /v1/agent-profiles/ap_1": () => ({ id: "ap_1", name: "bot", version: 4 }),
    "GET /v1/runs/run_9": () => ({ status: "finished", summary: { profiles: { "bot@v4": { overall: agg({ success_rate: 0.2 }) } } } }),
    "GET /v1/runs/run_9/failures": () => ({}),
    "GET /v1/runs/run_8": () => ({ status: "failed" }),
  });
  try {
    const c = new Rehearsal({ apiKey: "rh_k", baseUrl: p.url });
    assert.equal(await run(c, { profile: "ap_1", run: "run_9", minSuccess: 0.5 }, quiet), FAILED);
    assert.equal(await run(c, { profile: "ap_1", run: "run_8" }, quiet), UNFINISHED);
    assert.equal(await run(c, { profile: "ap_1" }, quiet), UNFINISHED);
    assert.equal(await run(c, { promptFile: "x.md" }, quiet), UNFINISHED);
  } finally { await p.close(); }
});
