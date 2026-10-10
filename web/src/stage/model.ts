import type { RhEvent } from "../api";
import { humanTool } from "../describe";

/**
 * Renderer-free state of the rehearsal room, driven only by recorded events.
 * Units are metres on the floor: x runs along the back wall (0..ROOM_W), z runs
 * from the back wall (0) toward the camera (ROOM_D). Nothing moves unless an
 * event says it happened.
 */

export const ROOM_W = 24;
export const ROOM_D = 13;
export const DESK_Z = 1.3;
export const MAX_DESKS = 8;

export type Tone = "go" | "stop" | "cue" | "plain";
export type DeskKind = "desk" | "books" | "rack" | "cabinet" | "board" | "images";

export interface Actor {
  id: string;
  label: string;
  kind: "agent" | "customer" | "verifier";
  x: number;
  z: number;
  tx: number;
  tz: number;
  homeX: number;
  homeZ: number;
  facing: number; // radians around Y
  busyUntil: number;
  slot: number; // position among actors sharing a desk
  lift: number; // how many levels this actor's name chip is raised so it clears a neighbour's
  returnAt: number; // walk home after a meeting
  lookAt?: { x: number; z: number; until: number };
  activity: string; // what this actor is doing right now, in a few words
  activityTone: Tone;
  task?: { text: string; from: string };
  bubble?: { text: string; until: number; tone: Tone };
  badge?: { tone: Tone; until: number };
}

export interface Link {
  a: string;
  b: string;
  until: number;
}

export interface Desk {
  id: string;
  label: string;
  x: number;
  kind: DeskKind;
  flash?: { tone: Tone; until: number };
}

export interface Flight {
  fx: number;
  fz: number;
  tx: number;
  tz: number;
  start: number;
  label?: string;
}

// who carries each compiler phase, and what they hand to the next role
const PHASE_ROLE: Record<string, [string, string]> = {
  inspect: ["inspector", "Inspection report"],
  plan: ["builder", "Runtime plan"],
  materialize: ["builder", "Running sandbox"],
  discover: ["builder", "API map"],
  seed: ["seeder", "Fictional data"],
  adapt: ["adapter", "Agent tools"],
  author: ["scenario_designer", "Scenarios"],
  validate: ["verifier", "Validated scenarios"],
  package: ["verifier", "Published world"],
};
const PHASE_NEXT: Record<string, string> = { inspect: "plan", plan: "materialize", materialize: "discover", discover: "seed", seed: "adapt", adapt: "author", author: "validate", validate: "package" };
const SLOT_X = [0, -0.95, 0.95, -1.9, 1.9];
const PERSONAL_SPACE = 0.8;
const CHIP_HALF_SPAN = 2.4; // name chips are about this wide in world units at the default zoom

// seats around the team table at (12, 7.4)
const SEATS: [number, number][] = [[9.6, 6.1], [12, 6.1], [14.4, 6.1], [9.6, 8.7], [12, 8.7], [14.4, 8.7], [7.6, 7.4], [16.4, 7.4]];

const COMPILER_DESKS: [string, DeskKind][] = [
  ["Source", "books"], ["Images", "images"], ["Sandbox", "rack"], ["API", "desk"], ["Database", "cabinet"], ["Scenarios", "board"],
];
export const COMPILER_TOOL_DESK: Record<string, string> = {
  read_file: "Source", grep: "Source", find: "Source", list_dir: "Source", inspect_image: "Images",
  http_request: "Sandbox", exec_command: "Sandbox", service_logs: "Sandbox", call_as_role: "Sandbox", list_secrets: "Sandbox", get_secret: "Sandbox",
  api_search: "API", api_operation: "API", graphql_search: "API", graphql_type: "API",
  sql_query: "Database", list_tables: "Database", describe_table: "Database", submit_scenario: "Scenarios",
};

export function seatOf(i: number): [number, number] {
  return SEATS[i % SEATS.length];
}

/** A few words for what a compiler tool call is doing. */
function activityOf(tool: string, a: Record<string, string>): string {
  const file = (p?: string) => (p ? String(p).split("/").pop() : "");
  switch (tool) {
    case "read_file": return `Reading ${file(a.path)}`;
    case "grep": return `Searching for ${String(a.pattern ?? "").slice(0, 24)}`;
    case "find": return `Finding ${a.name_glob ?? "files"}`;
    case "list_dir": return `Browsing ${file(a.path) || "the repo"}`;
    case "inspect_image": return "Inspecting an image";
    case "http_request": return `${a.method ?? "GET"} ${String(a.path ?? "").slice(0, 28)}`;
    case "call_as_role": return `${a.method ?? "GET"} as ${a.role}`;
    case "exec_command": return `Running a command in ${a.service}`;
    case "sql_query": return "Querying the database";
    case "describe_table": return `Reading table ${a.table}`;
    case "list_tables": return "Listing tables";
    case "service_logs": return `Reading ${a.service} logs`;
    case "api_search": return `Searching the API: ${String(a.query ?? "").slice(0, 22)}`;
    case "api_operation": return `Opening ${a.op_id}`;
    case "graphql_search": return "Searching the GraphQL schema";
    case "submit_scenario": return "Submitting a scenario";
    default: return humanTool(tool);
  }
}

function toneOf(type: string): Tone {
  if (type.endsWith("succeeded") || type === "compiler.submit.accepted") return "go";
  if (type.endsWith("failed") || type.endsWith("rejected")) return "stop";
  return "cue";
}

function sentence(text: string) {
  const plain = text.replace(/[#*`_>|]+/g, " ").replace(/\s+/g, " ").trim();
  const first = plain.match(/^.{12,}?[.!?](\s|$)/)?.[0] ?? plain;
  const t = first.trim();
  return t.length > 140 ? t.slice(0, 137) + "…" : t;
}

export class RoomModel {
  actors = new Map<string, Actor>();
  desks: Desk[] = [];
  flights: Flight[] = [];
  links: Link[] = [];
  banner?: { text: string; until: number; tone: Tone };
  doorOpenUntil = 0;
  version = 0; // bumps when the set of desks changes, so renderers rebuild furniture

  constructor(public mode: "episode" | "compiler") {
    if (mode === "episode") {
      this.actor("customer", "Customer", "customer");
      this.actor("verifier", "Verifier", "verifier");
    } else {
      this.actor("verifier", "Validator", "verifier");
      COMPILER_DESKS.forEach(([name, kind]) => this.desk(name, kind));
    }
  }

  actor(id: string, label: string, kind: Actor["kind"] = "agent"): Actor {
    const found = this.actors.get(id);
    if (found) return found;
    const n = [...this.actors.values()].filter((a) => a.kind === "agent").length;
    let home: [number, number];
    if (kind === "customer") home = [20.6, 2.9];
    else if (kind === "verifier") home = [3.6, 7.6];
    else home = seatOf(n);
    const a: Actor = { id, label, kind, x: home[0], z: home[1], tx: home[0], tz: home[1], homeX: home[0], homeZ: home[1], facing: 0, busyUntil: 0, slot: 0, lift: 0, returnAt: 0, activity: kind === "customer" ? "Waiting at the door" : kind === "verifier" ? "Waiting to check results" : "Waiting for work", activityTone: "plain" };
    a.facing = kind === "agent" ? (home[1] < 7.4 ? 0 : Math.PI) : kind === "customer" ? -Math.PI / 4 : Math.PI / 2;
    this.actors.set(id, a);
    return a;
  }

  desk(id: string, kind: DeskKind = "desk"): Desk {
    let d = this.desks.find((x) => x.id === id);
    if (d) return d;
    if (this.desks.length >= MAX_DESKS) return this.desks[this.desks.length - 1];
    d = { id, label: this.mode === "episode" ? humanTool(id) : id, x: 0, kind };
    this.desks.push(d);
    const span = 15.5;
    this.desks.forEach((desk, i) => {
      desk.x = 3.2 + (span / this.desks.length) * (i + 0.5);
    });
    this.version++;
    return d;
  }

  say(a: Actor, text: string, tone: Tone, now: number, ms = 4500) {
    a.bubble = { text: sentence(text), until: now + ms, tone };
  }

  goTo(a: Actor, d: Desk, now: number) {
    // share the desk: each visitor takes a free slot beside it
    const taken = new Set<number>();
    this.actors.forEach((o) => {
      if (o !== a && Math.abs(o.tz - (DESK_Z + 1.1)) < 0.01 && Math.abs(o.tx - d.x) < 2) taken.add(Math.round((o.tx - d.x) / 0.95));
    });
    const slot = [0, -1, 1, -2, 2].find((k) => !taken.has(k)) ?? 0;
    a.slot = Math.abs(slot);
    a.tx = d.x + SLOT_X[[0, -1, 1, -2, 2].indexOf(slot)];
    a.tz = DESK_Z + 1.1;
    a.busyUntil = now + 1800;
    a.returnAt = 0;
    if (a.task) a.task = undefined; // acting on a delegated task completes the hand-off
  }

  home(a: Actor) {
    a.tx = a.homeX;
    a.tz = a.homeZ;
    a.slot = 0;
  }

  /** a walks over to b, they face each other, and a link shows the exchange. */
  meet(a: Actor, b: Actor, now: number, ms = 2600) {
    const dx = a.x - b.x;
    const dz = a.z - b.z;
    const d = Math.hypot(dx, dz) || 1;
    a.tx = b.x + (dx / d) * 1.05;
    a.tz = b.z + (dz / d) * 1.05;
    a.returnAt = now + ms + 1200;
    a.lookAt = { x: b.x, z: b.z, until: now + ms + 1200 };
    b.lookAt = { x: a.tx, z: a.tz, until: now + ms + 1200 };
    this.links.push({ a: a.id, b: b.id, until: now + ms + 600 });
  }

  apply(ev: RhEvent, now: number) {
    const t = ev.type;
    const d = ev.data || {};
    if (this.mode === "compiler") {
      const roleName: string | undefined = d.role;
      const a = roleName ? this.actor(roleName, roleName.replace(/_/g, " ")) : undefined;
      if (t === "compiler.tool" && a) {
        const desk = this.desk(COMPILER_TOOL_DESK[d.tool] ?? "Sandbox");
        if (a.task) a.task = undefined;
        a.activity = activityOf(d.tool, d.args || {});
        a.activityTone = "plain";
        this.goTo(a, desk, now);
        desk.flash = { tone: "plain", until: now + 900 };
      } else if (t === "compiler.note" && a) {
        this.say(a, ev.summary, "plain", now);
      } else if ((t === "compiler.submit.accepted" || t === "compiler.submit.rejected") && a) {
        a.activity = t.endsWith("accepted") ? "Work accepted" : "Fixing rejected work";
        a.activityTone = t.endsWith("accepted") ? "go" : "stop";
        a.badge = { tone: toneOf(t), until: now + 3500 };
        this.home(a);
      } else if (t === "compiler.validation" || t === "compiler.validate") {
        const v = this.actors.get("verifier")!;
        this.goTo(v, this.desk("Scenarios"), now);
        if (t === "compiler.validation") v.badge = { tone: d.ok ? "go" : "stop", until: now + 3500 };
      } else if (t === "compiler.phase.completed" && PHASE_ROLE[d.phase]) {
        const [fromRole, artifact] = PHASE_ROLE[d.phase];
        const next = PHASE_NEXT[d.phase];
        const done = this.actors.get(fromRole);
        if (done) {
          done.activity = `Handed over: ${artifact}`;
          done.activityTone = "go";
        }
        const from = this.actor(fromRole, fromRole === "verifier" ? "Validator" : fromRole.replace(/_/g, " "), fromRole === "verifier" ? "verifier" : "agent");
        this.home(from);
        if (next) {
          const [toRole] = PHASE_ROLE[next];
          if (toRole !== fromRole) {
            const to = this.actor(toRole, toRole === "verifier" ? "Validator" : toRole.replace(/_/g, " "), toRole === "verifier" ? "verifier" : "agent");
            this.flights.push({ fx: from.x, fz: from.z, tx: to.x, tz: to.z, start: now, label: artifact });
            this.links.push({ a: from.id, b: to.id, until: now + 2600 });
            to.task = { text: artifact, from: from.label };
            to.activity = `Received: ${artifact}`;
            to.activityTone = "cue";
            to.badge = { tone: "plain", until: now + 2000 };
          }
        }
      } else if (t === "compiler.repair") {
        this.banner = { text: "The application did not start, so the builder is repairing it", until: now + 4000, tone: "cue" };
        this.desk("Sandbox").flash = { tone: "cue", until: now + 3000 };
      } else if (t === "world.published") {
        this.banner = { text: "World published", until: now + 600_000, tone: "go" };
      }
      return;
    }
    if (t.startsWith("action.") && ev.actor_id) {
      const a = this.actor(ev.actor_id, ev.actor_id);
      const tool = d.tool ?? ev.summary.split(" ")[0];
      const desk = this.desk(tool);
      this.goTo(a, desk, now);
      a.badge = { tone: toneOf(t), until: now + 3000 };
      a.activity = `${humanTool(tool)}: ${t === "action.succeeded" ? "done" : t === "action.unknown" ? "no response" : t === "action.rejected" ? "blocked" : "failed"}`;
      a.activityTone = toneOf(t);
      desk.flash = { tone: toneOf(t), until: now + 1600 };
    } else if (t === "customer.message" || t === "notification") {
      const c = this.actors.get("customer")!;
      this.say(c, ev.summary.replace(/^.*?:\s/, ""), "plain", now, 6000);
      this.doorOpenUntil = now + 2500;
      const to = d.to ? this.actors.get(d.to) : undefined;
      if (to) {
        this.flights.push({ fx: c.x, fz: c.z, tx: to.x, tz: to.z, start: now });
        this.links.push({ a: c.id, b: to.id, until: now + 3000 });
        to.lookAt = { x: c.x, z: c.z, until: now + 3500 };
      }
    } else if (t === "agent.reply" && ev.actor_id) {
      const a = this.actor(ev.actor_id, ev.actor_id);
      this.say(a, ev.summary.replace(/^.*?:\s/, ""), "plain", now);
      a.activity = "Replying to the customer";
      a.activityTone = "plain";
      const c = this.actors.get("customer")!;
      this.flights.push({ fx: a.x, fz: a.z, tx: c.x, tz: c.z, start: now });
      this.links.push({ a: a.id, b: c.id, until: now + 3000 });
      a.lookAt = { x: c.x, z: c.z, until: now + 3500 };
    } else if (t === "message.sent" && ev.actor_id) {
      const from = this.actor(ev.actor_id, ev.actor_id);
      const to = d.to ? this.actor(d.to, d.to) : undefined;
      if (to) {
        this.meet(from, to, now);
        from.activity = `Briefing ${to.label}`;
        from.activityTone = "plain";
        this.say(from, ev.summary.replace(/^.*?:\s/, ""), "plain", now);
        to.task = { text: sentence(ev.summary.replace(/^.*?:\s/, "")), from: from.label };
      }
    } else if (t === "agent.decision" && ev.actor_id) {
      this.say(this.actor(ev.actor_id, ev.actor_id), ev.summary, "plain", now);
    } else if (t === "goal.revised") {
      const cust = this.actors.get("customer")!;
      cust.activity = `Changed the request (v${ev.goal_version})`;
      cust.activityTone = "cue";
      this.banner = { text: "The customer changed the request", until: now + 4500, tone: "cue" };
      this.actors.get("customer")!.badge = { tone: "cue", until: now + 4500 };
      this.doorOpenUntil = now + 3000;
    } else if (t === "fault.injected") {
      this.banner = { text: "Fault injected: the response never arrived", until: now + 4000, tone: "cue" };
      if (d.tool) this.desk(d.tool).flash = { tone: "cue", until: now + 3000 };
    } else if (t === "permission.changed") {
      this.banner = { text: "Permissions changed", until: now + 3500, tone: "cue" };
    } else if (t === "episode.claimed_complete" && ev.actor_id) {
      const a = this.actor(ev.actor_id, ev.actor_id);
      this.home(a);
      this.say(a, "I'm done.", "plain", now);
      a.activity = "Says the work is done";
      a.activityTone = "cue";
    } else if (t === "episode.finished" && (d.oracle?.environment_error || ev.summary.startsWith("environment_error"))) {
      // a setup problem, not the agent's fault: nobody is judged
      const v = this.actors.get("verifier")!;
      v.activity = "Not scored";
      v.activityTone = "cue";
      this.say(v, "This run couldn't happen, so I'm not scoring it.", "cue", now, 600_000);
      this.banner = { text: "Not scored", until: now + 600_000, tone: "cue" };
      this.actors.forEach((a) => a.kind === "agent" && this.home(a));
    } else if (t === "episode.finished") {
      const v = this.actors.get("verifier")!;
      const ok = d.reward === 1;
      v.badge = { tone: ok ? "go" : "stop", until: now + 600_000 };
      v.activity = ok ? "Verified the outcome" : "Checks failed";
      v.activityTone = ok ? "go" : "stop";
      this.say(v, ok ? "Verified in the app's own records." : "The checks failed.", ok ? "go" : "stop", now, 600_000);
      this.banner = { text: ok ? "Verified" : "Not verified", until: now + 600_000, tone: ok ? "go" : "stop" };
      this.actors.forEach((a) => a.kind === "agent" && this.home(a));
    }
  }

  /** Advances walking and keeps people from overlapping; returns true while anyone moves. */
  step(dtMs: number, instant: boolean, now = performance.now()): boolean {
    const speed = 0.0032 * dtMs; // metres per ms
    let moving = false;
    this.links = this.links.filter((l) => l.until > now);
    this.actors.forEach((a) => {
      if (a.returnAt && now > a.returnAt) {
        a.returnAt = 0;
        this.home(a);
      }
      const dx = a.tx - a.x;
      const dz = a.tz - a.z;
      const dist = Math.hypot(dx, dz);
      if (instant || dist <= speed) {
        a.x = a.tx;
        a.z = a.tz;
      } else {
        a.x += (dx / dist) * speed;
        a.z += (dz / dist) * speed;
        a.facing = Math.atan2(dx, dz);
        moving = true;
      }
      if (dist <= speed) {
        if (a.lookAt && a.lookAt.until > now) a.facing = Math.atan2(a.lookAt.x - a.x, a.lookAt.z - a.z);
        else if (Math.abs(a.tz - (DESK_Z + 1.1)) < 0.01) a.facing = Math.PI; // face the desk
        else if (a.kind === "agent" && a.x === a.homeX && a.z === a.homeZ) a.facing = a.homeZ < 7.4 ? 0 : Math.PI;
      }
    });
    // separation: walkers step around each other instead of merging
    const list = [...this.actors.values()];
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        const a = list[i];
        const b = list[j];
        const dx = b.x - a.x;
        const dz = b.z - a.z;
        const d = Math.hypot(dx, dz);
        if (d >= PERSONAL_SPACE || instant) continue;
        const push = (PERSONAL_SPACE - d) / 2;
        const ux = d > 1e-3 ? dx / d : 1;
        const uz = d > 1e-3 ? dz / d : 0;
        const aSettled = a.x === a.tx && a.z === a.tz;
        const bSettled = b.x === b.tx && b.z === b.tz;
        if (!aSettled || bSettled) {
          a.x -= ux * push;
          a.z -= uz * push;
        }
        if (!bSettled || aSettled) {
          b.x += ux * push;
          b.z += uz * push;
        }
      }
    }
    // chips are wider than people: front chips stay low, a chip behind one it would cover moves up a level
    const placed: Actor[] = [];
    for (const a of list.sort((p, q) => q.z - p.z)) {
      let lift = 0;
      while (placed.some((o) => o.lift === lift && Math.abs(o.x - a.x) < CHIP_HALF_SPAN && Math.abs(o.z - a.z) < 2.2)) lift++;
      a.lift = lift;
      placed.push(a);
    }
    return moving;
  }
}
