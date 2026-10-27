"use client";

import { Pause, Play, RotateCcw, Square } from "lucide-react";
import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Inspector } from "@/components/inspector";
import { ActivityFeed, ModelsByRole, NowCaption, PageHeader, PhaseStepper, StatusBadge } from "@/components/rh";
import { post, useEvents, useResource, type RhEvent } from "../api";
import { go, routes } from "../nav";
import type { Selection } from "../stage/Stage";
import { explainProblem, nextStep } from "../problems";

const Stage = dynamic(() => import("../stage/Stage").then((m) => m.Stage), { ssr: false });

export function Build({ jobId }: { jobId: string }) {
  const job = useResource<any>(`/v1/jobs/${jobId}`, 4000);
  const [round, setRound] = useState(0);  // the stream closes when a job ends; a restart opens it again
  const { events } = useEvents(`/v1/jobs/${jobId}/events?restart=${round}`);
  const [beat, setBeat] = useState<RhEvent | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const phases = useMemo(() => {
    const done = events.filter((e) => e.type === "compiler.phase.completed").map((e) => e.data?.phase);
    const started = events.filter((e) => e.type === "compiler.phase.started").map((e) => e.data?.phase);
    return { done, active: started[started.length - 1] };
  }, [events]);
  const j = job.data;
  const failed = j?.status === "failed" || j?.status === "cancelled";
  const next = nextStep(j?.status === "cancelled" ? "stopped on request" : j?.error);
  const command = async (c: string) => {
    await post(`/v1/jobs/${jobId}/commands`, { command: c });
    toast(c === "retry" ? "Restarting from the last saved step" : `${c === "stop" ? "Stop" : c === "pause" ? "Pause" : "Resume"} requested`);
    if (c === "retry") setRound((r) => r + 1);
    job.reload();
  };
  const pick = (s: Selection | null) => setSelection(s);
  return (
    <>
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-3">World build {j && <StatusBadge status={j.status} />}</span>}
        description="The World Compiler reads the application, runs it in an isolated sandbox, and proves each scenario can be passed and can be failed. Click anyone in the room to see exactly what they are doing."
        actions={
          <>
            {j?.status === "running" && <Button variant="outline" onClick={() => command("pause")}><Pause /> Pause</Button>}
            {j?.status === "paused" && <Button variant="outline" onClick={() => command("resume")}><Play /> Resume</Button>}
            {["running", "queued", "paused"].includes(j?.status) && <Button variant="outline" className="text-destructive" onClick={() => command("stop")}><Square /> Stop</Button>}
            {failed && <Button variant={next.restart ? "default" : "outline"} onClick={() => command("retry")}><RotateCcw /> Restart build</Button>}
            {failed && !next.restart && <Button onClick={() => go(routes.applications)}>Build new version</Button>}
            {j?.status === "succeeded" && <Button onClick={() => go(routes.world(j.payload.world_version_id))}>Open the world</Button>}
          </>
        }
      />
      <Card className="mb-4">
        <CardContent className="pt-6">
          <PhaseStepper done={phases.done} active={phases.active} failed={failed} />
          <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted-foreground">
            <span>Attempt {j?.attempts ?? 0}</span>
            <span>Model spend ${(j?.spent_usd ?? 0).toFixed(4)}{j?.tokens ? `, ${Number(j.tokens).toLocaleString()} tokens` : ""}</span>
            <span>{events.filter((e) => e.type === "compiler.tool").length} tool calls</span>
            <span>{events.filter((e) => e.type === "compiler.repair" || e.type === "compiler.submit.rejected").length} repairs and rejections</span>
          </div>
        </CardContent>
      </Card>
      {j?.error && failed && (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>The build stopped</AlertTitle>
          <AlertDescription>{explainProblem(j.error)} {next.text}</AlertDescription>
        </Alert>
      )}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div>
          <Stage events={events} mode="compiler" onBeat={setBeat} onSelect={pick} selected={selection} label="Compiler roles moving between the source, sandbox, API, database, and scenario stations as they use tools" />
          <NowCaption ev={beat} fallback="Waiting for the compiler" />
        </div>
        <ActivityFeed events={events} onPick={(id) => pick({ kind: "actor", id })} height="calc(min(54vw, 60vh) + 70px)" />
      </div>
      {j?.result?.models && <div className="mt-6"><ModelsByRole models={j.result.models} what="build" /></div>}
      <Inspector open={!!selection} onOpenChange={(o) => !o && setSelection(null)} selection={selection} mode="compiler" events={events} />
    </>
  );
}
