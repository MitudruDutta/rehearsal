/**
 * TypeScript client for Rehearsal. It mirrors the Python SDK (`rehearsal-kit` on PyPI): the same resources and
 * methods, in camelCase. It uses the platform's fetch, so it runs in Node 18+, Deno, Bun and browsers.
 *
 *   const rh = new Rehearsal();                       // REHEARSAL_API_KEY and REHEARSAL_URL, or options
 *   const job = await rh.worlds.makeAgent(worldVersionId, { name: "support-agent" });
 *   for await (const ev of rh.jobs.events(job.job_id)) console.log(ev.type, ev.summary);
 */

export const DEFAULT_URL = "https://rehearsalkit.xyz";

// API payloads are documented in the server's OpenAPI reference (/api/docs); results are plain JSON objects.
export type Json = Record<string, any>;
export type Command = "pause" | "resume" | "stop" | "retry";
export type Split = "train" | "dev" | "holdout";

export interface Options {
  apiKey?: string;
  baseUrl?: string;
  /** Milliseconds before a request is abandoned. Default 60 000. Streams have no timeout. */
  timeoutMs?: number;
  fetch?: typeof fetch;
}

export class RehearsalError extends Error {
  constructor(readonly status: number, readonly detail: unknown) {
    super(`HTTP ${status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
    this.name = "RehearsalError";
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function env(name: string): string | undefined {
  const value = (globalThis as any).process?.env?.[name];
  // an empty or unexpanded variable (an unset plugin option such as ${REHEARSAL_API_KEY}) counts as unset
  return value && !String(value).startsWith("${") ? String(value) : undefined;
}

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
    const key = options.apiKey ?? env("REHEARSAL_API_KEY");
    if (!key) throw new Error("no Rehearsal API key: pass { apiKey } or set REHEARSAL_API_KEY");
    this.apiKey = key;
    this.baseUrl = (options.baseUrl ?? env("REHEARSAL_URL") ?? DEFAULT_URL).replace(/\/+$/, "");
    this.timeoutMs = options.timeoutMs ?? 60_000;
    this.fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  async request<T = any>(method: string, path: string, body?: unknown, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
    const url = new URL(this.baseUrl + path);
    for (const [k, v] of Object.entries(params ?? {})) if (v !== undefined) url.searchParams.set(k, String(v));
    const resp = await this.fetcher(url, {
      method,
      headers: { Authorization: `Bearer ${this.apiKey}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (resp.status >= 400) {
      const text = await resp.text();
      let detail: unknown = text.slice(0, 300); // an HTML error page says nothing useful past this
      try {
        const parsed = JSON.parse(text);
        detail = parsed && typeof parsed === "object" && "detail" in parsed ? parsed.detail : parsed;
      } catch { /* not JSON */ }
      throw new RehearsalError(resp.status, detail);
    }
    return (await resp.json()) as T;
  }

  get<T = any>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
    return this.request<T>("GET", path, undefined, params);
  }

  post<T = any>(path: string, body: unknown = {}): Promise<T> {
    return this.request<T>("POST", path, body);
  }

  /** Server-sent events, reconnecting from the last event id after a dropped connection, until the stream ends. */
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
          reader.cancel().catch(() => {}); // a caller that stops early must not leave the connection open
        }
      } catch (err) {
        if (err instanceof RehearsalError) throw err; // an HTTP error is an answer, not a dropped connection
      }
      await sleep(1000);
    }
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
}

export class Worlds extends Resource {
  build(applicationId: string, options: Json = {}): Promise<Json> {
    return this.c.post("/v1/world-builds", { application_id: applicationId, ...options });
  }
  /** Agent Factory: draft an agent from the world, harden it with the fix loop, prove it on held-out jobs, package it. */
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
  command(jobId: string, command: Command): Promise<Json> { return this.c.post(`/v1/jobs/${jobId}/commands`, { command }); }
  events(jobId: string, cursor = 0): AsyncGenerator<Json> { return this.c.stream(`/v1/jobs/${jobId}/events`, cursor); }
  /** Polls until the job has succeeded, failed or been cancelled. */
  async wait(jobId: string, options: { timeoutMs?: number; pollMs?: number } = {}): Promise<Json> {
    const deadline = Date.now() + (options.timeoutMs ?? 6 * 3600_000);
    while (Date.now() < deadline) {
      const job = await this.get(jobId);
      if (["succeeded", "failed", "cancelled"].includes(job.status)) return job;
      await sleep(options.pollMs ?? 3000);
    }
    throw new Error(`job ${jobId} did not finish in time`);
  }
}

export class Profiles extends Resource {
  create(name: string, systemPrompt = "", fields: Json = {}): Promise<Json> {
    return this.c.post("/v1/agent-profiles", { name, system_prompt: systemPrompt, ...fields });
  }
  list(): Promise<Json[]> { return this.c.get("/v1/agent-profiles"); }
  /** The fix loop: rounds of propose and rehearse, keeping only versions that verify more, proved on held-out jobs. */
  autofix(profileId: string, runId: string, options: { rounds?: number; repeats?: number } = {}): Promise<Json> {
    return this.c.post("/v1/autofix", { profile_id: profileId, run_id: runId, rounds: options.rounds ?? 3, repeats: options.repeats ?? 1 });
  }
}

export class Evaluations extends Resource {
  /** Without splits or repeats, the server runs every job twice with the default stress layer on. */
  create(worldVersionId: string, profileIds: string[], options: { splits?: Split[]; repeats?: number } & Json = {}): Promise<Json> {
    const { splits, repeats, ...fields } = options;
    return this.c.post("/v1/evaluations", { world_version_id: worldVersionId, profile_ids: profileIds, ...(splits?.length ? { splits } : {}), ...(repeats ? { repeats } : {}), ...fields });
  }
  compare(runA: string, runB?: string): Promise<Json> { return this.c.get("/v1/compare", { run_a: runA, run_b: runB }); }
}

export class Runs extends Resource {
  get(runId: string): Promise<Json> { return this.c.get(`/v1/runs/${runId}`); }
  episodes(runId: string): Promise<Json[]> { return this.c.get(`/v1/runs/${runId}/episodes`); }
  /** Why episodes failed, per agent: named causes with counts, usual fixes and example episodes. */
  failures(runId: string): Promise<Json> { return this.c.get(`/v1/runs/${runId}/failures`); }
  episode(episodeId: string): Promise<Json> { return this.c.get(`/v1/episodes/${episodeId}`); }
  events(runId: string, cursor = 0): AsyncGenerator<Json> { return this.c.stream(`/v1/runs/${runId}/events`, cursor); }
  intervene(episodeId: string, body: Json): Promise<Json> { return this.c.post(`/v1/episodes/${episodeId}/interventions`, body); }
  command(runId: string, command: Command): Promise<Json> { return this.c.post(`/v1/runs/${runId}/commands`, { command }); }
}

/** Drive an episode whose profile uses driver "external": your own agent, in your own code. */
export class ExternalAgent extends Resource {
  observation(episodeId: string): Promise<Json> { return this.c.get(`/v1/episodes/${episodeId}/observation`); }
  async act(episodeId: string, actor: string, tool: string, args: Json, idempotencyKey: string, waitMs = 120_000): Promise<Json> {
    await this.c.post(`/v1/episodes/${episodeId}/actions`, { actor, tool, args, idempotency_key: idempotencyKey });
    const deadline = Date.now() + waitMs;
    while (Date.now() < deadline) {
      const r = await this.c.get(`/v1/episodes/${episodeId}/actions/${idempotencyKey}`);
      if (r.status === "done") return r.result;
      await sleep(500);
    }
    throw new Error("action result not available yet; query again with the same idempotency key");
  }
}
