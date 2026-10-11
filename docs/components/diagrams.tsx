import type { ReactNode } from "react";

/* Diagrams are drawn with real text in boxes, in the theme's own colours, so they read in both themes, at any
   width, and to a screen reader. Each has a caption that says the same thing in a sentence. */

function Frame({ caption, children }: { caption: string; children: ReactNode }) {
  return (
    <figure className="not-prose my-7 max-w-(--rh-column)">
      <div className="rounded-xl border bg-muted/40 p-4 sm:p-5">{children}</div>
      <figcaption className="mt-2 text-sm leading-6 text-muted-foreground">{caption}</figcaption>
    </figure>
  );
}

function Box({ title, children, tone = "plain", className = "" }: { title: string; children?: ReactNode; tone?: "plain" | "accent" | "go" | "quiet"; className?: string }) {
  const tones = {
    plain: "border-border bg-card",
    accent: "border-primary/45 bg-card",
    go: "border-success/40 bg-card",
    quiet: "border-dashed border-border bg-transparent",
  };
  return (
    <div className={`rounded-lg border p-3 ${tones[tone]} ${className}`}>
      <div className="font-heading text-sm font-semibold leading-5 text-foreground">{title}</div>
      {children && <div className="mt-1 text-[13px] leading-5 text-muted-foreground">{children}</div>}
    </div>
  );
}

/** An arrow between two boxes. It points down in a column and right in a row. */
function Arrow({ label, dir = "down" }: { label?: string; dir?: "down" | "right" | "both" }) {
  return (
    <div className={`flex items-center justify-center gap-1.5 text-xs text-muted-foreground ${dir === "right" ? "px-1" : "py-1.5"}`}>
      <svg viewBox="0 0 16 16" aria-hidden="true" className={`size-4 shrink-0 ${dir === "right" ? "-rotate-90" : ""}`} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        {dir === "both" ? <path d="M8 2v12M4.5 5.5 8 2l3.5 3.5M4.5 10.5 8 14l3.5-3.5" /> : <path d="M8 2v12M4.5 10.5 8 14l3.5-3.5" />}
      </svg>
      {label && <span>{label}</span>}
    </div>
  );
}

/** A practice world in one picture: what goes in, what the world holds, who acts in it, and who decides. */
export function WorldDiagram() {
  return (
    <Frame caption="Rehearsal builds a practice world from your application. Your agent works in the world through tools. Checks read the application's own database to decide each outcome.">
      <div className="grid gap-0 md:grid-cols-[1fr_auto_1.6fr] md:items-center">
        <div className="grid gap-2">
          <Box title="Your application">Public source at a pinned commit, and its published container images.</Box>
          <Box title="Your policies" tone="quiet">Rules the agent must follow, in plain words.</Box>
        </div>
        <div className="md:hidden"><Arrow label="World Compiler" /></div>
        <div className="hidden md:block"><Arrow label="World Compiler" dir="right" /></div>
        <div className="rounded-xl border border-primary/45 bg-card p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="font-heading text-sm font-semibold text-foreground">Practice world</div>
            <span className="rounded-md border px-1.5 py-px text-[11px] text-muted-foreground">sandbox, no internet</span>
          </div>
          <div className="mt-2.5 grid gap-2 sm:grid-cols-2">
            <Box title="The application, running">The same code and the same database engine.</Box>
            <Box title="Fictional data">Customers, records and history that Rehearsal makes up.</Box>
            <Box title="Tools">The actions an agent may take, mapped to the real API.</Box>
            <Box title="Jobs with checks">Tasks to attempt, each with read-only database checks.</Box>
          </div>
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <Box title="Simulated customer">States the request, and can change it part-way.</Box>
        <Box title="Your agent" tone="accent">Reads observations, calls tools, says when it is done.</Box>
        <Box title="Verdict" tone="go">Verified, not achieved, or rule violated. No model decides it.</Box>
      </div>
    </Frame>
  );
}

function Stage({ n, title, children, tone = "plain" }: { n: number; title: string; children: ReactNode; tone?: "plain" | "accent" | "go" }) {
  return (
    <li className="flex gap-3">
      <span className={`mt-0.5 grid size-6 shrink-0 place-items-center rounded-full border font-mono text-xs font-semibold ${tone === "go" ? "border-success/40 text-success" : tone === "accent" ? "border-primary/50 text-link" : "text-muted-foreground"}`}>
        {n}
      </span>
      <div className="min-w-0 pb-3.5">
        <div className="font-heading text-sm font-semibold text-foreground">{title}</div>
        <div className="text-[13px] leading-5 text-muted-foreground">{children}</div>
      </div>
    </li>
  );
}

/** The life of one episode, including a changed request and an action whose result is unknown. */
export function EpisodeDiagram() {
  return (
    <Frame caption="One episode: one agent attempts one job in a fresh copy of the world. The checks at the end read the database; what the agent says about its own work is not evidence.">
      <ol className="grid gap-0 md:grid-cols-2 md:gap-x-8">
        <Stage n={1} title="Reset">The world returns to its saved starting state, so every episode starts the same.</Stage>
        <Stage n={2} title="Request">The simulated customer states what they want.</Stage>
        <Stage n={3} title="Turns" tone="accent">The agent reads an observation and takes one action. This repeats.</Stage>
        <Stage n={4} title="The request changes">On some jobs the customer changes their mind after work has started.</Stage>
        <Stage n={5} title="Something goes wrong">On some jobs a tool call fails, or its result comes back unknown.</Stage>
        <Stage n={6} title="The agent finishes">It says it is done, or it runs out of turns or time.</Stage>
        <Stage n={7} title="Checks" tone="go">Read-only queries ask the application&apos;s database what is true now.</Stage>
        <Stage n={8} title="Verdict" tone="go">Verified, not achieved, or rule violated, with each check&apos;s result.</Stage>
      </ol>
    </Frame>
  );
}

/** The parts of a server you run yourself. */
export function ArchitectureDiagram() {
  return (
    <Frame caption="A self-hosted server: the API serves the console and takes requests, PostgreSQL holds the data and the job queue, workers take jobs from the queue, and each world runs in its own sandbox.">
      <div className="grid gap-2 sm:grid-cols-4">
        <Box title="Console" tone="quiet">Browser</Box>
        <Box title="CLI" tone="quiet">Terminal</Box>
        <Box title="Python SDK" tone="quiet">Scripts and CI</Box>
        <Box title="MCP server" tone="quiet">AI assistants</Box>
      </div>
      <Arrow label="HTTPS, with a sign-in or an API key" />
      <Box title="API" tone="accent">One service on port 7800. It also serves the console.</Box>
      <Arrow dir="both" />
      <Box title="PostgreSQL">Applications, worlds, runs, results, and the job queue.</Box>
      <Arrow dir="both" label="workers take jobs and report back" />
      <div className="grid gap-2 sm:grid-cols-[1.4fr_1fr]">
        <div className="rounded-lg border bg-card p-3">
          <div className="font-heading text-sm font-semibold text-foreground">Workers</div>
          <div className="mt-1 text-[13px] leading-5 text-muted-foreground">Build worlds and run episodes. Add workers to do more at once.</div>
          <div className="mt-2.5 grid gap-2 sm:grid-cols-2">
            <Box title="Sandbox" tone="quiet">One world&apos;s containers, on a network with no internet.</Box>
            <Box title="Sandbox" tone="quiet">Removed when the work ends.</Box>
          </div>
        </div>
        <Box title="Model providers" tone="quiet">The only outside service workers call. Keys stay on the server.</Box>
      </div>
    </Frame>
  );
}
