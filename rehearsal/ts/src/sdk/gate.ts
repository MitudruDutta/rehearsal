/**
 * `rehearsal gate`: a pass or fail check for an agent change, for CI. The mirror of rehearsal/sdk/gate.py.
 *
 * It rehearses the agent (a profile, or a new version made from the instructions file in the change) on a published
 * world, next to a baseline version when one is given, waits for the run, and judges the result: the verified success
 * must reach the required rate, rule violations must stay under the limit, and nothing may get worse than the baseline.
 * It prints a Markdown report (also appended to --report, for example $GITHUB_STEP_SUMMARY) and exits 0 when the change
 * passes, 1 when it fails, and 2 when the run did not finish.
 */

import { appendFileSync, readFileSync } from "node:fs";

import type { Json, Rehearsal } from "./client.js";

export const PASSED = 0, FAILED = 1, UNFINISHED = 2;

export const ROWS: [string, string][] = [
  ["success_rate", "Verified success"], ["hard_violation_episodes", "Episodes with a rule violation"],
  ["false_completions", "Claimed done but was not"], ["duplicate_effects", "Duplicate side effects"],
  ["environment_errors", "Environment errors (not scored)"],
];

const pct = (x: number | null | undefined): string => (x === null || x === undefined ? "–" : `${Math.round(x * 100)}%`);

export type Check = [passed: boolean, reason: string];

/** Whether the candidate passes, with one [passed, reason] line per check. Profiles are keyed `name@vN`. */
export function verdict(summary: Json, candidate: string, baseline: string | null = null,
                        options: { minSuccess?: number | null; maxViolations?: number | null; tolerance?: number } = {}): [boolean, Check[]] {
  const { minSuccess = null, maxViolations = 0, tolerance = 0 } = options;
  const profiles = summary.profiles ?? {};
  const cand = profiles[candidate]?.overall;
  if (!cand || cand.success_rate === null || cand.success_rate === undefined) {
    return [false, [[false, "nothing was scored: every episode hit an environment error, or the agent had no episodes"]]];
  }
  const rate: number = cand.success_rate;
  const checks: Check[] = [];
  if (minSuccess !== null && minSuccess !== undefined) checks.push([rate >= minSuccess, `verified success ${pct(rate)}, required ${pct(minSuccess)}`]);
  if (maxViolations !== null && maxViolations !== undefined) {
    checks.push([cand.hard_violation_episodes <= maxViolations, `${cand.hard_violation_episodes} episodes broke a rule, at most ${maxViolations} allowed`]);
  }
  const base = baseline ? profiles[baseline]?.overall : null;
  if (base && base.success_rate !== null && base.success_rate !== undefined) {
    const slack = tolerance ? `, ${pct(tolerance)} tolerance` : "";
    checks.push([rate >= base.success_rate - tolerance - 1e-9, // rates are ratios of small counts: 0.8 - 0.1 is not quite 0.7 in floating point
                   `verified success ${pct(rate)} vs ${pct(base.success_rate)} for the baseline${slack}`]);
    for (const [key, what] of ROWS.slice(1, 4)) checks.push([cand[key] <= base[key], `${what.toLowerCase()}: ${cand[key]} vs ${base[key]} for the baseline`]);
  }
  return [checks.every(([ok]) => ok), checks];
}

export function report(summary: Json, candidate: string, baseline: string | null, passed: boolean, checks: Check[],
                       runLink: string, note = "", causes: Json[] | null = null): string {
  const cols: [string, string][] = [[candidate, "this change"], ...(baseline ? [[baseline, "baseline"] as [string, string]] : [])];
  const aggs = cols.map(([key]) => summary.profiles?.[key]?.overall ?? {});
  const cell = (agg: Json, key: string) => (key === "success_rate" ? `${pct(agg[key])} (${agg.successes ?? 0}/${agg.finished ?? 0})` : String(agg[key] ?? "–"));
  const lines = [
    `### Rehearsal gate: ${passed ? "passed" : "failed"}`, "",
    `Every episode is checked against the application's own database. [Open the run](${runLink})`, "",
    "| | " + cols.map(([key, label]) => `\`${key}\` (${label})`).join(" | ") + " |", "|---|" + "---|".repeat(cols.length),
    ...ROWS.map(([key, label]) => `| ${label} | ` + aggs.map((a) => cell(a, key)).join(" | ") + " |"),
    "", ...checks.map(([ok, text]) => `- ${ok ? "PASS" : "FAIL"}: ${text}`),
  ];
  if (causes?.length) {
    lines.push("", `**Why \`${candidate}\` failed episodes**`, "");
    for (const c of causes.slice(0, 3)) lines.push(`- ${c.label}: ${c.count} episode${c.count !== 1 ? "s" : ""}. ${c.fix}`);
  }
  return [...lines, ...(note ? ["", note] : [])].join("\n") + "\n";
}

/** The check could not run (a usage or server problem): exit 2, so CI does not read it as the agent failing. */
export class Unfinished extends Error {}

export interface GateArgs {
  wvId?: string | null; profile?: string | null; promptFile?: string | null; name?: string | null;
  baseline?: string | null; baselineFile?: string | null; split?: string[]; repeats?: number;
  minSuccess?: number | null; maxViolations?: number | null; tolerance?: number; budget?: number | null;
  run?: string | null; timeout?: number; report?: string | null;
}

/** The profile to test. From a file, the latest version of `name` with the same instructions is reused, so an
 * unchanged file does not add a version on every CI run. */
async function profileFor(c: Rehearsal, profileId?: string | null, promptFile?: string | null, name?: string | null): Promise<Json> {
  if (profileId) return c.get(`/v1/agent-profiles/${profileId}`);
  if (!(promptFile && name)) throw new Unfinished("give --profile, or --prompt-file with --name");
  const prompt = readFileSync(promptFile, "utf8");
  const same = (await c.profiles.list()).filter((p) => p.name === name && p.spec?.system_prompt === prompt && (p.spec?.driver ?? "llm") === "llm");
  return same.length ? same.reduce((a, b) => (b.version > a.version ? b : a)) : c.profiles.create(name, prompt);
}

async function waitFor(c: Rehearsal, runId: string, timeoutS: number, pollS = 15, log: (s: string) => void): Promise<Json | null> {
  const deadline = Date.now() + timeoutS * 1000;
  let last: string | null = null;
  while (Date.now() < deadline) {
    const run = await c.runs.get(runId);
    if (run.status !== last) { log(`run ${runId}: ${run.status}`); last = run.status; }
    if (["finished", "failed", "cancelled"].includes(run.status)) return run;
    await new Promise((r) => setTimeout(r, pollS * 1000));
  }
  return null;
}

export async function run(c: Rehearsal, args: GateArgs, io: { out?: (s: string) => void; err?: (s: string) => void; pollS?: number } = {}): Promise<number> {
  const out = io.out ?? ((s) => process.stdout.write(s + "\n"));
  const err = io.err ?? ((s) => process.stderr.write(s + "\n"));
  try {
    const cand = await profileFor(c, args.profile, args.promptFile, args.name);
    let base = args.baseline || args.baselineFile ? await profileFor(c, args.baseline, args.baselineFile, args.name) : null;
    let note = "";
    if (base && base.id === cand.id) {
      base = null;
      note = "The change does not touch the agent's instructions, so there is no baseline to compare with.";
    }
    const key = (p: Json) => `${p.name}@v${p.version}`;
    let runId: string;
    if (args.run) runId = args.run;
    else {
      if (!args.wvId) throw new Unfinished("give the world version to rehearse on, or --run with a finished run");
      const res = await c.evaluations.create(args.wvId, [cand.id, ...(base ? [base.id] : [])], args.split?.length ? args.split : null, args.repeats ?? 1,
                                             args.budget !== null && args.budget !== undefined ? { budget_usd: args.budget } : {});
      runId = res.run_id;
      const later = res.starts_at ? `; on the free plan it starts at ${res.starts_at} (UTC)` : "";
      err(`rehearsing ${key(cand)}${base ? " next to " + key(base) : ""}: ${res.episodes} episodes${later}`);
    }
    const finished = await waitFor(c, runId, (args.timeout ?? 90) * 60, io.pollS ?? 15, err);
    const link = `${c.baseUrl}/app/run/?id=${runId}`;
    if (!finished || finished.status !== "finished") {
      err(`The run did not finish (${finished ? finished.status : "timed out"}): ${link}`);
      return UNFINISHED;
    }
    const [passed, checks] = verdict(finished.summary ?? {}, key(cand), base ? key(base) : null,
                                     { minSuccess: args.minSuccess, maxViolations: args.maxViolations ?? 0, tolerance: args.tolerance ?? 0 });
    let causes: Json[] | null = null;
    try { // named causes need a key with evaluator access; the verdict does not depend on them
      causes = (await c.get(`/v1/runs/${runId}/failures`))?.[key(cand)]?.causes ?? null;
    } catch { causes = null; }
    const text = report(finished.summary ?? {}, key(cand), base ? key(base) : null, passed, checks, link, note, causes);
    out(text);
    if (args.report) appendFileSync(args.report, text, "utf8");
    return passed ? PASSED : FAILED;
  } catch (e) {
    if (e instanceof Unfinished) { err(e.message); return UNFINISHED; }
    throw e;
  }
}
