"use client";

import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { actorOf, describe } from "../describe";
import type { RhEvent } from "../api";
import { avatar } from "../stage/look";
import { ScrollArea } from "@/components/ui/scroll-area";

export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-bold tracking-tight md:text-[28px]">{title}</h1>
        {description && <p className="mt-1.5 text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

const TONES: Record<string, string> = {
  go: "border-success/30 bg-success/15 text-success",
  stop: "border-destructive/30 bg-destructive/15 text-destructive",
  cue: "border-warning/30 bg-warning/15 text-warning",
  info: "border-info/30 bg-info/15 text-info",
  plain: "border-border bg-muted text-muted-foreground",
};

export function Tone({ tone, children, className }: { tone: keyof typeof TONES; children: ReactNode; className?: string }) {
  return <Badge variant="outline" className={cn("gap-1 font-medium", TONES[tone], className)}>{children}</Badge>;
}

export function StatusBadge({ status }: { status: string }) {
  const tone = ["published", "succeeded", "finished", "approved", "validated"].includes(status) ? "go" : ["failed", "rejected", "error"].includes(status) ? "stop" : ["running", "building", "queued", "paused", "proposed"].includes(status) ? "cue" : "plain";
  return <Tone tone={tone as keyof typeof TONES}>{status}</Tone>;
}

export function Stat({ label, value, hint, className }: { label: ReactNode; value: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-xl border bg-card p-4", className)}>
      <div className="font-heading text-[28px] font-bold leading-none tabular-nums">{value}</div>
      <div className="mt-2 text-sm text-muted-foreground">{label}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground/80">{hint}</div>}
    </div>
  );
}

export function ActorAvatar({ id, className }: { id: string | null; className?: string }) {
  return id ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={avatar(id)} alt="" className={cn("size-8 shrink-0 rounded-md [image-rendering:pixelated]", className)} />
  ) : (
    <span className={cn("size-8 shrink-0 rounded-md bg-muted", className)} />
  );
}

export const PHASES = ["Read the source", "Research real use", "Plan the runtime", "Start the sandbox", "Find the API", "Seed fictional data", "Choose agent tools", "Write scenarios", "Validate and repair", "Publish"];
export const PHASE_KEYS = ["inspect", "research", "plan", "materialize", "discover", "seed", "adapt", "author", "validate", "package"];

export function PhaseStepper({ done, active, failed, compact }: { done: Set<string> | string[]; active?: string; failed?: boolean; compact?: boolean }) {
  const d = new Set(done);
  return (
    // each step shares the list's rows (bar, name, status), so a name that wraps to two lines keeps every status level
    <ol className={cn("grid gap-x-1.5", compact ? "grid-cols-10" : "grid-cols-3 md:grid-cols-10")} aria-label="Compiler phases">
      {PHASES.map((label, i) => {
        const key = PHASE_KEYS[i];
        // a phase that never ran while later ones did (web research on a build from before it existed) was skipped
        const later = PHASE_KEYS.slice(i + 1).some((k) => d.has(k) || active === k);
        const state = d.has(key) ? "done" : active === key ? (failed ? "failed" : "active") : later ? "skipped" : "todo";
        return (
          <li key={key} className={cn("min-w-0", !compact && "row-span-3 grid grid-rows-subgrid pb-2.5 md:pb-0")}>
            <div className={cn("h-1.5 rounded-full", state === "done" ? "bg-success" : state === "active" ? "animate-pulse bg-primary" : state === "failed" ? "bg-destructive" : state === "skipped" ? "bg-muted-foreground/25" : "bg-muted")} />
            {!compact && (
              <>
                <div className={cn("mt-2 text-[13px] font-medium leading-snug text-pretty", (state === "todo" || state === "skipped") && "text-muted-foreground")}>{i + 1}. {label}</div>
                <div className="text-xs text-muted-foreground">{state === "done" ? "done" : state === "active" ? (failed ? "stopped" : "in progress") : state === "skipped" ? "skipped" : "waiting"}</div>
              </>
            )}
          </li>
        );
      })}
    </ol>
  );
}

const ROW_TONE = (t: string) =>
  t.includes("goal") || t.includes("fault") || t.endsWith("unknown") || t === "compiler.repair" || t === "job.retrying"
    ? "border-l-warning bg-warning/5"
    : t.endsWith("rejected") || t.endsWith("failed")
      ? "border-l-destructive bg-destructive/5"
      : t.endsWith("accepted") || t.endsWith("completed") || t === "world.published" || t.endsWith("succeeded")
        ? "border-l-success"
        : "border-l-transparent";

export function ActivityFeed({ events, onPick, height = "calc(54vw)" }: { events: RhEvent[]; onPick?: (actor: string) => void; height?: string }) {
  const rows: { ev: RhEvent; count: number }[] = [];
  for (const e of events.filter((x) => !["job.queued", "compiler.sandbox", "fault.armed", "intervention.requested"].includes(x.type))) {
    const last = rows[rows.length - 1];
    if (last && e.type === "compiler.tool" && last.ev.type === e.type && actorOf(last.ev) === actorOf(e) && last.ev.data?.tool === e.data?.tool) {
      last.ev = e;
      last.count += 1;
    } else rows.push({ ev: e, count: 1 });
  }
  const shown = rows.reverse().slice(0, 300);
  return (
    <ScrollArea className="rounded-xl border bg-card" style={{ height }}>
      {shown.length === 0 && <div className="p-6 text-sm text-muted-foreground">Waiting for the first event.</div>}
      <ul className="divide-y">
        {shown.map(({ ev, count }) => {
          const who = actorOf(ev);
          return (
            <li key={ev.event_id} className={cn("flex gap-3 border-l-[3px] px-3 py-2.5", ROW_TONE(ev.type))}>
              <button className="shrink-0 rounded-md focus-visible:ring-2 focus-visible:ring-ring" onClick={() => who && onPick?.(who)} title={who && onPick ? `Inspect ${who}` : undefined} disabled={!who || !onPick}>
                <ActorAvatar id={who} />
              </button>
              <div className="min-w-0 text-sm leading-snug">
                <p className="line-clamp-4 break-words">{describe(ev)}{count > 1 && <span className="text-muted-foreground"> and {count - 1} more like this</span>}</p>
                <p className="mt-0.5 text-xs tabular-nums text-muted-foreground">{new Date(ev.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</p>
              </div>
            </li>
          );
        })}
      </ul>
    </ScrollArea>
  );
}

export function NowCaption({ ev, fallback }: { ev: RhEvent | null; fallback: string }) {
  return (
    <div className="mt-3 flex min-h-14 items-center gap-3 rounded-xl border bg-card px-4 py-3" aria-live="polite">
      <ActorAvatar id={ev ? actorOf(ev) : null} className="size-9" />
      <span className="min-w-0 text-[15px] font-medium break-words">{ev ? describe(ev) : fallback}</span>
    </div>
  );
}

const ROLES: Record<string, string> = { agent: "Agent under test", customer: "Simulated customer", improver: "Improvement step", "compiler.auditor": "Compiler: live audit", "research.web": "Web research" };
const PROVIDERS: Record<string, string> = { tavily: "Tavily", nebius: "Nebius Token Factory", openrouter: "OpenRouter", litellm: "LiteLLM", groq: "Groq", local: "local", custom: "custom endpoint" };

/** Model calls, average time, tokens and spend for each role of a job or run, from its `models` usage record. */
export function ModelsByRole({ models, what }: { models?: Record<string, any> | null; what: string }) {
  const rows = Object.entries(models || {}).sort(([, a], [, b]) => b.cost_usd - a.cost_usd || b.calls - a.calls);
  if (!rows.length) return null;
  const sum = (k: string) => rows.reduce((t, [, r]) => t + (r[k] || 0), 0);
  const tokens = (n: number) => n >= 10_000 ? `${Math.round(n / 1000)}k` : n.toLocaleString();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Models by role</CardTitle>
        <CardDescription>Each role runs on its own model chain, with reasoning on only where it helps. What this {what} used, role by role.</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader><TableRow><TableHead>Role</TableHead><TableHead>Model</TableHead><TableHead className="text-right">Calls</TableHead><TableHead className="text-right">Time per call</TableHead><TableHead className="text-right">Tokens in / out</TableHead><TableHead className="text-right">Spend</TableHead></TableRow></TableHeader>
          <TableBody>
            {rows.map(([role, r]) => (
              <TableRow key={role}>
                <TableCell className="font-medium">{ROLES[role] ?? (role.startsWith("compiler.") ? `Compiler: ${role.slice(9).replace(/_/g, " ")}` : role)}</TableCell>
                <TableCell>
                  {Object.entries(r.models as Record<string, number>).sort(([, a], [, b]) => b - a).map(([name, n]) => {
                    const [chain, flag] = name.split("#");
                    const provider = chain.split(":")[0];
                    const model = chain.slice(provider.length + 1);
                    return (
                      <div key={name} className="flex flex-wrap items-center gap-1.5" title={name}>
                        <span className="font-mono text-xs">{model.split("/").pop()}</span>
                        {flag === "think" && <Tone tone="info">reasoning</Tone>}
                        <span className="text-xs text-muted-foreground">{PROVIDERS[provider] ?? provider}{Object.keys(r.models).length > 1 ? `, ${n} calls` : ""}</span>
                      </div>
                    );
                  })}
                </TableCell>
                <TableCell className="text-right tabular-nums">{r.calls}</TableCell>
                <TableCell className="text-right tabular-nums">{r.calls ? `${(r.latency_ms / r.calls / 1000).toFixed(1)} s` : "–"}</TableCell>
                <TableCell className="text-right tabular-nums">{tokens(r.prompt_tokens)} / {tokens(r.completion_tokens)}</TableCell>
                <TableCell className="text-right tabular-nums">${r.cost_usd.toFixed(4)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
          <TableFooter><TableRow><TableCell colSpan={2}>Total</TableCell><TableCell className="text-right tabular-nums">{sum("calls")}</TableCell><TableCell /><TableCell className="text-right tabular-nums">{tokens(sum("prompt_tokens"))} / {tokens(sum("completion_tokens"))}</TableCell><TableCell className="text-right tabular-nums">${sum("cost_usd").toFixed(4)}</TableCell></TableRow></TableFooter>
        </Table>
      </CardContent>
    </Card>
  );
}
