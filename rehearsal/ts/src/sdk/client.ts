/**
 * TypeScript client for the Rehearsal API, the mirror of rehearsal/sdk/client.py.
 *
 *     import { Rehearsal } from "rehearsal-kit";
 *     const client = new Rehearsal(); // REHEARSAL_API_KEY and REHEARSAL_URL, else what `rehearsal login` saved
 *     const build = await client.worlds.build(applicationId);
 *     const job = await client.jobs.wait(build.job_id);
 */

import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join } from "node:path";

/** This package's version, from its package.json (kept equal to the Python package's by the release checks). */
export const VERSION: string = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8")).version;

export const DEFAULT_URL = "https://rehearsalkit.xyz"; // the hosted service; a server of your own: `rehearsal login --url ...` or REHEARSAL_URL

// API payloads are documented in the server's OpenAPI reference (/api/docs); results are plain JSON objects.
export type Json = Record<string, any>;
export type Command = "pause" | "resume" | "stop" | "retry";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Where `rehearsal login` keeps the server URL and API key (readable by this user only). Shared with the Python CLI. */
export function configPath(): string {
  const configured = process.env.REHEARSAL_CONFIG;
  return configured ? configured.replace(/^~(?=$|\/)/, homedir()) : join(homedir(), ".config", "rehearsal", "config.json");
}

export function savedLogin(): Record<string, string> {
  try {
    const data = JSON.parse(readFileSync(configPath(), "utf8"));
    return data && typeof data === "object" && !Array.isArray(data) ? data : {};
  } catch {
    return {};
  }
}

/** An environment value, ignoring an agent client's placeholder it did not expand (such as ${user_config.api_key}). */
export function env(name: string): string | undefined {
  const value = (process.env[name] ?? "").trim();
  return !value || value.startsWith("${") ? undefined : value;
}

export function saveLogin(url: string, apiKey: string): string {
  const path = configPath();
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const tmp = `${path}.tmp`;
  writeFileSync(tmp, JSON.stringify({ url: url.replace(/\/+$/, ""), api_key: apiKey }, null, 2), { mode: 0o600 });
  renameSync(tmp, path);
  return path;
}

export class RehearsalError extends Error {
  constructor(readonly status: number, readonly detail: unknown) {
    super(`HTTP ${status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
    this.name = "RehearsalError";
  }
}

class Resource {
  constructor(protected readonly c: Rehearsal) {}
}

export class Applications extends Resource {
  create(name: string, source: Json, images: Record<string, string> = {}, policies = ""): Promise<Json> {
    return this.c.post("/v1/applications", { name, source, images, policies });
  }
  importCatalog(): Promise<Json[]> { return this.c.post("/v1/applications/import-catalog", {}); }
  list(): Promise<Json[]> { return this.c.get("/v1/applications"); }
  get(appId: string): Promise<Json> { return this.c.get(`/v1/applications/${appId}`); }
  uploadSource(appId: string, archive: string): Promise<Json> {
    const form = new FormData();
    form.append("file", new Blob([new Uint8Array(readFileSync(archive))], { type: "application/gzip" }), basename(archive));
    return this.c.request("POST", `/v1/applications/${appId}/source`, { form });
  }
}

export class Worlds extends Resource {
  build(applicationId: string, options: Json = {}): Promise<Json> {
    return this.c.post("/v1/world-builds", { application_id: applicationId, ...options });
  }
  /** Agent Factory: drafts an agent from the world, hardens it with the fix loop and proves it on held-out jobs.
   * The finished job's result has every score and `artifact_id`, a zip with a runnable agent and its proof report. */
  makeAgent(worldVersionId: string, options: { name?: string; rounds?: number; repeats?: number } = {}): Promise<Json> {
    return this.c.post("/v1/factory", { world_version_id: worldVersionId, name: options.name ?? "", rounds: options.rounds ?? 3, repeats: options.repeats ?? 1 });
  }
  list(): Promise<Json[]> { return this.c.get("/v1/worlds"); }
  version(wvId: string): Promise<Json> { return this.c.get(`/v1/world-versions/${wvId}`); }
  scenarios(wvId: string): Promise<Json[]> { return this.c.get(`/v1/world-versions/${wvId}/scenarios`); }
  validate(wvId: string): Promise<Json> { return this.c.post(`/v1/world-versions/${wvId}/validate`, {}); }
  bundle(wvId: string, includeImages = false): Promise<Json> {
    return this.c.post(`/v1/world-versions/${wvId}/bundle?include_images=${includeImages}`, {});
  }
}

export class Jobs extends Resource {
  get(jobId: string): Promise<Json> { return this.c.get(`/v1/jobs/${jobId}`); }
  command(jobId: string, command: Command | string): Promise<Json> { return this.c.post(`/v1/jobs/${jobId}/commands`, { command }); }
  events(jobId: string, cursor = 0): AsyncGenerator<Json> { return this.c.stream(`/v1/jobs/${jobId}/events`, cursor); }
  async wait(jobId: string, options: { timeoutS?: number; pollS?: number } = {}): Promise<Json> {
    const timeoutS = options.timeoutS ?? 6 * 3600;
    const deadline = Date.now() + timeoutS * 1000;
    while (Date.now() < deadline) {
      const job = await this.get(jobId);
      if (["succeeded", "failed", "cancelled"].includes(job.status)) return job;
      await sleep((options.pollS ?? 3) * 1000);
    }
    throw new Error(`job ${jobId} did not finish within ${timeoutS} seconds`);
  }
}

export class Profiles extends Resource {
  create(name: string, systemPrompt = "", fields: Json = {}): Promise<Json> {
    return this.c.post("/v1/agent-profiles", { name, system_prompt: systemPrompt, ...fields });
  }
  list(): Promise<Json[]> { return this.c.get("/v1/agent-profiles"); }
  /** Starts the fix loop: propose a version, rehearse it on train and dev, keep it only if it verifies more, and
   * prove the best one against the original on held-out jobs. Returns the job; its result has every round. */
  autofix(profileId: string, runId: string, options: { rounds?: number; repeats?: number } = {}): Promise<Json> {
    return this.c.post("/v1/autofix", { profile_id: profileId, run_id: runId, rounds: options.rounds ?? 3, repeats: options.repeats ?? 1 });
  }
}

export class Evaluations extends Resource {
  /** Without splits or repeats, the server runs every job twice with the default stress layer on. */
  create(worldVersionId: string, profileIds: string[], splits?: string[] | null, repeats?: number | null, fields: Json = {}): Promise<Json> {
    return this.c.post("/v1/evaluations", { world_version_id: worldVersionId, profile_ids: profileIds, ...(splits?.length ? { splits } : {}), ...(repeats ? { repeats } : {}), ...fields });
  }
  compare(runA: string, runB?: string | null): Promise<Json> {
    return this.c.get("/v1/compare", { run_a: runA, ...(runB ? { run_b: runB } : {}) });
  }
}

export class Runs extends Resource {
  get(runId: string): Promise<Json> { return this.c.get(`/v1/runs/${runId}`); }
  episodes(runId: string): Promise<Json[]> { return this.c.get(`/v1/runs/${runId}/episodes`); }
  /** Why episodes failed, per agent: named causes, each with its count, its usual fix and example episodes. */
  failures(runId: string): Promise<Json> { return this.c.get(`/v1/runs/${runId}/failures`); }
  episode(epId: string): Promise<Json> { return this.c.get(`/v1/episodes/${epId}`); }
  events(runId: string, cursor = 0): AsyncGenerator<Json> { return this.c.stream(`/v1/runs/${runId}/events`, cursor); }
  intervene(epId: string, body: Json): Promise<Json> { return this.c.post(`/v1/episodes/${epId}/interventions`, body); }
  command(runId: string, command: Command | string): Promise<Json> { return this.c.post(`/v1/runs/${runId}/commands`, { command }); }
}

/** Drive an episode whose profile uses driver="external". */
export class ExternalAgent extends Resource {
  observation(epId: string): Promise<Json> { return this.c.get(`/v1/episodes/${epId}/observation`); }
  async act(epId: string, actor: string, tool: string, args: Json, idempotencyKey: string, waitS = 120): Promise<Json> {
    await this.c.post(`/v1/episodes/${epId}/actions`, { actor, tool, args, idempotency_key: idempotencyKey });
    const deadline = Date.now() + waitS * 1000;
    while (Date.now() < deadline) {
      const r = await this.c.get(`/v1/episodes/${epId}/actions/${idempotencyKey}`);
      if (r.status === "done") return r.result;
      await sleep(500);
    }
    throw new Error("action result not available yet; query again with the same idempotency key");
  }
}

export interface Options {
  apiKey?: string;
  baseUrl?: string;
  /** Seconds before a request is abandoned. Default 60. Streams have no timeout. */
  timeout?: number;
  fetch?: typeof fetch;
}

type Params = Record<string, string | number | boolean | null | undefined>;

export class Rehearsal {
  readonly apiKey: string;
  readonly baseUrl: string;
  readonly applications = new Applications(this);
  readonly worlds = new Worlds(this);
  readonly jobs = new Jobs(this);
  readonly profiles = new Profiles(this);
  readonly evaluations = new Evaluations(this);
  readonly runs = new Runs(this);
  readonly external = new ExternalAgent(this);
  private readonly timeoutMs: number;
  private readonly fetcher: typeof fetch;

  constructor(options: Options = {}) {
    const login = savedLogin(); // environment wins; an empty or unexpanded variable (an unset plugin option) counts as unset
    const key = options.apiKey || env("REHEARSAL_API_KEY") || login.api_key;
    if (!key) throw new Error("no Rehearsal API key: run `rehearsal login`, or set REHEARSAL_API_KEY");
    this.apiKey = key;
    this.baseUrl = (options.baseUrl || env("REHEARSAL_URL") || login.url || DEFAULT_URL).replace(/\/+$/, "");
    this.timeoutMs = (options.timeout ?? 60) * 1000;
    this.fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  async request<T = any>(method: string, path: string, init: { json?: unknown; params?: Params; form?: FormData } = {}): Promise<T> {
    const url = new URL(this.baseUrl + path);
    for (const [k, v] of Object.entries(init.params ?? {})) if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    const headers: Record<string, string> = { Authorization: `Bearer ${this.apiKey}` };
    let body: BodyInit | undefined;
    if (init.form) body = init.form;
    else if (init.json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(init.json); }
    const resp = await this.fetcher(url, { method, headers, body, signal: AbortSignal.timeout(this.timeoutMs) });
    if (resp.status >= 400) {
      const text = await resp.text();
      let detail: unknown = text.slice(0, 300); // an HTML error page says nothing useful past this
      try {
        const parsed = JSON.parse(text);
        detail = parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed.detail : parsed;
      } catch { /* not JSON */ }
      throw new RehearsalError(resp.status, detail);
    }
    return (await resp.json()) as T;
  }

  get<T = any>(path: string, params?: Params): Promise<T> { return this.request<T>("GET", path, { params }); }

  post<T = any>(path: string, body: unknown): Promise<T> { return this.request<T>("POST", path, { json: body }); }

  /** Downloads a binary response (an artifact) and returns its bytes. */
  async download(path: string): Promise<Uint8Array> {
    const resp = await this.fetcher(this.baseUrl + path, { headers: { Authorization: `Bearer ${this.apiKey}` } });
    if (resp.status >= 400) throw new RehearsalError(resp.status, (await resp.text()).slice(0, 300));
    return new Uint8Array(await resp.arrayBuffer());
  }

  /** Server-sent events with automatic reconnect from the last event id. Leaving the loop early closes the connection. */
  async *stream(path: string, cursor = 0): AsyncGenerator<Json> {
    for (;;) {
      try {
        const resp = await this.fetcher(`${this.baseUrl}${path}?cursor=${cursor}`, { headers: { Authorization: `Bearer ${this.apiKey}` } });
        if (resp.status >= 400) throw new RehearsalError(resp.status, (await resp.text()).slice(0, 500));
        const reader = resp.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = "", event: string | null = null, data: string[] = [];
        try {
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let nl: number;
            while ((nl = buffer.indexOf("\n")) >= 0) {
              const line = buffer.slice(0, nl).replace(/\r$/, "");
              buffer = buffer.slice(nl + 1);
              if (line.startsWith("event:")) event = line.slice(6).trim();
              else if (line.startsWith("data:")) data.push(line.slice(5).trim());
              else if (line === "") {
                if (event === "stream.end") return;
                if (data.length) {
                  const payload = JSON.parse(data.join("\n"));
                  cursor = payload.event_id ?? cursor;
                  yield payload;
                }
                event = null;
                data = [];
              }
            }
          }
        } finally {
          reader.cancel().catch(() => {});
        }
      } catch (err) {
        if (err instanceof RehearsalError) throw err; // an HTTP error is an answer, not a dropped connection
      }
      await sleep(1000);
    }
  }
}
