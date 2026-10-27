"use client";

import { CircleAlert, CircleCheck, CircleX, LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/* The landing page's showcases: small scripted scenes styled like the console. They are illustrations with example
   content, not connected to a server. Each plays only while it is on screen, pauses while the pointer is over it,
   and with reduced motion shows its finished state and no animation. */

function prefersStill() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Steps 0..steps-1 on a timer, then round again. `delays[i]` is how long step i stays (ms). Before it starts, and
 * with reduced motion, it rests on the last step, the finished scene. */
function useScene(delays: number[]) {
  const ref = useRef<HTMLDivElement>(null);
  const [step, setStep] = useState(delays.length - 1);
  const [visible, setVisible] = useState(false);
  const [held, setHeld] = useState(false);
  const [loops, setLoops] = useState(0);
  const [still, setStill] = useState(true);
  const started = useRef(false);
  useEffect(() => {
    setStill(prefersStill());
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { threshold: 0.35 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  useEffect(() => {
    if (still || !visible || started.current) return;
    started.current = true; // the first time it comes into view, play from the start
    setStep(0);
  }, [still, visible]);
  const delay = delays[step] ?? 1000;
  const last = delays.length - 1;
  useEffect(() => {
    if (still || !visible || held || !started.current) return;
    const t = setTimeout(() => {
      if (step < last) setStep(step + 1);
      else {
        setStep(0);
        setLoops((n) => n + 1);
      }
    }, delay);
    return () => clearTimeout(t);
  }, [step, visible, held, still, delay, last]);
  return { ref, step, loops, held, hold: { onMouseEnter: () => setHeld(true), onMouseLeave: () => setHeld(false) } };
}

function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={cn("font-mono text-[12px] leading-relaxed", className)}>{children}</div>;
}

/** A small window that frames a scene: a title bar with a label, then the content. */
function Pane({ label, aside, children, className = "" }: { label: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cn("overflow-hidden rounded-lg border bg-card shadow-[0_10px_28px_-14px_rgb(0_0_0/0.55)]", className)}>
      <div className="flex items-center gap-2 border-b px-3 py-1.5 text-[11px] text-muted-foreground">
        <span className="flex gap-1" aria-hidden="true">
          <i className="size-1.5 rounded-full bg-muted-foreground/35" /><i className="size-1.5 rounded-full bg-muted-foreground/35" /><i className="size-1.5 rounded-full bg-muted-foreground/35" />
        </span>
        <span className="truncate font-mono">{label}</span>
        {aside && <span className="ml-auto shrink-0">{aside}</span>}
      </div>
      <div className="p-3">{children}</div>
    </div>
  );
}

/** Shown in a pane's title bar while the pointer holds the scene. */
function Held({ on }: { on: boolean }) {
  return <span className={cn("font-mono text-[10px] transition-opacity", on ? "opacity-100" : "opacity-0")} aria-hidden="true">paused</span>;
}

/** Two-way switch for a scene, in a pane's title bar. */
function Switch<T extends string>({ value, options, onChange, label }: { value: T; options: [T, string][]; onChange: (v: T) => void; label: string }) {
  return (
    <span role="radiogroup" aria-label={label} className="inline-flex rounded-md border p-0.5">
      {options.map(([v, text]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v} onClick={() => onChange(v)} className={cn("rounded px-1.5 py-px font-sans text-[10px] transition-colors", value === v ? "bg-primary text-primary-foreground" : "hover:text-foreground")}>
          {text}
        </button>
      ))}
    </span>
  );
}

/** Rows that are always laid out (so the card never changes height) and fade in as the scene reaches them. */
function Reveal({ on, children, className = "" }: { on: boolean; children: ReactNode; className?: string }) {
  return <div className={cn("transition-all duration-500", on ? "translate-y-0 opacity-100" : "translate-y-1 opacity-0", className)}>{children}</div>;
}

/* ---------------------------------------------------------------------------------------------- World Compiler */

const PHASES = ["Read the source", "Research real use", "Plan the runtime", "Start the sandbox", "Find the API", "Seed fictional data", "Choose agent tools", "Write jobs", "Validate", "Publish"];
const PHASE_LOG = [
  "inspector · read docker-compose.yml",
  "planner · 3 services, PostgreSQL 16",
  "runtime · gitea healthy in 41 s",
  "explorer · 212 endpoints from /swagger.v1.json",
  "seeder · 6 users, 14 repositories, 38 issues",
  "toolsmith · 18 tools across 3 roles",
  "author · 24 jobs, each passable and failable",
  "validator · 24 of 24 jobs proven",
  "published · world v3",
];

export function CompilerScene() {
  const s = useScene([...PHASES.map(() => 650), 2600]);
  const done = Math.min(s.step, PHASES.length);
  return (
    <div ref={s.ref} {...s.hold}>
      <Pane label="world build · gitea" aside={<span className="flex items-center gap-2"><Held on={s.held} /><span className="tabular-nums">{done === PHASES.length ? "published" : `${done} of ${PHASES.length}`}</span></span>} className="mx-auto max-w-xl">
        <ol className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-[12px] sm:grid-cols-3">
          {PHASES.map((p, i) => (
            <li key={p} className="flex min-w-0 items-center gap-2">
              {i < done ? (
                <CircleCheck className="size-3.5 shrink-0 text-success" />
              ) : i === done ? (
                <span className="grid size-3.5 shrink-0 place-items-center"><span className="size-2 animate-pulse rounded-full bg-primary shadow-[0_0_8px_var(--primary)]" /></span>
              ) : (
                <span className="size-3.5 shrink-0 rounded-full border border-muted-foreground/35" />
              )}
              <span className={cn("truncate transition-colors", i < done ? "" : i === done ? "font-medium" : "text-muted-foreground")}>{p}</span>
            </li>
          ))}
        </ol>
        <div className="mt-3 h-1 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-linear-to-r from-success to-primary transition-[width] duration-500" style={{ width: `${(done / PHASES.length) * 100}%` }} />
        </div>
        <Mono className="mt-2 truncate text-[11px] text-muted-foreground"><span className="text-primary">›</span> {PHASE_LOG[Math.min(s.step, PHASE_LOG.length - 1)]}</Mono>
      </Pane>
    </div>
  );
}

/* ----------------------------------------------------------------------------------- Customer changes their mind */

function Bubble({ who, children, className = "" }: { who: "customer" | "agent"; children: ReactNode; className?: string }) {
  const agent = who === "agent";
  return (
    <div className={cn("flex items-end gap-2", agent && "flex-row-reverse")}>
      <span className={cn("grid size-5 shrink-0 place-items-center rounded-full border text-[9px] font-semibold", agent ? "border-primary/40 bg-primary/15 text-primary" : "bg-muted text-muted-foreground")} aria-hidden="true">{agent ? "A" : "C"}</span>
      <div className={cn("rounded-2xl border px-2.5 py-1 transition-all duration-500", agent ? "rounded-br-sm border-primary/25 bg-primary/10" : "rounded-bl-sm bg-card", className)}>{children}</div>
    </div>
  );
}

function Typing() {
  return (
    <span className="inline-flex gap-0.5 py-1">
      {[0, 150, 300].map((d) => <i key={d} className="size-1 animate-bounce rounded-full bg-muted-foreground" style={{ animationDelay: `${d}ms` }} />)}
    </span>
  );
}

export function CustomerScene() {
  const s = useScene([1100, 900, 1300, 1600, 900, 3200]);
  const changed = s.step >= 3;
  return (
    <div ref={s.ref} {...s.hold} className="mx-auto max-w-sm space-y-1.5 text-[12px]">
      <Bubble who="customer" className={cn(changed && "text-muted-foreground line-through decoration-muted-foreground/60")}>Refund order 4182, please.</Bubble>
      <Reveal on={s.step >= 1}><Bubble who="agent">{s.step === 1 ? <Typing /> : changed ? <span className="text-muted-foreground">Looking up order 4182…</span> : "Looking up order 4182…"}</Bubble></Reveal>
      <Reveal on={changed} className="flex items-center gap-2 px-7 text-[10px] text-warning">
        <span className="h-px flex-1 bg-warning/30" /><span className="rounded-full border border-warning/40 bg-warning/10 px-2 py-px font-medium">request changed · v2</span><span className="h-px flex-1 bg-warning/30" />
      </Reveal>
      <Reveal on={changed}><Bubble who="customer">Actually, make it store credit instead.</Bubble></Reveal>
      <Reveal on={s.step >= 4}>
        <Bubble who="agent">{s.step === 4 ? <Typing /> : <span className="inline-flex items-center gap-1.5"><CircleCheck className="size-3 shrink-0 text-success" />$40 store credit added, no refund.</span>}</Bubble>
      </Reveal>
    </div>
  );
}

/* ----------------------------------------------------------------------------------------- Failures on purpose */

type Style = "careful" | "blind";

export function FaultScene() {
  const s = useScene([900, 1100, 1100, 3000]);
  const [chosen, setChosen] = useState<Style | null>(null);
  // until someone picks, the two agents take turns, one per round
  const style: Style = chosen ?? (s.loops % 2 ? "blind" : "careful");
  const careful = style === "careful";
  return (
    <div ref={s.ref} {...s.hold}>
      <Pane label="episode · tool calls" aside={<Switch label="Agent" value={style} onChange={setChosen} options={[["careful", "checks first"], ["blind", "blind retry"]]} />} className="mx-auto max-w-sm">
        <Mono className="space-y-2">
          <div className="flex items-center gap-1.5">
            <span className="w-8 shrink-0 text-muted-foreground">POST</span><span className="truncate">/refunds</span>
            {s.step === 0 ? (
              <LoaderCircle className="ml-auto size-3.5 shrink-0 animate-spin text-muted-foreground" />
            ) : (
              <span className="ml-auto shrink-0 rounded border border-destructive/40 bg-destructive/10 px-1.5 text-[11px] text-destructive">timeout · injected</span>
            )}
          </div>
          <Reveal on={s.step >= 2} className="flex items-center gap-1.5">
            <span className="w-8 shrink-0 text-muted-foreground">{careful ? "GET" : "POST"}</span><span className="truncate">{careful ? "/refunds?order=4182" : "/refunds"}</span>
            <span className="ml-auto shrink-0 rounded border px-1.5 text-[11px] text-muted-foreground">{careful ? "1 found" : "201 created"}</span>
          </Reveal>
          <Reveal on={s.step >= 3} className={cn("flex items-center gap-2 border-t pt-2", careful ? "text-success" : "text-destructive")}>
            {careful ? <CircleCheck className="size-3.5 shrink-0" /> : <CircleX className="size-3.5 shrink-0" />}
            <span className="truncate">{careful ? "already refunded, no retry" : "2 refunds in the database"}</span>
          </Reveal>
        </Mono>
      </Pane>
    </div>
  );
}

/* ------------------------------------------------------------------------------------ Verified in the database */

const EPISODES = [
  { id: "ep_0193", count: 1, checks: [true, true, true] },
  { id: "ep_0194", count: 2, checks: [true, false, false] }, // the agent said "done" twice over a blind retry
];
const CHECKS = ["Goal reached", "No duplicate refund", "Claim matches records"];

export function VerifyScene() {
  const s = useScene([700, 900, 700, 550, 550, 2800]);
  const ep = EPISODES[s.loops % 2];
  return (
    <div ref={s.ref} {...s.hold} className="mx-auto grid max-w-2xl items-center gap-3 sm:grid-cols-[1.25fr_1fr]">
      <Pane label={`check · read-only · ${ep.id}`} aside={<Held on={s.held} />}>
        <Mono className="grid grid-cols-[auto_1fr] gap-x-3">
          <span className="select-none text-right text-muted-foreground/50" aria-hidden="true">1<br />2</span>
          <span><span className="text-primary">SELECT</span> count(*) <span className="text-primary">FROM</span> refunds<br /><span className="text-primary">WHERE</span> order_id = 4182;</span>
        </Mono>
        <div className="mt-2 flex items-center gap-1.5 border-t pt-2 font-mono text-[11px] text-muted-foreground">
          {s.step < 2 ? (
            <><LoaderCircle className={cn("size-3 animate-spin", s.step === 0 && "opacity-0")} /> {s.step === 0 ? "" : "reading the sandbox database"}</>
          ) : (
            <>→ count = <span className={ep.count === 1 ? "text-foreground" : "text-destructive"}>{ep.count}</span>, read after the episode</>
          )}
        </div>
      </Pane>
      <ul className="space-y-1.5 text-[12px]">
        {CHECKS.map((check, i) => {
          const shown = s.step >= 3 + i;
          const pass = ep.checks[i];
          return (
            <li key={check} className={cn("flex items-center gap-2 rounded-md border px-2.5 py-1.5 transition-colors duration-500", !shown ? "border-border bg-transparent" : pass ? "border-success/25 bg-success/10" : "border-destructive/30 bg-destructive/10")}>
              {!shown ? <span className="size-3.5 shrink-0 rounded-full border border-muted-foreground/35" /> : pass ? <CircleCheck className="size-3.5 shrink-0 text-success" /> : <CircleX className="size-3.5 shrink-0 text-destructive" />}
              <span className="truncate">{check}</span>
              <span className={cn("ml-auto font-mono text-[11px]", !shown ? "text-muted-foreground" : pass ? "text-success" : "text-destructive")}>{!shown ? "…" : pass ? "pass" : "fail"}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------------------------------- Fix my agent */

const DIFF: ["-" | "+", string][] = [
  ["-", "Retry any refund call that fails."],
  ["+", "Before retrying, check whether the refund already exists."],
  ["+", "Re-read the latest customer message before acting."],
];

export function ImproveScene() {
  const s = useScene([700, 800, 800, 900, 3000]);
  const [chosen, setChosen] = useState<"v1" | "v2" | null>(null);
  const version = chosen ?? (s.step >= 4 ? "v2" : "v1");
  const score = { v1: 62, v2: 91 };
  return (
    <div ref={s.ref} {...s.hold} className="mx-auto grid max-w-2xl items-center gap-3 sm:grid-cols-[1.45fr_1fr]">
      <Pane label="agent instructions" aside={<span className="flex items-center gap-2"><Held on={s.held} /><span className="rounded border px-1.5 font-mono">v1 → v2</span></span>}>
        <Mono className="space-y-1">
          {DIFF.map(([sign, line], i) => (
            <Reveal key={line} on={chosen !== null || s.step >= i + 1} className={cn("flex gap-2 rounded px-2 py-0.5", sign === "-" ? "bg-destructive/10 text-destructive" : "bg-success/10 text-success")}>
              <span className="select-none" aria-hidden="true">{sign === "-" ? "−" : "+"}</span><span className="min-w-0 md:truncate">{line}</span>
            </Reveal>
          ))}
        </Mono>
        <div className="mt-2.5 truncate text-[11px] text-muted-foreground">Round 2: verified more, no new rule broken, kept</div>
      </Pane>
      <div className="rounded-lg border bg-card p-3 text-[12px]">
        <div className="flex items-center justify-between gap-2">
          <span className="text-muted-foreground">Held-out jobs</span>
          <Switch label="Agent version" value={version} onChange={setChosen} options={[["v1", "v1"], ["v2", "v2"]]} />
        </div>
        <div className="mt-2 font-heading text-2xl font-bold tabular-nums">{score[version]}%</div>
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
          <div className={cn("h-full rounded-full transition-[width] duration-700", version === "v2" ? "bg-success" : "bg-warning")} style={{ width: `${score[version]}%` }} />
        </div>
        <div className="mt-1.5 text-[11px] text-muted-foreground">verified success, jobs neither version has seen</div>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------------------------- Every step on the record */

// name, depth in the tree, where its bar starts and how wide it is (percent of the episode), colour
const SPANS: [string, number, number, number, string][] = [
  ["episode · changed-mind", 0, 0, 100, "bg-primary/60"],
  ["llm · nemotron-3-super", 1, 3, 34, "bg-primary"],
  ["tool · create_refund", 1, 39, 20, "bg-info"],
  ["tool · list_refunds", 1, 61, 16, "bg-info"],
  ["verifier · 3 passed", 1, 82, 16, "bg-success"],
];
const TICKS = 12;
const EPISODE_S = 4.8;

export function TraceScene() {
  const s = useScene([...Array.from({ length: TICKS }, () => 260), 2600]);
  const t = (Math.min(s.step + 1, TICKS) / TICKS) * 100; // percent of the episode recorded so far
  return (
    <div ref={s.ref} {...s.hold}>
      <Pane label="trace · rehearse-agent" aside={<span className="font-mono tabular-nums">{((t / 100) * EPISODE_S).toFixed(1)} s</span>} className="mx-auto max-w-sm">
        <div className="space-y-1.5 font-mono text-[11px]">
          {SPANS.map(([name, depth, from, width, colour]) => {
            const grown = Math.max(0, Math.min(width, t - from));
            return (
              <div key={name} className="group/span grid grid-cols-[minmax(0,2.4fr)_1fr] items-center gap-2.5">
                <span className={cn("truncate transition-colors group-hover/span:text-foreground", depth ? "text-muted-foreground" : "", grown === 0 && "opacity-50")} style={{ paddingLeft: depth * 10 }}>{name}</span>
                <span className="relative h-1.5 rounded-full bg-muted">
                  <span className={cn("absolute inset-y-0 rounded-full transition-[width] duration-300 ease-linear group-hover/span:ring-2 group-hover/span:ring-foreground/30", colour)} style={{ left: `${from}%`, width: `${grown}%` }} />
                </span>
              </div>
            );
          })}
        </div>
      </Pane>
    </div>
  );
}

/* ------------------------------------------------------------------------------------------ Readiness verdict */

type Tone = "go" | "stop" | "cue";
type Measure = { title: string; body: string; v1: [string, Tone, string]; v2: [string, Tone, string] };

// value shown, how it reads, and one piece of evidence behind it
const MEASURES: Measure[] = [
  { title: "Verified success", body: "The outcome exists in your application's own records.", v1: ["71%", "stop", "ep_0412 · the customer switched to store credit; none was created."], v2: ["94%", "go", "45 of 48 outcomes found in the application's records."] },
  { title: "Rule violations", body: "Anything your checks say must never happen.", v1: ["2", "stop", "ep_0388 · refunded order 4183, which belongs to another customer."], v2: ["0", "go", "No episode touched an account outside its job."] },
  { title: "Duplicate side effects", body: "A second refund, email or shipment from a blind retry.", v1: ["3", "stop", "ep_0391 · retried POST /refunds after a timeout; two refunds exist."], v2: ["0", "go", "Checked for an existing refund before every retry."] },
  { title: "Recovery after faults", body: "Finished correctly after a request failed or timed out.", v1: ["5 of 9", "stop", "4 episodes stopped after an injected timeout."], v2: ["9 of 9", "go", "Finished correctly after all 9 injected faults."] },
  { title: "False “done” claims", body: "The agent said it finished; the records say otherwise.", v1: ["4", "stop", "ep_0407 · told the customer “done”; the order is still open."], v2: ["0", "go", "Every “done” matched the records."] },
  { title: "Unneeded questions", body: "Interruptions beyond what the job required.", v1: ["6", "cue", "ep_0402 · asked for the order number twice."], v2: ["1", "go", "One extra question in 48 episodes."] },
];

const TONE_ICON = { go: CircleCheck, stop: CircleX, cue: CircleAlert };
const TONE_TEXT = { go: "text-success", stop: "text-destructive", cue: "text-warning" };

export function VerdictReport() {
  const ref = useRef<HTMLDivElement>(null);
  const [agent, setAgent] = useState<"v1" | "v2">("v1");
  const [picked, setPicked] = useState(false); // once someone chooses, the report stops switching by itself
  const [held, setHeld] = useState(false);
  const [row, setRow] = useState(2);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { threshold: 0.3 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  useEffect(() => {
    if (picked || held || !visible || prefersStill()) return;
    const t = setTimeout(() => setAgent((a) => (a === "v1" ? "v2" : "v1")), 5200);
    return () => clearTimeout(t);
  }, [agent, picked, held, visible]);
  const ready = agent === "v2";
  const m = MEASURES[row];
  const [, tone, evidence] = m[agent];
  return (
    <div ref={ref} onMouseEnter={() => setHeld(true)} onMouseLeave={() => setHeld(false)} className="mx-auto max-w-6xl overflow-hidden rounded-2xl border bg-card 2xl:max-w-7xl shadow-[inset_0_1px_0_0_rgb(255_255_255/0.05),0_40px_80px_-40px_rgb(0_0_0/0.6)]">
      <div className="flex flex-wrap items-center gap-3 border-b px-4 py-2.5 text-xs text-muted-foreground">
        <span className="flex gap-1" aria-hidden="true"><i className="size-2 rounded-full bg-muted-foreground/35" /><i className="size-2 rounded-full bg-muted-foreground/35" /><i className="size-2 rounded-full bg-muted-foreground/35" /></span>
        <span className="font-mono">readiness · support-agent on Gitea · 48 held-out episodes</span>
        <span role="tablist" aria-label="Agent version" className="ml-auto inline-flex rounded-lg border p-0.5">
          {(["v1", "v2"] as const).map((v) => (
            <button key={v} type="button" role="tab" aria-selected={agent === v} onClick={() => { setPicked(true); setAgent(v); }} className={cn("rounded-md px-3 py-1 text-xs font-medium transition-colors", agent === v ? "bg-primary text-primary-foreground" : "hover:text-foreground")}>
              Agent {v}
            </button>
          ))}
        </span>
      </div>

      <div className="grid md:grid-cols-[260px_minmax(0,1fr)]">
        <div className="flex flex-col justify-between gap-6 border-b p-6 md:border-r md:border-b-0">
          <div>
            <div className="text-sm text-muted-foreground">Verdict</div>
            <div className={cn("mt-2 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm font-semibold transition-colors", ready ? "border-success/40 bg-success/10 text-success" : "border-destructive/40 bg-destructive/10 text-destructive")}>
              {ready ? <CircleCheck className="size-4" /> : <CircleX className="size-4" />} {ready ? "Ready to pilot" : "Not yet"}
            </div>
            <p className="mt-4 text-sm text-muted-foreground">{ready ? "Every measure is inside the bar for a supervised pilot." : "Duplicate refunds and false “done” claims stop it short of a pilot."}</p>
          </div>
          <div>
            <div className="font-heading text-5xl font-bold tabular-nums">{MEASURES[0][agent][0]}</div>
            <div className="mt-1 text-sm text-muted-foreground">verified success</div>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted"><div className={cn("h-full rounded-full transition-[width] duration-700", ready ? "bg-success" : "bg-destructive")} style={{ width: MEASURES[0][agent][0] }} /></div>
            <p className="mt-3 text-xs text-muted-foreground">A pilot needs 90% verified success, no rule violations and no duplicate side effects.</p>
          </div>
        </div>

        <div className="min-w-0">
          <ul>
            {MEASURES.map((x, i) => {
              const [value, t] = x[agent];
              const Icon = TONE_ICON[t];
              return (
                <li key={x.title} className="border-b last:border-b-0">
                  <button type="button" aria-pressed={row === i} onClick={() => setRow(i)} className={cn("grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 px-5 py-3 text-left transition-colors hover:bg-accent/50", row === i && "bg-accent/60")}>
                    <Icon className={cn("size-4 transition-colors", TONE_TEXT[t])} />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium">{x.title}</span>
                      <span className="block truncate text-xs text-muted-foreground">{x.body}</span>
                    </span>
                    <span className={cn("font-mono text-sm tabular-nums transition-colors", TONE_TEXT[t])}>{value}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          <div className="flex items-start gap-3 border-t bg-background/40 px-5 py-4 text-sm">
            <span className="shrink-0 text-muted-foreground">Evidence</span>
            <span className={cn("min-w-0 font-mono text-[13px]", TONE_TEXT[tone])}>{evidence}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
