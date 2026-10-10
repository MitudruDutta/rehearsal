"use client";

import { useMemo } from "react";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useResource, type RhEvent } from "../api";
import { actorOf, describe, humanTool } from "../describe";
import { COMPILER_TOOL_DESK } from "../stage/model";
import type { Selection } from "../stage/Stage";
import { ActorAvatar, Tone } from "./rh";

/** What a character or desk in the room is doing, in detail. Opens when you click it. */

const ROLE: Record<string, string> = {
  inspector: "Reads the application's source code and reports how it runs, where its state lives, and what work happens in it.",
  builder: "Writes the runtime plan and starts the application in an isolated sandbox with no internet access.",
  builder_repair: "Diagnoses why the application failed to start, from the logs and source, and fixes the runtime plan.",
  seeder: "Creates fictional users and records through the application's own API, then writes the exact steps so they replay from scratch.",
  adapter: "Chooses the tools agents may use, each mapped to a real API operation, and proves every tool works against the seeded data.",
  scenario_designer: "Writes the jobs agents must do and the read-only database checks that decide success, including careless runs that must fail.",
  validation_investigator: "Repairs scenarios that failed validation, using the evidence from their replays.",
  verifier: "Replays every scenario to prove it can be passed and can be failed, and decides each episode from the application's own records.",
  customer: "The simulated customer. Their goals and facts come from the scenario; a model only words their messages.",
};

function Json({ value }: { value: unknown }) {
  return <pre className="max-h-64 overflow-auto rounded-md bg-muted p-2.5 text-xs leading-relaxed">{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</pre>;
}

/** The argument that tells calls apart: the query, path, or pattern. */
function argPreview(args: unknown): string {
  if (args && typeof args === "object") {
    const v = Object.values(args as Record<string, unknown>).find((x) => typeof x === "string" || Array.isArray(x));
    return Array.isArray(v) ? v.join(" ") : String(v ?? JSON.stringify(args));
  }
  return String(args ?? "");
}

function CompilerDetail({ selection, events }: { selection: Selection; events: RhEvent[] }) {
  const mine = useMemo(() => {
    if (selection.kind === "desk") return events.filter((e) => e.type === "compiler.tool" && (COMPILER_TOOL_DESK[e.data?.tool] ?? "Sandbox") === selection.id);
    if (selection.id === "verifier") return events.filter((e) => e.type.startsWith("compiler.validat") || e.type === "world.published");
    return events.filter((e) => e.data?.role === selection.id);
  }, [events, selection]);
  const tools = mine.filter((e) => e.type === "compiler.tool").length;
  const rejected = mine.filter((e) => e.type === "compiler.submit.rejected").length;
  const accepted = mine.filter((e) => e.type === "compiler.submit.accepted").length;
  const latest = [...mine].reverse();
  return (
    <>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="rounded-lg border p-2"><div className="font-heading text-xl font-bold">{tools}</div><div className="text-xs text-muted-foreground">tool calls</div></div>
        <div className="rounded-lg border p-2"><div className="font-heading text-xl font-bold text-success">{accepted}</div><div className="text-xs text-muted-foreground">accepted</div></div>
        <div className="rounded-lg border p-2"><div className="font-heading text-xl font-bold text-destructive">{rejected}</div><div className="text-xs text-muted-foreground">sent back</div></div>
      </div>
      <Separator className="my-4" />
      <h3 className="mb-2 text-sm font-semibold">Timeline, newest first</h3>
      {latest.length === 0 && <p className="text-sm text-muted-foreground">Nothing recorded yet.</p>}
      <Accordion type="multiple" className="w-full">
        {latest.slice(0, 120).map((e) => (
          <AccordionItem key={e.event_id} value={String(e.event_id)}>
            <AccordionTrigger className="py-2.5 text-left text-sm hover:no-underline">
              <span className="flex min-w-0 items-start gap-2">
                {selection.kind === "desk" && <ActorAvatar id={actorOf(e)} className="size-6" />}
                <span className="min-w-0">
                  <span className="line-clamp-2">{describe(e)}</span>
                  {e.type === "compiler.tool" && <span className="block truncate font-mono text-xs font-normal text-muted-foreground">{argPreview(e.data?.args)}</span>}
                  <span className="block text-xs font-normal text-muted-foreground">{new Date(e.created_at).toLocaleTimeString()}</span>
                </span>
              </span>
            </AccordionTrigger>
            <AccordionContent className="space-y-2">
              {e.type === "compiler.tool" && (
                <>
                  <div className="text-xs font-medium text-muted-foreground">Arguments</div>
                  <Json value={e.data?.args ?? e.summary} />
                  {e.data?.result && (<><div className="text-xs font-medium text-muted-foreground">Result (first 600 characters)</div><Json value={e.data.result} /></>)}
                </>
              )}
              {e.type !== "compiler.tool" && <Json value={e.summary} />}
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </>
  );
}

function EpisodeDetail({ selection, episodeId }: { selection: Selection; episodeId: string }) {
  const ep = useResource<any>(`/v1/episodes/${episodeId}`, 3000);
  const e = ep.data;
  if (!e) return <p className="text-sm text-muted-foreground">Loading the episode…</p>;
  const spec = (e.scenario?.actors || []).find((a: any) => a.id === selection.id);
  const actions = (e.actions || []).filter((a: any) => (selection.kind === "desk" ? a.tool === selection.id : a.actor === selection.id));
  const messages = (e.messages || []).filter((m: any) => selection.kind === "actor" && (m.sender === selection.id || m.recipient === selection.id));
  const currentGoal = e.goal_version ?? 1;
  return (
    <div className="space-y-5">
      {spec && (
        <div className="space-y-1.5 text-sm">
          <div><span className="text-muted-foreground">Role </span><span className="font-medium">{spec.role}</span>{spec.can_complete && <Tone tone="info" className="ml-2">can declare done</Tone>}</div>
          <p className="text-muted-foreground">{spec.instructions}</p>
        </div>
      )}
      {selection.id === "customer" && e.scenario?.participant && (
        <div className="space-y-2 text-sm">
          <p>{e.scenario.participant.persona}</p>
          {(e.scenario.participant.facts || []).length > 0 && <ul className="list-disc space-y-1 pl-5 text-muted-foreground">{e.scenario.participant.facts.map((f: string) => <li key={f}>{f}</li>)}</ul>}
          <h3 className="pt-2 text-sm font-semibold">What they want, by version</h3>
          <ol className="space-y-1.5">
            {(e.scenario.goals || []).map((g: any) => (
              <li key={g.version} className={`rounded-md border p-2 ${g.version === currentGoal ? "border-primary bg-primary/10" : ""}`}>
                <span className="font-medium">v{g.version}</span> {g.instruction}
              </li>
            ))}
          </ol>
        </div>
      )}
      {selection.id === "verifier" && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold">Independent checks</h3>
          {(e.oracle?.check_results || []).length === 0 && <p className="text-sm text-muted-foreground">The verifier runs when the episode ends.</p>}
          {(e.oracle?.check_results || []).map((c: any) => (
            <div key={c.id} className="rounded-md border p-2.5 text-sm">
              <div className="flex items-center justify-between gap-2"><span className="font-medium">{c.description}</span><Tone tone={c.passed ? "go" : "stop"}>{c.passed ? "passed" : "failed"}</Tone></div>
              <div className="mt-1 text-xs text-muted-foreground">{c.role === "constraint" ? "must never fail" : "goal"} · observed {JSON.stringify(c.actual)} {c.op} {JSON.stringify(c.expected)}{c.error ? ` · ${c.error}` : ""}</div>
            </div>
          ))}
        </div>
      )}
      {(selection.kind === "desk" || (selection.id !== "customer" && selection.id !== "verifier")) && (
        <div>
          <h3 className="mb-2 text-sm font-semibold">{selection.kind === "desk" ? `Every call to ${humanTool(selection.id)}` : "Actions, newest first"}</h3>
          {actions.length === 0 && <p className="text-sm text-muted-foreground">No actions yet.</p>}
          <Accordion type="multiple">
            {[...actions].reverse().map((a: any) => (
              <AccordionItem key={a.id} value={a.id}>
                <AccordionTrigger className="py-2.5 text-left text-sm hover:no-underline">
                  <span className="flex min-w-0 flex-1 items-center gap-2">
                    {selection.kind === "desk" && <ActorAvatar id={a.actor} className="size-6" />}
                    <span className="truncate font-medium">{humanTool(a.tool)}</span>
                    <Tone tone={a.status === "SUCCEEDED" ? "go" : a.status === "UNKNOWN" ? "cue" : "stop"}>{a.status.toLowerCase()}</Tone>
                    {a.observed_goal_version < a.goal_version && <Tone tone="cue">saw v{a.observed_goal_version} of v{a.goal_version}</Tone>}
                  </span>
                </AccordionTrigger>
                <AccordionContent className="space-y-2">
                  <div className="text-xs font-medium text-muted-foreground">Arguments</div>
                  <Json value={a.args} />
                  <div className="text-xs font-medium text-muted-foreground">What the agent saw</div>
                  <Json value={a.visible_result} />
                  {a.fault && <p className="text-xs text-warning">Fault injected: {a.fault.replace(/_/g, " ")}. The application may have applied the change even though the agent got no answer.</p>}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>
      )}
      {messages.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold">Messages</h3>
          <ul className="space-y-2">
            {messages.map((m: any) => (
              <li key={m.id} className="rounded-md border p-2.5 text-sm"><span className="font-medium">{m.sender}</span> <span className="text-muted-foreground">to</span> <span className="font-medium">{m.recipient}</span><p className="mt-1">{m.text}</p></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function Inspector({
  open,
  onOpenChange,
  selection,
  mode,
  events,
  episodeId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  selection: Selection | null;
  mode: "compiler" | "episode";
  events: RhEvent[];
  episodeId?: string | null;
}) {
  const title = selection ? (selection.kind === "desk" ? humanTool(selection.id) : selection.id.replace(/_/g, " ")) : "";
  const latest = selection ? [...events].reverse().find((e) => (selection.kind === "desk" ? e.data?.tool === selection.id || COMPILER_TOOL_DESK[e.data?.tool] === selection.id : actorOf(e) === selection.id)) : undefined;
  return (
    <Sheet open={open && !!selection} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 p-0 sm:max-w-xl">
        {selection && (
          <>
            <SheetHeader className="border-b p-5">
              <div className="flex items-center gap-3">
                {selection.kind === "actor" ? <ActorAvatar id={selection.id} className="size-11" /> : <span className="grid size-11 place-items-center rounded-md bg-muted text-lg">▦</span>}
                <div className="min-w-0">
                  <SheetTitle className="capitalize">{title}</SheetTitle>
                  <SheetDescription>{selection.kind === "desk" ? (mode === "compiler" ? "Workstation: every tool call made here." : "Every call agents made to this tool.") : ROLE[selection.id] ?? "An agent under test in this episode."}</SheetDescription>
                </div>
              </div>
              {latest && (
                <div className="mt-3 rounded-lg border border-primary/40 bg-primary/10 p-3 text-sm">
                  <div className="text-xs font-semibold text-primary">Right now</div>
                  <div className="mt-0.5">{describe(latest)}</div>
                </div>
              )}
            </SheetHeader>
            <ScrollArea className="h-[calc(100vh-190px)]">
              <div className="p-5">
                {mode === "compiler" ? <CompilerDetail selection={selection} events={events} /> : episodeId ? <EpisodeDetail selection={selection} episodeId={episodeId} /> : <p className="text-sm text-muted-foreground">Select an episode first.</p>}
              </div>
            </ScrollArea>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
