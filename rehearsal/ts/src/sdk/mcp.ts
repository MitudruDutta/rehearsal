/**
 * MCP server: lets an AI assistant (Claude Code, Cursor, Codex, ...) use Rehearsal with a Rehearsal API key.
 * The mirror of rehearsal/sdk/mcp.py: the same tools, arguments and answers.
 *
 *     rehearsal login                      # once: saves the server URL and an API key
 *     claude mcp add rehearsal -- npx rehearsal-kit mcp
 *     (or REHEARSAL_API_KEY / REHEARSAL_URL in the server's environment)
 *
 * The assistant can add applications, build practice worlds, run evaluations, read why episodes failed, and propose a
 * better agent version. It can also be the agent under test: an agent created with bring_your_own=true gets its turns
 * through waiting_turns and acts through take_action. Every call uses the key's own permissions; model costs of builds
 * and evaluations count against the workspace's monthly allowance.
 */

import { randomUUID } from "node:crypto";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import { Rehearsal, VERSION, type Json } from "./client.js";

export const INSTRUCTIONS =
  "Rehearsal tests AI agents on a sandboxed copy of a real application, with fictional data, a simulated customer who " +
  "changes their mind, and injected faults; results are checked against the application's own database. Typical flow: " +
  "list_applications or add_application -> build_world (1-3 hours; check with job_status) -> list_worlds -> list_agents " +
  "or create_agent (no agent yet? make_agent writes, hardens and proves one) -> run_evaluation -> run_results -> episode_details for failures -> fix_agent (rounds of improve and " +
  "rehearse, proven on held-out jobs; or improve_agent for one proposal) -> job_status. Builds and evaluations spend " +
  "model money from the workspace's monthly allowance: say what you are about to start and ask the user before " +
  "build_world, run_evaluation, make_agent, fix_agent, improve_agent and recheck_world. To act as the agent under test yourself, create_agent(bring_your_own=True), start run_evaluation with " +
  "it, then loop: waiting_turns -> read the new messages -> take_action with one of the offered tools.";

const short = (text: unknown, n = 600): string => {
  const s = text === null || text === undefined ? "" : typeof text === "string" ? text : JSON.stringify(text);
  return s.length <= n ? s : s.slice(0, n) + "...";
};

/** Connects on first use, so the server starts (and the assistant can explain what to do) before the user signs in. */
function lazyClient(): () => Rehearsal {
  let c: Rehearsal | null = null;
  return () => {
    if (c) return c;
    try {
      c = new Rehearsal();
    } catch {
      throw new Error("Rehearsal is not signed in on this machine. Ask the user to run `rehearsal login` " +
                      "(or `npx rehearsal-kit login`) with an API key from the console's API keys page, then try again.");
    }
    return c;
  };
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function buildServer(client?: Rehearsal): McpServer {
  const get = client ? () => client : lazyClient();
  const link = (path: string) => `${get().baseUrl}${path}`;
  const mcp = new McpServer({ name: "rehearsal", version: VERSION }, { instructions: INSTRUCTIONS });
  const tool = <S extends z.ZodRawShape>(name: string, description: string, shape: S, fn: (args: z.infer<z.ZodObject<S>>) => Promise<unknown>) =>
    mcp.registerTool(name, { description, inputSchema: shape }, (async (args: any) => {
      const result = await fn(args);
      return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 1) }] };
    }) as any);

  // ------------------------------------------------------------------ workspace and applications

  tool("workspace_status", "The workspace's plan and what it has left this month (applications, world builds, episodes, sandboxes), model " +
       "spend against the monthly allowance, and what exists in the workspace.", {}, async () => {
    const c = get();
    const usage = await c.get("/v1/usage");
    const b = await c.get("/v1/billing");
    const plan = { name: b.plan.title, limits: Object.fromEntries(["applications", "builds", "episodes", "sandboxes"].map((k) => [k, b.plan[k]])),
                   used: b.usage, renews: b.renews, quiet_hours_utc: b.quiet_hours_utc, more: link("/app/billing/") };
    const worlds: Json[] = await c.get("/v1/worlds");
    const published = worlds.flatMap((w) => w.versions).filter((v: Json) => v.status === "published");
    return { plan, usage, applications: (await c.get("/v1/applications")).length, published_world_versions: published.length,
             agents: (await c.get("/v1/agent-profiles")).length, console: link("/app/") };
  });

  tool("list_applications", "Applications in the workspace (the real apps that practice worlds are built from).", {}, async () =>
    (await get().get<Json[]>("/v1/applications")).map((a) => ({ id: a.id, name: a.name, source: a.source, notes: a.notes })));

  tool("add_application", "Add an application from a public git repository. images maps service name to a pinned image " +
       "(for example {\"app\": \"org/app:1.2@sha256:...\"}). policies are rules agents must follow, in plain words.",
       { name: z.string(), repository_url: z.string(), commit: z.string().default(""), images: z.record(z.string(), z.string()).optional(), policies: z.string().default("") },
       async ({ name, repository_url, commit, images, policies }) => {
    const source = { kind: "git", url: repository_url, ...(commit ? { commit } : {}) };
    const a = await get().post("/v1/applications", { name, source, images: images ?? {}, policies });
    return { id: a.id, name: a.name };
  });

  // ------------------------------------------------------------------ worlds

  tool("build_world", "Start compiling an application into a practice world. Takes 1-3 hours and spends model money (about $3-8). " +
       "Ask the user first. Follow progress with job_status.",
       { application_id: z.string(), scenarios: z.number().int().default(8), budget_usd: z.number().optional() }, async ({ application_id, scenarios, budget_usd }) => {
    const r = await get().post("/v1/world-builds", { application_id, scenario_target: scenarios, ...(budget_usd ? { budget_usd } : {}) });
    return { ...r, watch: link(`/app/build/?id=${r.job_id}`) };
  });

  tool("job_status", "Status of a build, evaluation shard or improvement job: state, finished steps, spend, and the error if it failed.",
       { job_id: z.string() }, async ({ job_id }) => {
    const j = await get().get(`/v1/jobs/${job_id}`);
    return { id: j.id, kind: j.kind, status: j.status, attempts: j.attempts, spent_usd: Math.round((j.spent_usd ?? 0) * 10000) / 10000,
             completed_steps: j.completed_phases, result: j.result, error: short(j.error, 800) || null };
  });

  tool("control_job", "pause, resume, stop, or retry (restart a failed or stopped job from its last saved step).",
       { job_id: z.string(), command: z.string() }, async ({ job_id, command }) => get().post(`/v1/jobs/${job_id}/commands`, { command }));

  tool("list_worlds", "Practice worlds and their versions. Only published versions can be used in evaluations.", {}, async () =>
    (await get().get<Json[]>("/v1/worlds")).map((w) => ({ world: w.name, application_id: w.application_id,
      versions: w.versions.map((v: Json) => ({ world_version_id: v.id, version: v.version, status: v.status })) })));

  tool("list_scenarios", "The jobs (scenarios) in a world version, with their split: train and dev are for improving, holdout is for the final score.",
       { world_version_id: z.string() }, async ({ world_version_id }) =>
    (await get().get<Json[]>(`/v1/world-versions/${world_version_id}/scenarios`)).map((s) => ({ id: s.id, slug: s.slug, title: s.spec?.title, split: s.split, status: s.status })));

  tool("recheck_world", "Replay every job of a published world and try each with a live agent; unfair jobs are withdrawn. Costs about $0.03 per job. Ask first.",
       { world_version_id: z.string() }, async ({ world_version_id }) => get().post(`/v1/world-versions/${world_version_id}/validate`, {}));

  // ------------------------------------------------------------------ agents and evaluations

  tool("list_agents", "Agent profiles (versions of an agent: instructions, tool guidance, model).", {}, async () =>
    (await get().get<Json[]>("/v1/agent-profiles")).map((p) => ({ id: p.id, name: p.name, version: p.version, driver: p.spec?.driver ?? "llm", created_by: p.created_by })));

  tool("create_agent", "Create an agent profile. instructions is its system prompt (empty uses the platform default). With " +
       "bring_your_own=True, Rehearsal does not run a model for it: your own agent acts through waiting_turns and take_action.",
       { name: z.string(), instructions: z.string().default(""), model: z.string().optional(), bring_your_own: z.boolean().default(false) },
       async ({ name, instructions, model, bring_your_own }) => {
    const p = await get().post("/v1/agent-profiles", { name, system_prompt: instructions, model: model ?? null, driver: bring_your_own ? "external" : "llm" });
    return { id: p.id, name: p.name, version: p.version };
  });

  tool("run_evaluation", "Run agents through the jobs of a published world version. By default every job (train, dev, holdout) is run " +
       "twice, with the default stress layer on. Narrow it with splits (any of train, dev, holdout) and repeats. " +
       "Spends model money (about $0.02 per episode). Ask the user first.",
       { world_version_id: z.string(), agent_ids: z.array(z.string()), splits: z.array(z.string()).optional(), repeats: z.number().int().optional(), budget_usd: z.number().optional() },
       async ({ world_version_id, agent_ids, splits, repeats, budget_usd }) => {
    const r = await get().post("/v1/evaluations", { world_version_id, profile_ids: agent_ids, ...(splits?.length ? { splits } : {}),
                                                    ...(repeats ? { repeats } : {}), ...(budget_usd ? { budget_usd } : {}) });
    return { ...r, watch: link(`/app/run/?id=${r.run_id}`) };
  });

  tool("run_results", "Status and scores of an evaluation run, one line per episode, and why episodes failed: named causes per " +
       "agent with their usual fix. Start from the causes when explaining a run.", { run_id: z.string() }, async ({ run_id }) => {
    const c = get();
    const run = await c.get(`/v1/runs/${run_id}`);
    const episodes: Json[] = await c.get(`/v1/runs/${run_id}/episodes`);
    const failures: Json = await c.get(`/v1/runs/${run_id}/failures`);
    const causes = Object.fromEntries(Object.entries<Json>(failures).map(([agent, v]) => [agent, v.causes.map((x: Json) => ({ label: x.label, count: x.count, fix: x.fix, episodes: x.episodes }))]));
    return { status: run.status, summary: run.summary?.profiles ?? null, failure_causes: causes,
             episodes: episodes.map((e) => ({ id: e.id, split: e.split, scenario: e.scenario, status: e.status, verified: e.reward === 1, ending: e.termination })),
             console: link(`/app/run/?id=${run_id}`) };
  });

  tool("episode_details", "What happened in one episode: the request and its revisions, every action with its result, and which checks failed.",
       { episode_id: z.string() }, async ({ episode_id }) => {
    const e = await get().get(`/v1/episodes/${episode_id}`);
    const oracle = e.oracle ?? {};
    return {
      scenario: e.scenario?.title, goals: e.scenario?.goals, status: e.status, ending: e.termination,
      verified: e.reward === 1, environment_error: oracle.environment_error,
      failed_checks: (oracle.check_results ?? []).filter((x: Json) => !x.passed).map((x: Json) => ({ check: x.description, observed: x.actual, wanted: `${x.op} ${x.expected}` })),
      duplicate_effects: oracle.duplicate_effects, false_completion: oracle.false_completion,
      actions: (e.actions ?? []).map((a: Json) => `${a.actor}: ${a.tool}(${short(a.args, 160)}) -> ${a.status}${a.fault ? " [" + a.fault + "]" : ""}`),
      messages: (e.messages ?? []).map((m: Json) => `${m.sender}: ${short(m.text, 300)}`).slice(-30),
      console: link(`/app/run/?id=${e.run_id}&episode=${episode_id}`),
    };
  });

  tool("improve_agent", "Propose the next version of an agent from its failed train and dev episodes in a run. Ask first. Then " +
       "evaluate both versions on the holdout split and compare_runs before keeping the new one.",
       { agent_id: z.string(), run_id: z.string() }, async ({ agent_id, run_id }) => get().post("/v1/improvements", { profile_id: agent_id, run_id }));

  tool("make_agent", "Agent Factory: write a new agent for a published world, rehearse it, harden it with the fix loop, prove it on " +
       "held-out jobs, and package it as a zip (a runnable agent on Nemotron that calls the application's API, plus a proof " +
       "report). Spends money: say the episode count and ask first. Follow it with job_status; the result has artifact_id.",
       { world_version_id: z.string(), name: z.string().default(""), rounds: z.number().int().default(3), repeats: z.number().int().default(1) },
       async ({ world_version_id, name, rounds, repeats }) => {
    const res = await get().post("/v1/factory", { world_version_id, name, rounds, repeats });
    return { ...res, console: link(`/app/fix/?job=${res.job_id}`) };
  });

  tool("fix_agent", "Fix an agent end to end: each round proposes a new version from failed train and dev episodes, rehearses it, " +
       "and keeps it only if it verifies more episodes without new rule violations. The best version is then compared " +
       "with the original on held-out jobs. Spends money from the allowance: say the episode count and ask first. " +
       "Follow it with job_status; the finished job's result lists every round and the held-out comparison.",
       { agent_id: z.string(), run_id: z.string(), rounds: z.number().int().default(3), repeats: z.number().int().default(1) },
       async ({ agent_id, run_id, rounds, repeats }) => {
    const res = await get().post("/v1/autofix", { profile_id: agent_id, run_id, rounds, repeats });
    return { ...res, console: link(`/app/fix/?job=${res.job_id}`) };
  });

  tool("compare_runs", "Compare agents within one run, or two runs on the same world version.",
       { run_a: z.string(), run_b: z.string().optional() }, async ({ run_a, run_b }) => get().get("/v1/compare", { run_a, ...(run_b ? { run_b } : {}) }));

  // ------------------------------------------------------------------ bring your own agent

  tool("waiting_turns", "For a run of a bring-your-own agent: episodes waiting for your next action. Each has the actor you play, " +
       "the new messages since your last action, and the tools you may call. Waits up to wait_s for a turn.",
       { run_id: z.string(), wait_s: z.number().int().default(30) }, async ({ run_id, wait_s }) => {
    const c = get();
    const deadline = Date.now() + Math.max(0, Math.min(wait_s, 120)) * 1000;
    for (;;) {
      const out: Json[] = [];
      for (const e of await c.get<Json[]>(`/v1/runs/${run_id}/episodes`)) {
        if (e.status !== "running") continue;
        const obs = await c.get(`/v1/episodes/${e.id}/observation`);
        if (obs.awaiting_action) {
          const data = obs.turn.data;
          out.push({ episode_id: e.id, actor: data.actor, new_messages: data.new ?? [],
                     tools: (data.tools ?? []).map((t: Json) => ({ name: t.function.name, description: short(t.function.description, 400), parameters: t.function.parameters })) });
        }
      }
      if (out.length || Date.now() >= deadline) return out;
      await sleep(2000);
    }
  });

  tool("take_action", "Act in an episode as the actor named by waiting_turns, with one of the tools it offered. Returns the tool's result.",
       { episode_id: z.string(), actor: z.string(), tool: z.string(), arguments: z.record(z.string(), z.any()).optional() },
       async ({ episode_id, actor, tool: name, arguments: args }) => get().external.act(episode_id, actor, name, args ?? {}, randomUUID().replace(/-/g, ""), 90));

  return mcp;
}

export async function main(): Promise<void> {
  await buildServer().connect(new StdioServerTransport()); // stdio
}
