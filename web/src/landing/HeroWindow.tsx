"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import type { RhEvent } from "../api";
import { ActivityFeed, NowCaption, PhaseStepper } from "@/components/rh";
import { Inspector } from "@/components/inspector";
import type { Selection } from "../stage/Stage";

const Stage = dynamic(() => import("../stage/Stage").then((m) => m.Stage), { ssr: false });

/** The hero: the console's own build view (phases, 3D room, activity feed) replaying a recorded Gitea build.
 * Every event is real and redacted; only the pace is changed. */
export function HeroWindow({ src = "/replays/gitea-build.json" }: { src?: string }) {
  const [all, setAll] = useState<RhEvent[]>([]);
  const [shown, setShown] = useState<RhEvent[]>([]);
  const [beat, setBeat] = useState<RhEvent | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  useEffect(() => {
    fetch(src).then((r) => (r.ok ? r.json() : { events: [] })).then((d) => setAll(d.events || [])).catch(() => setAll([]));
  }, [src]);
  useEffect(() => {
    if (!all.length) return;
    // most file reads are skipped so hand-offs between roles come quickly
    const story = all.filter((e, i) => e.type !== "compiler.tool" || i % 4 === 0);
    let i = 0;
    const t = setInterval(() => {
      i = i >= story.length ? 0 : i + 1;
      setShown(i === 0 ? [] : story.slice(0, i));
    }, 650);
    return () => clearInterval(t);
  }, [all]);
  const phases = useMemo(() => {
    const done = shown.filter((e) => e.type === "compiler.phase.completed").map((e) => e.data?.phase);
    const started = shown.filter((e) => e.type === "compiler.phase.started").map((e) => e.data?.phase);
    return { done, active: started[started.length - 1] };
  }, [shown]);
  return (
    <div className="overflow-hidden rounded-xl border bg-card shadow-[0_30px_120px_-30px_color-mix(in_srgb,var(--primary)_45%,transparent)]">
      <div className="flex items-center gap-2 border-b px-4 py-2.5">
        <span className="size-2.5 rounded-full bg-[#ff5f57]" /><span className="size-2.5 rounded-full bg-[#febc2e]" /><span className="size-2.5 rounded-full bg-[#28c840]" />
        <span className="ml-3 truncate rounded-md bg-muted px-3 py-0.5 font-mono text-xs text-muted-foreground">rehearsal / applications / gitea / build</span>
        <span className="ml-auto hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex"><span className="size-1.5 animate-pulse rounded-full bg-success" /> replaying a recorded build</span>
      </div>
      <div className="border-b px-4 py-3"><PhaseStepper done={phases.done} active={phases.active} /></div>
      <div className="grid gap-3 p-3 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0">
          <Stage events={shown} mode="compiler" onBeat={setBeat} onSelect={setSelection} selected={selection} height="min(44vw, 470px)" label="Replay of a recorded World Compiler build" />
          <NowCaption ev={beat} fallback="Loading the recording" />
        </div>
        <div className="hidden lg:block"><ActivityFeed events={shown} height="calc(min(44vw, 470px) + 48px)" onPick={(id) => setSelection({ kind: "actor", id })} /></div>
      </div>
      <Inspector open={!!selection} onOpenChange={(o) => !o && setSelection(null)} selection={selection} mode="compiler" events={shown} />
    </div>
  );
}
