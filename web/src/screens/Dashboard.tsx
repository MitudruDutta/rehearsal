"use client";

import { ArrowRight, CircleCheck, CircleDashed, CircleX, Hammer, PlayCircle, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ActorAvatar, PageHeader, PhaseStepper, PHASES, PHASE_KEYS, StatusBadge, Tone } from "@/components/rh";
import { pct, post, useResource, type RhEvent } from "../api";
import { describe } from "../describe";
import { go, routes } from "../nav";

/** Overview = a readiness board: can this agent go live in this application, and on what evidence? */

const READY_SUCCESS = 0.8;
const MIN_EPISODES = 3;

type Verdict = { kind: "ready" | "work" | "thin" | "none" | "noworld"; label: string; evidence?: any; split?: string; result?: any; why?: string };

/** Which agent versions were produced by Improve: they have learned from the training jobs. */
function improvedVersions(agents: any[]): Set<string> {
  return new Set(agents.flatMap((a: any) => (a.versions || []).filter((v: any) => v.created_by === "improver").map((v: any) => `${a.name}@${v.version}`)));
}

function verdict(world: any, agent: string, improved: Set<string> = new Set()): Verdict {
  if (!world.published) return { kind: "noworld", label: world.latest?.status === "building" ? "World building" : "No world yet" };
  const mine = (world.results || []).filter((r: any) => r.name === agent);
  if (!mine.length) return { kind: "none", label: "Not evaluated" };
  const latest = mine.reduce((a: any, b: any) => (b.version > a.version || (b.version === a.version && (b.finished_at ?? "") > (a.finished_at ?? "")) ? b : a));
  // A version made by Improve has learned from the training jobs, so only jobs it never saw count. A version
  // nobody improved has learned from no job in this world, so every job is unseen and counts.
  const learned = improved.has(`${agent}@${latest.version}`);
  const split = !learned ? "all jobs" : latest.holdout ? "held-out" : latest.dev ? "dev" : "all jobs";
  const ev = !learned ? latest.overall : latest.holdout ?? latest.dev ?? latest.overall;
  const clean = ev.hard_violation_episodes === 0 && ev.false_completions === 0;
  if (ev.finished < MIN_EPISODES && clean && (ev.success_rate ?? 0) >= READY_SUCCESS) {
    return { kind: "thin", label: `Too few episodes (${ev.finished} of ${MIN_EPISODES})`, evidence: ev, split, result: latest };
  }
  const ok = ev.finished >= MIN_EPISODES && (ev.success_rate ?? 0) >= READY_SUCCESS && clean;
  const why = [
    (ev.success_rate ?? 0) < READY_SUCCESS && `${pct(ev.success_rate)} verified (needs ${Math.round(READY_SUCCESS * 100)}%)`,
    ev.hard_violation_episodes > 0 && `${ev.hard_violation_episodes} broke a rule`,
    ev.false_completions > 0 && `${ev.false_completions} false "done"`,
    ev.finished < MIN_EPISODES && `only ${ev.finished} of ${MIN_EPISODES} episodes`,
  ].filter(Boolean).join(", ");
  return { kind: ok ? "ready" : "work", label: ok ? "Ready to pilot" : "Needs work", evidence: ev, split, result: latest, why };
}

function VerdictCell({ v }: { v: Verdict }) {
  if (!v.result) {
    return (
      <div className="flex h-full items-center gap-2 rounded-lg border border-dashed px-3 py-3 text-sm text-muted-foreground">
        <CircleDashed className="size-4" /> {v.label}
      </div>
    );
  }
  const ready = v.kind === "ready";
  const tone = ready ? "border-success/40 bg-success/10" : v.kind === "thin" ? "border-border bg-muted/30" : "border-destructive/40 bg-destructive/10";
  const ink = ready ? "text-success" : v.kind === "thin" ? "text-muted-foreground" : "text-destructive";
  return (
    <HoverCard openDelay={150}>
      <HoverCardTrigger asChild>
        <Link href={routes.run(v.result.run_id)} className={`block rounded-lg border p-3 transition-colors hover:bg-accent ${tone}`}>
          <div className={`flex items-center gap-1.5 text-sm font-semibold ${ink}`}>
            {ready ? <CircleCheck className="size-4" /> : v.kind === "thin" ? <CircleDashed className="size-4" /> : <CircleX className="size-4" />} {v.label}
          </div>
          <div className="mt-1 font-heading text-3xl font-bold tabular-nums">{pct(v.evidence.success_rate)}</div>
          <div className="text-xs text-muted-foreground">verified on {v.split} · v{v.result.version}</div>
          {v.why && <div className="mt-1 text-xs text-destructive">{v.why}</div>}
        </Link>
      </HoverCardTrigger>
      <HoverCardContent className="w-80 text-sm">
        <div className="font-semibold">Evidence</div>
        <ul className="mt-2 space-y-1 text-muted-foreground">
          <li>{v.evidence.successes} of {v.evidence.finished} episodes verified in the application's records</li>
          <li>{v.evidence.hard_violation_episodes} with rule violations</li>
          <li>{v.evidence.false_completions} false &ldquo;done&rdquo; claims</li>
          <li>{v.evidence.duplicate_effects} duplicate side effects</li>
          <li>recovered after faults: {v.evidence.recovered}</li>
        </ul>
      </HoverCardContent>
    </HoverCard>
  );
}

function LiveItem({ item }: { item: any }) {
  const last = item.last_event ? describe(item.last_event) : item.last;
  if (item.kind === "world_build") {
    const idx = Math.max(0, PHASE_KEYS.indexOf(item.phase));
    return (
      <button onClick={() => go(routes.build(item.job_id))} className="w-full rounded-lg border bg-background/40 p-3 text-left transition-colors hover:bg-accent">
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-2 font-medium"><Hammer className="size-4 text-primary" /> Building {item.application}</span>
          <span className="text-xs text-muted-foreground">{item.status === "queued" ? "queued" : `${idx + 1}/9`}</span>
        </div>
        <div className="mt-2"><PhaseStepper done={PHASE_KEYS.slice(0, item.done)} active={item.phase} compact /></div>
        <div className="mt-2 text-sm">{PHASES[idx]}</div>
        <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{last}</div>
      </button>
    );
  }
  if (item.kind === "world_validate") {
    return (
      <button onClick={() => item.world_version_id && go(routes.world(item.world_version_id))} className="w-full rounded-lg border bg-background/40 p-3 text-left transition-colors hover:bg-accent">
        <div className="flex items-center gap-2 font-medium"><ShieldCheck className="size-4 text-success" /> Re-checking {item.world}</div>
        <Progress value={item.total ? (item.checked / item.total) * 100 : 0} className="mt-2 h-1.5" />
        <div className="mt-2 text-sm">{item.status === "queued" ? "Queued" : `${item.checked} of ${item.total} jobs checked`}</div>
        <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{last}</div>
      </button>
    );
  }
  if (item.kind === "improvement") {
    return (
      <button onClick={() => item.run_id && go(routes.run(item.run_id))} className="w-full rounded-lg border bg-background/40 p-3 text-left transition-colors hover:bg-accent">
        <div className="flex items-center gap-2 font-medium"><Sparkles className="size-4 text-primary" /> Improving {item.agent}</div>
        <div className="mt-2 text-sm">{item.status === "queued" ? "Queued" : "Writing the next version from failed training jobs"}</div>
      </button>
    );
  }
  if (item.kind !== "evaluation") {
    return <div className="rounded-lg border bg-background/40 p-3 text-sm"><span className="font-medium capitalize">{item.kind.replace(/_/g, " ")}</span> <span className="text-muted-foreground">{item.status}</span></div>;
  }
  const share = item.episodes ? Math.round((item.finished / item.episodes) * 100) : 0;
  return (
    <button onClick={() => go(routes.run(item.run_id))} className="w-full rounded-lg border bg-background/40 p-3 text-left transition-colors hover:bg-accent">
      <div className="flex items-center gap-2 font-medium"><PlayCircle className="size-4 text-info" /> Rehearsing {(item.profiles || []).join(" and ")}</div>
      <Progress value={share} className="mt-2 h-1.5" />
      <div className="mt-2 text-sm">{item.finished} of {item.episodes} episodes, {item.verified} verified{item.shards > 1 ? `, ${item.shards} at a time` : ""}</div>
      <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{last}</div>
    </button>
  );
}

function BeforeAfter({ worlds }: { worlds: any[] }) {
  const groups: { key: string; title: string; rows: any[] }[] = [];
  for (const w of worlds) {
    const byAgent = new Map<string, Map<number, any>>();
    for (const r of w.results || []) {
      const m = byAgent.get(r.name) ?? new Map<number, any>();
      m.set(r.version, r);
      byAgent.set(r.name, m);
    }
    byAgent.forEach((versions, name) => {
      if (versions.size >= 2) groups.push({ key: `${w.application}-${name}`, title: `${name} on ${w.application}`, rows: [...versions.values()].sort((a, b) => a.version - b.version) });
    });
  }
  if (!groups.length) return <p className="text-sm text-muted-foreground">Improve an agent and evaluate the new version on the same world; its before and after appear here.</p>;
  return (
    <div className="space-y-5">
      {groups.map((g) => (
        <figure key={g.key}>
          <figcaption className="mb-2 text-sm font-medium">{g.title}</figcaption>
          <div className="space-y-2">
            {g.rows.map((r) => {
              const ev = r.holdout ?? r.dev ?? r.overall;
              return (
                <Tooltip key={r.version}>
                  <TooltipTrigger asChild>
                    <div className="grid grid-cols-[36px_1fr_48px] items-center gap-3 outline-none" tabIndex={0}>
                      <span className="text-sm text-muted-foreground">v{r.version}</span>
                      <span className="h-3.5 rounded-sm bg-muted"><span className="block h-full rounded-r-[4px] bg-chart-1" style={{ width: `${Math.max(1, Math.round((ev.success_rate ?? 0) * 100))}%` }} /></span>
                      <span className="text-right text-sm font-semibold tabular-nums">{pct(ev.success_rate)}</span>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>v{r.version}: {ev.successes} of {ev.finished} verified on {r.holdout ? "held-out" : r.dev ? "dev" : "all"} scenarios; {ev.hard_violation_episodes} with rule violations; recovered {ev.recovered}</TooltipContent>
                </Tooltip>
              );
            })}
          </div>
        </figure>
      ))}
    </div>
  );
}

/** First-run checklist, derived from what the project already has; it disappears once everything is done. */
function GetStarted({ d, onImport }: { d: any; onImport: () => void }) {
  const t = d.totals;
  const building = d.worlds.some((w: any) => w.latest?.status === "building");
  const steps = [
    { done: t.applications > 0, title: "Add an application", body: "Start with the sample apps, or connect your own repository and images.", action: t.applications === 0 ? <Button size="sm" onClick={onImport}>Add sample applications</Button> : null },
    { done: t.worlds_published > 0, title: "Build a practice world", body: building ? "A build is running; open it to watch the compiler work." : "The World Compiler turns an application into a sandbox with validated jobs.", action: <Button size="sm" variant="outline" asChild><Link href={routes.applications}>{building ? "Watch the build" : "Open applications"}</Link></Button> },
    { done: d.agents.length > 0, title: "Describe the agent under test", body: "A model and its instructions, or your own agent over the episode API.", action: <Button size="sm" variant="outline" asChild><Link href={routes.agents}>Create an agent</Link></Button> },
    { done: t.episodes > 0, title: "Run the first rehearsal", body: "Episodes are scored against the application's own records.", action: <Button size="sm" variant="outline" asChild><Link href={routes.runs()}>Run an evaluation</Link></Button> },
  ];
  const done = steps.filter((x) => x.done).length;
  if (done === steps.length) return null;
  const next = steps.findIndex((x) => !x.done);
  return (
    <Card className="mb-6 border-primary/40">
      <CardHeader>
        <CardTitle>Get started</CardTitle>
        <CardDescription>{done} of {steps.length} done. Each step unlocks the next.</CardDescription>
        <Progress value={(done / steps.length) * 100} className="mt-2 h-1.5" />
      </CardHeader>
      <CardContent>
        <ol className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {steps.map((x, i) => (
            <li key={x.title} className={`flex flex-col gap-2 rounded-lg border p-3 ${i === next ? "border-primary bg-primary/5" : ""}`}>
              <span className="flex items-center gap-2 font-medium">
                {x.done ? <CircleCheck className="size-4 shrink-0 text-success" /> : <CircleDashed className="size-4 shrink-0 text-muted-foreground" />}
                {x.title}
              </span>
              <span className="text-sm text-muted-foreground">{x.body}</span>
              {!x.done && i === next && x.action && <span className="mt-auto pt-1">{x.action}</span>}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

export function Dashboard() {
  const dash = useResource<any>("/v1/dashboard", 4000);
  const d = dash.data;
  if (dash.error) return <p className="text-destructive">{dash.error}</p>;
  if (!d) return <div className="grid gap-4"><Skeleton className="h-10 w-1/2" /><Skeleton className="h-64" /><Skeleton className="h-40" /></div>;
  const t = d.totals;
  const worlds = d.worlds.filter((w: any) => w.published || w.latest);
  const improved = improvedVersions(d.agents);
  const ready = d.agents.reduce((n: number, a: any) => n + worlds.filter((w: any) => verdict(w, a.name, improved).kind === "ready").length, 0);
  const cells = d.agents.length * Math.max(1, worlds.filter((w: any) => w.published).length);
  const importCatalog = async () => {
    await post("/v1/applications/import-catalog");
    toast.success("Sample applications added");
    dash.reload();
  };
  return (
    <>
      <PageHeader
        title="Is each agent ready for each application?"
        description="Every verdict rests on episodes scored against the application's own records, never on the agent's own claims."
        actions={t.applications === 0 ? <Button onClick={importCatalog}>Load sample applications</Button> : <Button asChild><Link href={routes.runs()}>Run an evaluation <ArrowRight /></Link></Button>}
      />

      <GetStarted d={d} onImport={importCatalog} />

      <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-xl border bg-gradient-to-br from-primary/20 to-transparent p-4 sm:col-span-2 xl:col-span-1">
          <div className="font-heading text-4xl font-bold tabular-nums">{ready}<span className="text-xl text-muted-foreground"> / {cells}</span></div>
          <div className="mt-1 text-sm text-muted-foreground">agent and application pairs ready to pilot</div>
        </div>
        <div className="rounded-xl border bg-card p-4"><div className="font-heading text-3xl font-bold tabular-nums">{t.worlds_published}</div><div className="mt-1 text-sm text-muted-foreground">practice worlds from {t.applications} applications</div></div>
        <div className="rounded-xl border bg-card p-4"><div className="font-heading text-3xl font-bold tabular-nums">{t.scenarios}</div><div className="mt-1 text-sm text-muted-foreground">scenarios proven passable and failable</div></div>
        <div className="rounded-xl border bg-card p-4"><div className="font-heading text-3xl font-bold tabular-nums">{t.episodes}</div><div className="mt-1 text-sm text-muted-foreground">episodes rehearsed · ${t.spend_usd.toFixed(2)} model spend</div></div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <CardHeader>
            <CardTitle>Readiness</CardTitle>
            <CardDescription>Ready to pilot: at least {MIN_EPISODES} scored episodes on jobs the agent version never learned from (every job for a version nobody improved; held-out jobs for a version made by Improve), {Math.round(READY_SUCCESS * 100)}% or more verified, no rule violations, no false &ldquo;done&rdquo; claims. Jobs withdrawn as unfair do not count.</CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            {d.agents.length === 0 ? (
              <p className="text-sm text-muted-foreground">Create an agent profile on the Agents page, then evaluate it to see a verdict per application.</p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="w-40">Agent</TableHead>
                    {worlds.map((w: any) => <TableHead key={w.application_id} className="min-w-48">{w.application}</TableHead>)}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.agents.map((a: any) => (
                    <TableRow key={a.name} className="hover:bg-transparent">
                      <TableCell className="align-top">
                        <div className="flex items-center gap-2"><ActorAvatar id={a.name} className="size-7" /><div><div className="font-medium">{a.name}</div><div className="text-xs text-muted-foreground">v{a.versions[a.versions.length - 1].version}</div></div></div>
                      </TableCell>
                      {worlds.map((w: any) => <TableCell key={w.application_id} className="align-top"><VerdictCell v={verdict(w, a.name, improved)} /></TableCell>)}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>On stage now</CardTitle><CardDescription>Builds and evaluations in progress.</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            {d.live.length === 0 ? <p className="text-sm text-muted-foreground">Nothing running.</p> : d.live.map((it: any) => <LiveItem key={it.job_id} item={it} />)}
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Before and after improvement</CardTitle><CardDescription>Verified success per agent version, same pinned world.</CardDescription></CardHeader>
          <CardContent><BeforeAfter worlds={d.worlds} /></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Practice worlds</CardTitle><CardDescription>One per application, rebuilt when the application changes.</CardDescription></CardHeader>
          <CardContent>
            <Table>
              <TableBody>
                {d.worlds.map((w: any) => (
                  <TableRow key={w.application_id}>
                    <TableCell><div className="font-medium">{w.application}</div><div className="text-xs text-muted-foreground">{(w.notes || "").split(";")[1]?.replace("domain=", "").trim()}</div></TableCell>
                    <TableCell>{w.published ? <div className="flex flex-wrap items-center gap-1.5"><Tone tone="go">v{w.published.version}</Tone>{["train", "dev", "holdout"].map((k) => <Badge key={k} variant="secondary" className="font-normal">{w.published.scenarios[k] ?? 0} {k}</Badge>)}</div> : w.latest ? <StatusBadge status={w.latest.status} /> : <Tone tone="plain">not built</Tone>}</TableCell>
                    <TableCell className="text-right">
                      {w.published ? <Button size="sm" variant="outline" onClick={() => go(routes.world(w.published.id))}>Open</Button> : w.latest?.status === "building" ? <Button size="sm" variant="outline" onClick={() => go(routes.build(w.latest.build_job_id))}>Watch</Button> : ["failed", "cancelled"].includes(w.latest?.status) ? (
                        <Button size="sm" onClick={async () => { await post(`/v1/jobs/${w.latest.build_job_id}/commands`, { command: "retry" }); go(routes.build(w.latest.build_job_id)); }}>Restart</Button>
                      ) : (
                        <Button size="sm" onClick={async () => { const r = await post("/v1/world-builds", { application_id: w.application_id }); go(routes.build(r.job_id)); }}>Build</Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader><CardTitle>Recent milestones</CardTitle></CardHeader>
        <CardContent>
          <ScrollArea className="h-80">
            {d.recent.length === 0 && <p className="text-sm text-muted-foreground">Milestones appear as worlds are built and agents are evaluated.</p>}
            <ul className="divide-y">
              {d.recent.map((e: RhEvent & { context?: string }) => (
                <li key={e.event_id} className="flex items-start gap-3 py-2.5">
                  <ActorAvatar id={e.actor_id} className="size-7" />
                  <div className="text-sm">
                    {e.context && <span className="font-semibold">{e.context}: </span>}{describe(e)}
                    <div className="text-xs text-muted-foreground">{new Date(e.created_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</div>
                  </div>
                </li>
              ))}
            </ul>
          </ScrollArea>
        </CardContent>
      </Card>
    </>
  );
}
