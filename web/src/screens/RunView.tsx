"use client";

import { GitCompareArrows, MessageSquareWarning, Pause, Sparkles, Square } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Inspector } from "@/components/inspector";
import { ActivityFeed, ModelsByRole, NowCaption, PageHeader, Stat, StatusBadge, Tone } from "@/components/rh";
import { pct, post, useEvents, useResource, type RhEvent } from "../api";
import { humanTool } from "../describe";
import { go, routes } from "../nav";
import type { Selection } from "../stage/Stage";
import { describeEnding, explainProblem } from "../problems";

const Stage = dynamic(() => import("../stage/Stage").then((m) => m.Stage), { ssr: false });

export function Scorecard({ agg }: { agg: any }) {
  if (!agg) return null;
  return (
    <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
      <Stat value={pct(agg.success_rate)} label={`verified success (${agg.successes}/${agg.finished})`} className="border-success/30" />
      <Stat value={agg.hard_violation_episodes} label="episodes with a rule violation" />
      <Stat value={agg.false_completions} label="claimed done but was not" />
      <Stat value={agg.duplicate_effects} label="duplicate side effects" />
      <Stat value={agg.recovered} label="recovered after a fault" />
      <Stat value={agg.environment_errors} label="environment errors (not scored)" />
    </div>
  );
}

function EpisodeTabs({ episodeId }: { episodeId: string }) {
  const ep = useResource<any>(`/v1/episodes/${episodeId}`, 4000);
  const e = ep.data;
  if (!e) return null;
  const checks = e.oracle?.check_results || [];
  return (
    <Card>
      <CardHeader>
        <CardTitle>{e.scenario?.title}</CardTitle>
        <CardDescription>{e.scenario?.slug} · {e.scenario?.split} · {describeEnding(e.termination)}{e.oracle?.changed_tables?.length ? ` · tables changed: ${e.oracle.changed_tables.map((t: string) => t.split(":").pop()).join(", ")}` : ""}</CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="checks">
          <TabsList><TabsTrigger value="checks">Independent checks</TabsTrigger><TabsTrigger value="actions">Actions ({e.actions.length})</TabsTrigger><TabsTrigger value="messages">Messages ({e.messages.length})</TabsTrigger></TabsList>
          <TabsContent value="checks">
            {checks.length === 0 && <p className="text-sm text-muted-foreground">The verifier runs when the episode ends.</p>}
            <Table><TableBody>{checks.map((c: any) => (
              <TableRow key={c.id}>
                <TableCell>{c.description}</TableCell>
                <TableCell>{c.role === "constraint" ? <Tone tone="stop">must never fail</Tone> : <Tone tone="info">goal</Tone>}</TableCell>
                <TableCell><Tone tone={c.passed ? "go" : "stop"}>{c.passed ? "passed" : "failed"}</Tone></TableCell>
                <TableCell className="text-xs text-muted-foreground">{c.error ?? `${JSON.stringify(c.actual)} ${c.op} ${JSON.stringify(c.expected)}`}</TableCell>
              </TableRow>
            ))}</TableBody></Table>
            {e.oracle?.environment_error && <p className="mt-3 rounded-md border border-warning/30 bg-warning/10 p-3 text-sm">{explainProblem(e.oracle.environment_error)}</p>}
          </TabsContent>
          <TabsContent value="actions">
            <Table>
              <TableHeader><TableRow><TableHead>#</TableHead><TableHead>Actor</TableHead><TableHead>Tool</TableHead><TableHead>Outcome</TableHead><TableHead>Request seen</TableHead><TableHead>What the agent saw</TableHead></TableRow></TableHeader>
              <TableBody>{e.actions.map((a: any) => (
                <TableRow key={a.id}>
                  <TableCell className="tabular-nums">{a.seq}</TableCell>
                  <TableCell>{a.actor}</TableCell>
                  <TableCell><div className="font-medium">{humanTool(a.tool)}</div><div className="max-w-56 truncate font-mono text-xs text-muted-foreground">{JSON.stringify(a.args)}</div></TableCell>
                  <TableCell><Tone tone={a.status === "SUCCEEDED" ? "go" : a.status === "UNKNOWN" ? "cue" : "stop"}>{a.status.toLowerCase()}</Tone>{a.fault && <div className="mt-1 text-xs text-warning">{a.fault.replace(/_/g, " ")}</div>}</TableCell>
                  <TableCell>{a.observed_goal_version < a.goal_version ? <Tone tone="cue">v{a.observed_goal_version} of v{a.goal_version}</Tone> : `v${a.goal_version}`}</TableCell>
                  <TableCell className="max-w-72 truncate font-mono text-xs">{JSON.stringify(a.visible_result)}</TableCell>
                </TableRow>
              ))}</TableBody>
            </Table>
          </TabsContent>
          <TabsContent value="messages" className="space-y-2">
            {e.messages.map((m: any) => <div key={m.id} className="rounded-md border p-3 text-sm"><span className="font-medium">{m.sender}</span> <span className="text-muted-foreground">to</span> <span className="font-medium">{m.recipient}</span><p className="mt-1">{m.text}</p></div>)}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

function Intervene({ episodeId, goals }: { episodeId: string; goals: any[] }) {
  const [text, setText] = useState("");
  const [goal, setGoal] = useState(String(goals[goals.length - 1]?.version ?? 1));
  const send = async (body: any) => {
    try {
      await post(`/v1/episodes/${episodeId}/interventions`, body);
      toast.success("Queued; applied before the agent's next action");
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  return (
    <Dialog>
      <DialogTrigger asChild><Button variant="outline"><MessageSquareWarning /> Intervene</Button></DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Intervene in this episode</DialogTitle><DialogDescription>Act as the customer or change what they want, mid-episode. The change is recorded like any scheduled event.</DialogDescription></DialogHeader>
        <div className="grid gap-2"><Label htmlFor="say">Customer says</Label><Input id="say" value={text} onChange={(e) => setText(e.target.value)} /></div>
        <div className="grid gap-2">
          <Label>Request version</Label>
          <Select value={goal} onValueChange={setGoal}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{goals.map((g) => <SelectItem key={g.version} value={String(g.version)}>v{g.version}: {g.instruction.slice(0, 60)}</SelectItem>)}</SelectContent></Select>
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" disabled={!text} onClick={() => send({ kind: "customer_message", text })}>Send as customer</Button>
          <Button onClick={() => send({ kind: "goal_change", goal_version: Number(goal), text: text || goals.find((g) => String(g.version) === goal)?.instruction })}>Change the request</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FixAgent({ runId, worldVersionId, profiles }: { runId: string; worldVersionId: string; profiles: { id: string; name: string }[] }) {
  const [profile, setProfile] = useState(profiles[0]?.id ?? "");
  const [rounds, setRounds] = useState("3");
  const [busy, setBusy] = useState(false);
  const scenarios = useResource<any[]>(`/v1/world-versions/${worldVersionId}/scenarios`);
  const count = (split: string) => (scenarios.data || []).filter((s) => s.status === "approved" && s.split === split).length;
  const practice = count("train") + count("dev");
  const most = Number(rounds) * practice + 2 * count("holdout");
  const start = async () => {
    setBusy(true);
    try {
      const res = await post("/v1/autofix", { profile_id: profile, run_id: runId, rounds: Number(rounds) });
      go(routes.fix(res.job_id));
    } catch (e) {
      toast.error((e as Error).message);
      setBusy(false);
    }
  };
  const improve = async () => {
    try {
      const res = await post("/v1/improvements", { profile_id: profile, run_id: runId });
      toast.success(`Improvement job ${res.job_id} started; the new version appears on the Agents page.`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  return (
    <Dialog>
      <DialogTrigger asChild><Button variant="outline"><Sparkles /> Fix my agent</Button></DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Fix an agent from this run</DialogTitle>
          <DialogDescription>Each round writes a new version from the failed train and dev episodes and rehearses it on every train and dev job. It is kept only if it verifies more without breaking a rule. The best version is then proved against the original on held-out jobs.</DialogDescription>
        </DialogHeader>
        {profiles.length > 1 && (
          <div className="grid gap-2">
            <Label>Agent</Label>
            <Select value={profile} onValueChange={setProfile}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{profiles.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent></Select>
          </div>
        )}
        <div className="grid gap-2">
          <Label>Rounds</Label>
          <Select value={rounds} onValueChange={setRounds}><SelectTrigger className="w-28"><SelectValue /></SelectTrigger><SelectContent>{[1, 2, 3, 4, 5].map((n) => <SelectItem key={n} value={String(n)}>{n}</SelectItem>)}</SelectContent></Select>
        </div>
        <p className="text-sm text-muted-foreground">
          {scenarios.data ? `At most ${most} episodes, about $${(most * 0.02).toFixed(2)}: ${rounds} × ${practice} train and dev jobs, then 2 × ${count("holdout")} held-out jobs. It stops early when every job passes.` : "Counting the jobs…"}
        </p>
        <DialogFooter className="gap-2">
          <Button variant="ghost" onClick={improve}>Only propose one version</Button>
          <Button disabled={!profile || !practice || busy} onClick={start}>Start {rounds} {rounds === "1" ? "round" : "rounds"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function RunView({ runId, episodeId }: { runId: string; episodeId?: string }) {
  const run = useResource<any>(`/v1/runs/${runId}`, 4000);
  const episodes = useResource<any[]>(`/v1/runs/${runId}/episodes`, 4000);
  const { events } = useEvents(`/v1/runs/${runId}/events`);
  const [beat, setBeat] = useState<RhEvent | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  // Several episodes run at once (one per sandbox). Follow the oldest one still running until it ends, so the
  // live view does not jump to every episode that starts; afterwards show the most recent one.
  const live = useMemo(() => {
    const finished = new Set(events.filter((e) => e.type === "episode.finished").map((e) => e.episode_id));
    const started = events.filter((e) => e.type === "episode.started");
    return (started.find((e) => !finished.has(e.episode_id)) ?? started[started.length - 1])?.episode_id ?? null;
  }, [events]);
  const selected = episodeId || live || episodes.data?.[0]?.id || null;
  const epEvents = useMemo(() => events.filter((e: RhEvent) => e.episode_id === selected), [events, selected]);
  useEffect(() => setBeat(null), [selected]); // the caption belongs to the episode on screen
  const selectedRow = episodes.data?.find((e) => e.id === selected);
  const ep = useResource<any>(selected ? `/v1/episodes/${selected}` : null, 5000);
  const goalEv = [...epEvents].reverse().find((e) => e.type === "goal.revised");
  const r = run.data;
  const command = async (c: string) => {
    await post(`/v1/runs/${runId}/commands`, { command: c });
    run.reload();
  };
  const profiles = [...new Map((episodes.data || []).map((e) => [e.profile_id, { id: e.profile_id, name: e.profile }])).values()];
  return (
    <>
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-3">Run {runId.slice(-8)} {r && <StatusBadge status={r.status} />}</span>}
        description={`${(r?.config?.profiles || []).join(" vs ")} on ${(r?.config?.splits || []).join(", ")} scenarios. Click anyone in the room to see what they did and saw.`}
        actions={
          <>
            {selected && ep.data?.status === "running" && <Intervene episodeId={selected} goals={ep.data?.scenario?.goals || []} />}
            {r?.status === "running" && <Button variant="outline" onClick={() => command("pause")}><Pause /> Pause</Button>}
            {(r?.status === "running" || r?.status === "queued") && <Button variant="outline" className="text-destructive" onClick={() => command("stop")}><Square /> Stop</Button>}
            {r?.config?.autofix_job && <Button variant="outline" onClick={() => go(routes.fix(r.config.autofix_job))}>Back to the fix loop</Button>}
            {r?.status === "finished" && !r.config?.autofix_job && profiles.length > 0 && <FixAgent runId={runId} worldVersionId={r.world_version_id} profiles={profiles} />}
            {r?.status === "finished" && <Button onClick={() => go(routes.compare(runId))}><GitCompareArrows /> Compare</Button>}
          </>
        }
      />
      {r?.status === "queued" && r.config?.starts_at && new Date(r.config.starts_at) > new Date() && (
        <div className="mb-3 rounded-lg border bg-muted/40 p-3 text-sm">
          On the free plan, evaluations start in quiet hours. This run starts at {new Date(r.config.starts_at).toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" })} your time. Paid plans start runs at once: see Billing.
        </div>
      )}
      <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
        <Tone tone="cue">Request v{goalEv?.goal_version ?? 1}</Tone>
        {selectedRow && <span className="text-muted-foreground">{selectedRow.scenario} with {selectedRow.profile}</span>}
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div>
          <Stage key={selected ?? "none"} events={epEvents} mode="episode" onBeat={setBeat} onSelect={setSelection} selected={selection} label="Agents, the customer, and the verifier in the rehearsal room; agents move to the tools they use" />
          <NowCaption ev={beat} fallback="Waiting for the episode to start" />
        </div>
        <ActivityFeed events={epEvents} onPick={(id) => setSelection({ kind: "actor", id })} height="calc(min(54vw, 60vh) + 70px)" />
      </div>
      <div className="mt-6 grid gap-6">
        {r?.summary?.profiles && Object.entries(r.summary.profiles).map(([name, s]: [string, any]) => (
          <section key={name} className="grid gap-3"><h2 className="text-lg font-semibold">{name}</h2><Scorecard agg={s.overall} /></section>
        ))}
        <Card>
          <CardHeader>
            <CardTitle>Episodes</CardTitle>
            <CardDescription>Cost is what Rehearsal spent on models: the simulated customer and, for hosted agents, the agent. A bring-your-own agent's own model calls are billed by its provider and are not included.</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader><TableRow><TableHead>Scenario</TableHead><TableHead>Agent</TableHead><TableHead>Status</TableHead><TableHead>Outcome</TableHead><TableHead className="text-right">Cost</TableHead></TableRow></TableHeader>
              <TableBody>
                {episodes.data?.map((e) => (
                  <TableRow key={e.id} className={`cursor-pointer ${e.id === selected ? "bg-accent" : ""}`} onClick={() => go(routes.run(runId, e.id))}>
                    <TableCell><div className="font-medium">{e.scenario}</div><div className="text-xs text-muted-foreground">{e.split}</div></TableCell>
                    <TableCell>{e.profile}</TableCell>
                    <TableCell><StatusBadge status={e.status} /></TableCell>
                    <TableCell>{e.status === "error" ? <Tone tone="plain">not scored</Tone> : e.reward === 1 ? <Tone tone="go">verified</Tone> : e.reward === -1 ? <Tone tone="stop">rule violated</Tone> : e.status === "finished" ? <Tone tone="cue">not achieved</Tone> : null}</TableCell>
                    <TableCell className="text-right tabular-nums">{e.cost_usd ? `$${e.cost_usd.toFixed(4)}` : "–"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        {selected && <EpisodeTabs episodeId={selected} />}
        <ModelsByRole models={r?.models} what="run" />
      </div>
      <Inspector open={!!selection} onOpenChange={(o) => !o && setSelection(null)} selection={selection} mode="episode" events={epEvents} episodeId={selected} />
    </>
  );
}
