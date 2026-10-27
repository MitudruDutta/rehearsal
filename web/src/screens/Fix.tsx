"use client";

import { Check, GitCompareArrows, Loader2, RotateCcw, Square, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ModelsByRole, PageHeader, Stat, StatusBadge, Tone } from "@/components/rh";
import { pct, post, useEvents, useResource } from "../api";
import { go, routes } from "../nav";
import { explainProblem, nextStep } from "../problems";

type Score = { success_rate: number | null; successes?: number; finished: number; hard_violation_episodes: number; false_completions: number };

/** The instructions and tool guidance of a profile, one sentence per entry: the unit the change view compares. */
function sentences(spec: any): string[] {
  const guidance = Object.entries(spec?.tool_guidance || {}).map(([tool, text]) => `${tool}: ${text}`);
  return [spec?.system_prompt || "(platform default instructions)", ...guidance].join("\n").split(/(?<=[.!?])\s+|\n+/).map((s) => s.trim()).filter(Boolean);
}

/** Longest-common-subsequence diff of two sentence lists. */
export function diff(a: string[], b: string[]): { kind: "same" | "add" | "del"; text: string }[] {
  const L = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out: { kind: "same" | "add" | "del"; text: string }[] = [];
  let i = 0, j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { out.push({ kind: "same", text: a[i] }); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) out.push({ kind: "del", text: a[i++] });
    else out.push({ kind: "add", text: b[j++] });
  }
  return [...out, ...a.slice(i).map((text) => ({ kind: "del" as const, text })), ...b.slice(j).map((text) => ({ kind: "add" as const, text }))];
}

function Changes({ from, to }: { from: string; to: string }) {
  const a = useResource<any>(`/v1/agent-profiles/${from}`);
  const b = useResource<any>(`/v1/agent-profiles/${to}`);
  if (!a.data || !b.data) return <p className="mt-3 text-sm text-muted-foreground">Loading both versions…</p>;
  return (
    <div className="mt-3 max-h-80 overflow-y-auto rounded-lg border bg-muted/30 p-3 text-sm leading-relaxed" aria-label={`Changes from v${a.data.version} to v${b.data.version}`}>
      {diff(sentences(a.data.spec), sentences(b.data.spec)).map((d, k) =>
        d.kind === "same" ? <p key={k} className="text-muted-foreground">{d.text}</p>
        : d.kind === "add" ? <p key={k} className="my-1 rounded bg-success/10 px-2 py-0.5"><span className="sr-only">Added: </span><span aria-hidden className="mr-2 font-mono text-success">+</span>{d.text}</p>
        : <p key={k} className="my-1 rounded bg-destructive/10 px-2 py-0.5 line-through decoration-destructive/50"><span className="sr-only">Removed: </span><span aria-hidden className="mr-2 font-mono text-destructive no-underline">−</span>{d.text}</p>,
      )}
    </div>
  );
}

/** Why a version was not kept, in the order the loop checks. */
function whyDiscarded(s: Score, prev: Score) {
  if (s.success_rate == null) return "nothing was scored: every episode hit an environment error";
  if (s.hard_violation_episodes > prev.hard_violation_episodes) return "it broke a rule in more episodes";
  if (s.false_completions > prev.false_completions) return "it claimed done more often when it was not";
  return "it did not verify more episodes";
}

function Round({ r }: { r: any }) {
  const [open, setOpen] = useState(false);
  const prev: Score = r.compared_with.score;
  return (
    <li className="relative pb-7 pl-8 last:pb-0">
      <span className={`absolute left-0 top-0.5 grid size-6 place-items-center rounded-full border bg-background ${r.accepted ? "border-success/50 text-success" : "text-muted-foreground"}`}>
        {r.accepted ? <Check className="size-3.5" /> : <X className="size-3.5" />}
      </span>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="font-semibold">Round {r.round}: v{r.version}</h3>
        <Tone tone={r.accepted ? "go" : "plain"}>{r.accepted ? "kept" : "discarded"}</Tone>
        <span className="text-sm tabular-nums">
          <strong>{pct(r.score.success_rate)}</strong> verified <span className="text-muted-foreground">vs {pct(prev.success_rate)} for v{r.compared_with.version}</span>
        </span>
      </div>
      <p className="mt-1.5 max-w-3xl text-sm">{r.rationale || "No reason given."}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        {r.accepted ? "Kept: more episodes verified, with no new rule violation or false completion." : `Discarded: ${whyDiscarded(r.score, prev)}.`}
        {" "}{r.score.hard_violation_episodes} with a rule violation, {r.score.false_completions} claimed done but was not, {r.score.finished} scored.
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        {r.compared_with.profile_id && <Button size="sm" variant="outline" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide changes" : `What changed from v${r.compared_with.version}`}</Button>}
        {r.run_id && <Button size="sm" variant="ghost" onClick={() => go(routes.run(r.run_id))}>Open its episodes</Button>}
      </div>
      {open && <Changes from={r.compared_with.profile_id} to={r.profile_id} />}
    </li>
  );
}

function Proof({ st, done }: { st: any; done: boolean }) {
  const { original, best, holdout } = st;
  if (holdout) {
    const gain = Math.round((holdout.best.success_rate ?? 0) * 100) - Math.round((holdout.original.success_rate ?? 0) * 100); // the same rounding as the percentages shown
    return (
      <Card className="mb-6 border-primary/30">
        <CardHeader>
          <CardTitle>{gain > 0 ? `v${best.version} verifies ${gain} points more on jobs it never saw` : gain === 0 ? `v${best.version} matches v${original.version} on jobs it never saw` : `v${best.version} does worse than v${original.version} on jobs it never saw`}</CardTitle>
          <CardDescription>No round saw these held-out jobs, so this comparison is the result to trust, not the training score.{gain <= 0 ? ` Keep v${original.version}.` : ""}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <Stat value={pct(holdout.original.success_rate)} label={`v${original.version}, the original`} hint={`${holdout.original.hard_violation_episodes} rule violations, ${holdout.original.false_completions} false completions`} />
          <Stat value={pct(holdout.best.success_rate)} label={`v${best.version}, the best version`} hint={`${holdout.best.hard_violation_episodes} rule violations, ${holdout.best.false_completions} false completions`} className={gain > 0 ? "border-success/40" : undefined} />
        </CardContent>
      </Card>
    );
  }
  if (!done) return null;
  return (
    <Alert className="mb-6">
      <AlertTitle>{best.profile_id === original.profile_id ? `No version beat v${original.version}` : `v${best.version} is the best version`}</AlertTitle>
      <AlertDescription>
        {best.profile_id === original.profile_id
          ? "Every proposal verified no more episodes, or added a rule violation or a false completion, so the original stays and there was nothing to prove on held-out jobs. Read the failures for a cause the instructions cannot fix."
          : "This world has no held-out jobs, so the train and dev scores are the only evidence. Build a world version with held-out jobs to prove it."}
      </AlertDescription>
    </Alert>
  );
}

export function Fix({ jobId }: { jobId: string }) {
  const job = useResource<any>(`/v1/jobs/${jobId}`, 4000);
  const [attempt, setAttempt] = useState(0); // the stream closes when a job ends; a restart opens it again
  const { events } = useEvents(`/v1/jobs/${jobId}/events?restart=${attempt}`);
  const j = job.data;
  const st = j?.result?.original ? j.result : j?.autofix; // a job's result is {} until it succeeds
  const profile = useResource<any>(j ? `/v1/agent-profiles/${j.payload.profile_id}` : null);
  const failed = j?.status === "failed" || j?.status === "cancelled";
  const next = nextStep(j?.status === "cancelled" ? "stopped on request" : j?.error);
  const progress = [...events].reverse().find((e) => e.type === "run.progress")?.summary;
  const command = async (c: string) => {
    await post(`/v1/jobs/${jobId}/commands`, { command: c });
    toast(c === "retry" ? "Restarting from the last saved round" : "Stop requested");
    if (c === "retry") setAttempt((n) => n + 1);
    job.reload();
  };
  const working = ["running", "queued", "paused"].includes(j?.status);
  const now = !st ? "Scoring the starting version" : st.phase === "propose" ? `Writing round ${st.round}'s version from v${st.best.version}'s failures`
    : st.phase === "rehearse" ? `Rehearsing v${st.current?.version} on every train and dev job${progress ? `: ${progress}` : ""}`
    : st.phase === "holdout" ? `Running v${st.original.version} and v${st.best.version} side by side on held-out jobs${progress ? `: ${progress}` : ""}` : null;
  return (
    <>
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-3">Fix {profile.data?.name ?? "agent"} {j && <StatusBadge status={j.status} />}</span>}
        description="Each round writes a new version from the failures, rehearses it on every train and dev job, and keeps it only if it verifies more without breaking a rule or claiming done falsely. The best version is then proved against the original on held-out jobs."
        actions={
          <>
            {working && <Button variant="outline" className="text-destructive" onClick={() => command("stop")}><Square /> Stop</Button>}
            {failed && <Button variant={next.restart ? "default" : "outline"} onClick={() => command("retry")}><RotateCcw /> Restart from last round</Button>}
            {st?.holdout && <Button variant="outline" onClick={() => go(routes.compare(st.holdout.run_id))}><GitCompareArrows /> Compare on held-out jobs</Button>}
            {j?.status === "succeeded" && <Button onClick={() => go(routes.agents)}>Open agents</Button>}
          </>
        }
      />
      {j?.error && failed && (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>The fix loop stopped</AlertTitle>
          <AlertDescription>{explainProblem(j.error)} {next.text} Versions made so far are kept on the Agents page.</AlertDescription>
        </Alert>
      )}
      {working && now && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border bg-muted/40 p-3 text-sm" role="status">
          <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> {now}
          <span className="ml-auto whitespace-nowrap text-muted-foreground">Round {Math.min(st?.round ?? 1, j.payload.rounds)} of {j.payload.rounds}, spent ${(j.spent_usd ?? 0).toFixed(2)}</span>
        </div>
      )}
      {st && <Proof st={st} done={j?.status === "succeeded"} />}
      <Card>
        <CardHeader>
          <CardTitle>Rounds</CardTitle>
          <CardDescription>Each version is compared with the best one before it. A tie is not kept. Rejected ideas are shown to the next round, so it tries something else.</CardDescription>
        </CardHeader>
        <CardContent>
          {!st && <p className="text-sm text-muted-foreground">The first round starts once the starting version is scored.</p>}
          {st && (
            <ol className="relative before:absolute before:bottom-2 before:left-3 before:top-2 before:w-px before:bg-border">
              <li className="relative pb-7 pl-8">
                <span className="absolute left-0 top-0.5 grid size-6 place-items-center rounded-full border bg-background text-xs font-semibold">v{st.original.version}</span>
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <h3 className="font-semibold">Start: v{st.original.version}</h3>
                  <span className="text-sm tabular-nums"><strong>{pct(st.original.score.success_rate)}</strong> verified on train and dev <span className="text-muted-foreground">({st.original.score.successes ?? "?"} of {st.original.score.finished})</span></span>
                </div>
                <Button size="sm" variant="ghost" className="mt-2" onClick={() => go(routes.run(st.original.run_id))}>Open the run it learns from</Button>
              </li>
              {st.rounds.map((r: any) => <Round key={r.round} r={r} />)}
              {st.current && (
                <li className="relative pb-0 pl-8">
                  <span className="absolute left-0 top-0.5 grid size-6 place-items-center rounded-full border border-primary/40 bg-background text-primary"><Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" /></span>
                  <h3 className="font-semibold">Round {st.round}: v{st.current.version}</h3>
                  <p className="mt-1.5 max-w-3xl text-sm">{st.current.rationale}</p>
                  <p className="mt-1 text-xs text-muted-foreground">Rehearsing on train and dev{progress ? `: ${progress}` : ""}.</p>
                </li>
              )}
            </ol>
          )}
        </CardContent>
      </Card>
      {j?.result?.models && <div className="mt-6"><ModelsByRole models={j.result.models} what="fix loop" /></div>}
    </>
  );
}
