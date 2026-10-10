import type { RhEvent } from "./api";
import { explainProblem } from "./problems";

/** Plain-English descriptions of recorded events, for people rather than parsers. */

export function humanTool(name: string): string {
  const s = name.replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function quote(text: unknown, n = 140) {
  const t = String(text ?? "").trim();
  return `"${t.length > n ? t.slice(0, n - 1) + "…" : t}"`;
}

function role(ev: RhEvent) {
  const r = ev.actor_id || ev.data?.role;
  return r ? String(r).replace(/_/g, " ") : "";
}

const COMPILER_TOOL: Record<string, ((a: any) => string) | undefined> = {
  read_file: (a) => `read ${a.path}${a.start ? ` (lines ${a.start}-${a.end ?? "end"})` : ""}`,
  grep: (a) => `searched the source for ${quote(a.pattern, 60)}${a.glob && a.glob !== "*" ? ` in ${a.glob}` : ""}`,
  find: (a) => `looked for files named ${a.name_glob}`,
  list_dir: (a) => `listed ${a.path || "the repository root"}`,
  inspect_image: () => "inspected a container image's defaults",
  http_request: (a) => `called ${a.method || "GET"} ${a.path} on ${a.service}`,
  call_as_role: (a) => `called ${a.method || "GET"} ${a.path} as ${a.role}`,
  exec_command: (a) => `ran a command in ${a.service}`,
  sql_query: () => "queried the application database (read-only)",
  list_tables: () => "listed the database tables",
  describe_table: (a) => `looked at the columns of ${a.table}`,
  service_logs: (a) => `read the ${a.service} logs`,
  api_search: (a) => `searched the API for ${quote(a.query, 60)}`,
  api_operation: (a) => `opened API operation ${a.op_id}`,
  graphql_search: (a) => `searched the GraphQL schema for ${quote(a.query, 60)}`,
  graphql_type: (a) => `opened GraphQL type ${a.name}`,
  submit_scenario: () => "submitted a scenario for checking",
  list_secrets: () => "listed the generated sandbox secrets",
  get_secret: (a) => `read sandbox secret ${a.name}`,
};

/** Older events stored only "tool({json...})"; recover simple string fields from it. */
function argsFromSummary(summary: string): Record<string, string> | null {
  const out: Record<string, string> = {};
  for (const m of summary.matchAll(/"(\w+)":\s*"((?:[^"\\]|\\.)*)"/g)) out[m[1]] = m[2];
  return Object.keys(out).length ? out : null;
}

/** Who an event is about, for avatars. */
export function actorOf(ev: RhEvent): string | null {
  if (ev.actor_id) return ev.actor_id;
  if (ev.data?.role) return String(ev.data.role);
  if (ev.type === "customer.message" || ev.type === "goal.revised") return "customer";
  if (ev.type === "episode.finished" || ev.type.startsWith("compiler.validat")) return "verifier";
  return null;
}

export function describe(ev: RhEvent): string {
  try {
    return describeUnsafe(ev);
  } catch {
    return ev.summary; // a malformed or older event must never break the page
  }
}

function describeUnsafe(ev: RhEvent): string {
  const who = role(ev);
  const d = ev.data || {};
  const text = ev.summary.replace(/^[^:]*?->\s*[^:]*?:\s*/, "");
  switch (ev.type) {
    case "compiler.tool": {
      const f = COMPILER_TOOL[d.tool];
      const args = d.args || argsFromSummary(ev.summary);
      return f && args ? `${who} ${f(args)}` : `${who} used ${humanTool(d.tool || "a tool")}`;
    }
    case "compiler.note":
      return `${who}: ${ev.summary}`;
    case "compiler.submit.accepted":
      return `${who}'s work passed the platform's checks`;
    case "compiler.submit.rejected":
      return `${who}'s work was sent back: ${ev.summary}`;
    case "compiler.repair":
      return ev.summary.replace("sandbox start failed", "The application did not start");
    case "compiler.phase.started":
      return `Started: ${ev.summary.replace(" started", "")}`;
    case "compiler.phase.completed":
      return `Finished: ${ev.summary.replace(" completed", "")}`;
    case "customer.message":
      return `Customer: ${quote(text, 220)}`;
    case "agent.reply":
      return `${who} to the customer: ${quote(text, 220)}`;
    case "message.sent":
      return `${who} to ${d.to}: ${quote(text, 200)}`;
    case "notification":
      return text;
    case "agent.decision":
      return `${who}: ${ev.summary}`;
    case "goal.revised":
      return `The customer changed the request (now version ${ev.goal_version}): ${quote(d.instruction || "", 200)}`;
    case "fault.armed":
      return `Scheduled fault: ${ev.summary.replace(/_/g, " ")}`;
    case "fault.injected":
      return `Fault: ${humanTool(ev.summary.split(" on ")[1] || "")} ${ev.summary.startsWith("drop") ? "took effect but its response was dropped" : ev.summary.startsWith("timeout") ? "timed out before it was sent" : "failed"}`;
    case "permission.changed":
      return `Permission change: ${ev.summary}`;
    case "action.succeeded":
    case "action.failed":
    case "action.unknown":
    case "action.rejected": {
      const tool = humanTool(d.tool || ev.summary.split(" ")[0]);
      const status = ev.summary.split("-> ")[1] || "";
      const outcome = {
        "action.succeeded": `done${status ? ` (HTTP ${status})` : ""}`,
        "action.failed": `failed${status ? ` (HTTP ${status})` : ""}`,
        "action.unknown": "no response, so the outcome is unknown",
        "action.rejected": `blocked by the gateway: ${ev.summary.split(": ").slice(1).join(": ") || "not permitted"}`,
      }[ev.type];
      const stale = d.observed_goal_version && ev.goal_version && d.observed_goal_version < ev.goal_version ? " (it had not yet seen the latest request)" : "";
      return `${who} ${tool}: ${outcome}${stale}`;
    }
    case "episode.started":
      return `Episode started: ${ev.summary}`;
    case "external.turn":
      return `${role(ev) || "The agent"}'s turn: waiting for the agent to choose an action`;
    case "external.action.submitted":
      return `${role(ev) || "The agent"} chose ${humanTool(String(ev.data?.tool ?? "an action")).toLowerCase()}`;
    case "external.action.result":
      return `${role(ev) || "The agent"} got the result of ${humanTool(String(ev.data?.tool ?? "its action")).toLowerCase()}`;
    case "episode.claimed_complete":
      return `${who} says the work is done: ${quote(ev.summary, 160)}`;
    case "episode.finished": {
      const o = d.oracle || {};
      if (o.environment_error || ev.summary.startsWith("environment_error")) return `This episode couldn't run, so it isn't scored. ${explainProblem(o.environment_error || ev.summary)}`;
      const v = (o.hard_constraint_violations || []).length;
      return `Verifier: ${o.goal_satisfied ? "the request is satisfied in the application's own records" : "the request is not satisfied"}${v ? `, ${v} rule${v > 1 ? "s" : ""} broken` : ""}${o.duplicate_effects ? `, ${o.duplicate_effects} duplicate side effect(s)` : ""}`;
    }
    case "episode.resumed":
      return "The worker restarted; the episode resumed where it stopped";
    case "action.held":
      return `${who || "The agent"} was about to ${humanTool(d.tool || "act")} when the customer changed the request; the change was not made`;
    case "environment.error":
      return `Not scored: ${explainProblem(ev.summary)}`;
    case "job.failed":
      return `The job stopped. ${explainProblem(ev.summary)}`;
    case "job.retrying":
      return "A step failed; the job is retrying from its last saved step";
    case "run.finished": {
      const o = ev.data?.overall;
      return o ? `Run finished: ${o.successes} of ${o.finished} episodes verified${o.environment_errors ? `, ${o.environment_errors} not scored` : ""}` : "Run finished";
    }
    case "job.succeeded":
      return "Finished";
    case "validate.sandbox":
      return "Starting a copy of the application";
    case "validate.step":
      return `Checking ${ev.summary.split(":")[0]}`;
    case "validation.result": {
      const [slug, rest = ""] = ev.summary.split(/:(.*)/s);
      return rest.trim() === "valid" ? `${slug}: fair, kept` : `${slug}: withdrawn; a live agent could not pass it for a reason that was not its fault`;
    }
    default:
      return who ? `${who}: ${ev.summary}` : ev.summary;
  }
}
