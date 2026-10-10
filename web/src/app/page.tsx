import { Activity, CircleCheck, Database, GitCompareArrows, MessageSquareDiff, ShieldCheck, TimerOff, Workflow, ListChecks, Repeat, BadgeCheck, CopyX, MessageCircleQuestion } from "lucide-react";
import Link from "next/link";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { BentoCard, BentoGrid } from "@/components/blocks/bento-grid";
import { SpotlightCard } from "@/components/blocks/spotlight-card";
import { HeroWindow } from "../landing/HeroWindow";
import { InstallChip } from "../landing/InstallChip";
import { PixelBackdrop } from "../landing/PixelBackdrop";
import { NavActions, StartCta } from "../landing/SessionCta";

// Where pilot requests go (booking page, form, or mailto), set at deploy time.
const CONTACT = process.env.NEXT_PUBLIC_CONTACT_URL;

// Where "Docs" leads. Until the documentation site planned in handbook/DOCS_SITE_PLAN.md exists, that is the API
// reference the server generates at /docs; set this at deploy time to point at the site instead.
const DOCS = process.env.NEXT_PUBLIC_DOCS_URL || "/docs";

/* ---- small illustrations inside the bento cards: example content, styled like the console ---- */

function Mono({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`font-mono text-[12px] leading-relaxed ${className}`}>{children}</div>;
}

/** A small window that frames an illustration: a title bar with a label, then the content. */
function Pane({ label, aside, children, className = "" }: { label: string; aside?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={`overflow-hidden rounded-lg border bg-card shadow-[0_10px_28px_-14px_rgb(0_0_0/0.55)] ${className}`}>
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

const PHASES = ["Read the source", "Plan the runtime", "Start the sandbox", "Find the API", "Seed fictional data", "Choose agent tools", "Write jobs", "Validate", "Publish"];

function CompilerVisual() {
  return (
    <Pane label="world build · gitea" aside={<span className="tabular-nums">5 of 9</span>} className="mx-auto max-w-xl">
      <ol className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-[12px] sm:grid-cols-3">
        {PHASES.map((p, i) => (
          <li key={p} className="flex min-w-0 items-center gap-2">
            {i < 5 ? (
              <CircleCheck className="size-3.5 shrink-0 text-success" />
            ) : i === 5 ? (
              <span className="grid size-3.5 shrink-0 place-items-center"><span className="size-2 animate-pulse rounded-full bg-primary shadow-[0_0_8px_var(--primary)]" /></span>
            ) : (
              <span className="size-3.5 shrink-0 rounded-full border border-muted-foreground/35" />
            )}
            <span className={`truncate ${i < 5 ? "" : i === 5 ? "font-medium" : "text-muted-foreground"}`}>{p}</span>
          </li>
        ))}
      </ol>
      <div className="mt-3 h-1 overflow-hidden rounded-full bg-muted"><div className="h-full w-[60%] rounded-full bg-linear-to-r from-success to-primary" /></div>
    </Pane>
  );
}

function CustomerVisual() {
  const face = <span className="grid size-6 shrink-0 place-items-center rounded-full border bg-muted text-[10px] font-semibold text-muted-foreground" aria-hidden="true">C</span>;
  return (
    <div className="mx-auto max-w-sm space-y-2 text-[13px]">
      <div className="flex items-end gap-2">
        {face}
        <div className="rounded-2xl rounded-bl-sm border bg-card px-3 py-1.5 text-muted-foreground line-through decoration-muted-foreground/60">Refund order 4182, please.</div>
      </div>
      <div className="flex items-center gap-2 pl-8 text-[11px] text-warning">
        <span className="h-px flex-1 bg-warning/30" />
        <span className="rounded-full border border-warning/40 bg-warning/10 px-2 py-0.5 font-medium">request changed · v2</span>
        <span className="h-px flex-1 bg-warning/30" />
      </div>
      <div className="flex items-end gap-2">
        {face}
        <div className="rounded-2xl rounded-bl-sm border bg-card px-3 py-1.5 shadow-[0_8px_20px_-12px_rgb(0_0_0/0.5)]">Actually, make it store credit instead.</div>
      </div>
    </div>
  );
}

function FaultVisual() {
  return (
    <Pane label="episode · tool calls" className="mx-auto max-w-sm">
      <Mono className="space-y-2">
        <div className="flex items-center gap-1.5">
          <span className="w-8 shrink-0 text-muted-foreground">POST</span><span className="truncate">/refunds</span>
          <span className="ml-auto shrink-0 rounded border border-destructive/40 bg-destructive/10 px-1.5 text-[11px] text-destructive">timeout · injected</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-8 shrink-0 text-muted-foreground">GET</span><span className="truncate">/refunds?order=4182</span>
          <span className="ml-auto shrink-0 rounded border px-1.5 text-[11px] text-muted-foreground">1 found</span>
        </div>
        <div className="flex items-center gap-2 border-t pt-2 text-success"><CircleCheck className="size-3.5 shrink-0" /><span className="truncate">already refunded, no retry</span></div>
      </Mono>
    </Pane>
  );
}

function VerifyVisual() {
  return (
    <div className="mx-auto grid max-w-2xl items-center gap-3 sm:grid-cols-[1.25fr_1fr]">
      <Pane label="check · read-only">
        <Mono className="grid grid-cols-[auto_1fr] gap-x-3">
          <span className="select-none text-right text-muted-foreground/50" aria-hidden="true">1<br />2</span>
          <span><span className="text-primary">SELECT</span> count(*) <span className="text-primary">FROM</span> refunds<br /><span className="text-primary">WHERE</span> order_id = 4182;</span>
        </Mono>
        <div className="mt-2 border-t pt-2 font-mono text-[11px] text-muted-foreground">→ count = <span className="text-foreground">1</span>, read after the episode</div>
      </Pane>
      <ul className="space-y-1.5 text-[12px]">
        {["Goal reached", "No duplicate refund", "Claim matches records"].map((check) => (
          <li key={check} className="flex items-center gap-2 rounded-md border border-success/25 bg-success/10 px-2.5 py-1.5">
            <CircleCheck className="size-3.5 shrink-0 text-success" /><span className="truncate">{check}</span>
            <span className="ml-auto font-mono text-[11px] text-success">pass</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ImproveVisual() {
  return (
    <Pane label="agent instructions" aside={<span className="rounded border px-1.5 font-mono">v1 → v2</span>} className="mx-auto max-w-2xl">
      <Mono className="space-y-1">
        <div className="flex gap-2 rounded bg-destructive/10 px-2 py-0.5 text-destructive"><span className="select-none" aria-hidden="true">−</span><span className="min-w-0 md:truncate">Retry any refund call that fails.</span></div>
        <div className="flex gap-2 rounded bg-success/10 px-2 py-0.5 text-success"><span className="select-none" aria-hidden="true">+</span><span className="min-w-0 md:truncate">Before retrying, check whether the refund already exists.</span></div>
        <div className="flex gap-2 rounded bg-success/10 px-2 py-0.5 text-success"><span className="select-none" aria-hidden="true">+</span><span className="min-w-0 md:truncate">Re-read the latest customer message before acting.</span></div>
      </Mono>
      <div className="mt-2.5 truncate text-[11px] text-muted-foreground">Proposed from failed training jobs</div>
    </Pane>
  );
}

// name, depth in the tree, where its bar starts and how wide it is (percent of the episode), colour
const SPANS: [string, number, number, number, string][] = [
  ["episode · changed-mind", 0, 0, 100, "bg-primary/60"],
  ["llm · deepseek-v4.1-flash", 1, 3, 34, "bg-primary"],
  ["tool · create_refund", 1, 39, 20, "bg-info"],
  ["tool · list_refunds", 1, 61, 16, "bg-info"],
  ["verifier · 3 passed", 1, 82, 16, "bg-success"],
];

function TraceVisual() {
  return (
    <Pane label="trace · rehearse-agent" className="mx-auto max-w-sm">
      <div className="space-y-1.5 font-mono text-[11px]">
        {SPANS.map(([name, depth, from, width, colour]) => (
          <div key={name} className="grid grid-cols-[minmax(0,2.4fr)_1fr] items-center gap-2.5">
            <span className={`truncate ${depth ? "text-muted-foreground" : ""}`} style={{ paddingLeft: depth * 10 }}>{name}</span>
            <span className="relative h-1.5 rounded-full bg-muted"><span className={`absolute inset-y-0 rounded-full ${colour}`} style={{ left: `${from}%`, width: `${width}%` }} /></span>
          </div>
        ))}
      </div>
    </Pane>
  );
}

const MEASURES = [
  { icon: BadgeCheck, title: "Verified success", body: "The outcome exists in your application's own records." },
  { icon: ShieldCheck, title: "Rule violations", body: "Anything your checks say must never happen, like touching the wrong account." },
  { icon: CopyX, title: "Duplicate side effects", body: "A second refund, email, or shipment caused by a blind retry." },
  { icon: Repeat, title: "Recovery after faults", body: "Whether the agent finished correctly after a request failed or timed out." },
  { icon: ListChecks, title: "False “done” claims", body: "The agent said it finished; the records say otherwise." },
  { icon: MessageCircleQuestion, title: "Unneeded questions", body: "Interruptions to the customer beyond what the job required." },
];

const TIERS = [
  { name: "Free", price: "$0", unit: "forever", points: ["1 application, built into a practice world once", "40 episodes a month, run in quiet hours", "1 sandbox at a time"], cta: "Start free", href: "/app/" },
  { name: "Pro", price: "$29", unit: "/ month", points: ["3 applications, 2 world builds a month", "750 episodes a month, run at once", "2 sandboxes at a time", "Top-ups when you need more"], cta: "Start free", href: "/app/", featured: true },
  { name: "Team", price: "$149", unit: "/ month", points: ["20 applications, 8 world builds a month", "3,000 episodes a month", "4 sandboxes at a time", "Top-ups when you need more"], cta: "Start free", href: "/app/" },
  { name: "Enterprise", price: "Custom", unit: "from $3,000 a month", points: ["Runner inside your own cloud account", "Single sign-on, audit export, retention controls", "Private held-out evaluation of vendor agents"], cta: "Talk to us", href: "#cta" },
];

const FAQ = [
  ["Can I train a model on my practice worlds?", "Coming soon. Every episode already ends with a score verified in your application's database, which is the reward reinforcement learning needs. Today you can export verified episodes as a dataset and improve an agent's instructions from its failures."],
  ["Does Rehearsal touch my production data?", "No. It runs your application's published images in a network with no internet access, with fictional data it creates itself. Checks read the sandbox database read-only."],
  ["Do I need to write code?", "No. Sign in, add your application, build its world, and rehearse an agent from the dashboard. The CLI and Python SDK do the same things for CI pipelines and scripts."],
  ["Which applications work?", "Web applications that run in containers and expose an HTTP or GraphQL API, backed by SQLite, PostgreSQL, or MySQL. One catalog application is kept out of development entirely, to test applications the compiler has never seen."],
  ["Which agents can I rehearse?", "Any model behind an OpenAI-compatible API, described as an agent profile, or your own agent in any language through the episode API."],
  ["How do I install it?", "pip install rehearsal-kit installs the CLI and Python SDK. To run the server, workers, and sandboxes yourself, install rehearsal-kit[server] on a Linux machine with Docker."],
  ["How is model cost counted?", "From the cost the provider reports, the serving provider's published price list, or a dated override, with the source recorded for every call."],
];

function SectionHead({ title, body }: { title: string; body: string }) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <h2 className="text-3xl font-bold tracking-tight md:text-[44px] md:leading-[1.08]">{title}</h2>
      <p className="mt-4 text-lg text-muted-foreground">{body}</p>
    </div>
  );
}

export default function Landing() {
  return (
    <div className="min-h-screen overflow-x-clip bg-background">
      {/* A black line along the top edge with a tab hanging from it (the header's own pseudo-element is the line; the
          tab's two are the concave shoulders that join it to the line). They stay black in both themes, and the hero's
          black frame below continues the line down the sides. */}
      <header className="pointer-events-none fixed inset-x-0 top-0 z-40 flex justify-center px-5 before:absolute before:inset-x-0 before:top-0 before:h-2.5 before:bg-black">
        <div className="pointer-events-auto relative flex h-14 items-center rounded-b-2xl bg-black px-3 text-white [filter:drop-shadow(0_1px_0_rgb(255_255_255/0.14))_drop-shadow(0_14px_30px_rgb(0_0_0/0.45))] before:absolute before:right-full before:top-2.5 before:size-3.5 before:bg-[radial-gradient(circle_at_0_100%,transparent_13.5px,#000_14.5px)] after:absolute after:left-full after:top-2.5 after:size-3.5 after:bg-[radial-gradient(circle_at_100%_100%,transparent_13.5px,#000_14.5px)]">
          <Link href="/" className="flex items-center gap-2.5">
            <span className="grid size-8 place-items-center rounded-[9px] bg-[linear-gradient(180deg,#b9b1ff_0%,#8f83ff_24%,#6a5af0_25%,#4b3dd2_100%)] shadow-[inset_0_1px_0_rgb(255_255_255/0.5)]" aria-hidden="true"><span className="size-2.5 rotate-45 rounded-[2px] bg-white" /></span>
            <span className="font-heading text-[19px] font-bold tracking-tight">Rehearsal</span>
          </Link>
          <nav className="ml-11 hidden items-center gap-[22px] text-[15px] text-white/60 md:flex">
            <a href="#features" className="transition-colors hover:text-white">Features</a>
            <a href="#faq" className="transition-colors hover:text-white">FAQ</a>
            <a href="#pricing" className="transition-colors hover:text-white">Pricing</a>
            {/* a plain link, not a router link: the server answers /docs itself, it is not a page of this app */}
            <a href={DOCS} className="transition-colors hover:text-white">Docs</a>
          </nav>
          <div className="ml-6 md:ml-11"><NavActions /></div>
        </div>
      </header>

      {/* Hero: the product working, replayed in the console's own build view, on a picture held in a black frame.
          Everything inside takes its colours from the picture (the "wave" palette in globals.css), in both themes.
          The panel and the page root clip their overflow and do not hide it, which would stop the picture staying
          in view as the hero scrolls. */}
      <section className="bg-black p-2.5">
        <div className="dark wave relative overflow-clip rounded-[26px] text-foreground">
          <PixelBackdrop src="/landing/great-wave.webp" focusX={0.44} />
          {/* the picture is a little darker behind the words and under the caption at the foot */}
          <div className="pointer-events-none absolute inset-x-0 top-0 h-[780px] bg-[radial-gradient(ellipse_52%_44%_at_50%_45%,color-mix(in_srgb,var(--background)_58%,transparent),transparent)]" />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-40 bg-linear-to-b from-transparent to-background/70" />
          <div className="relative mx-auto max-w-7xl px-4 pt-28 md:px-8 lg:pt-36">
            <div className="mx-auto max-w-4xl text-center">
              <a href="#live" className="inline-flex items-center gap-2 rounded-full border bg-card px-3 py-1 text-sm text-muted-foreground backdrop-blur-md transition-colors hover:text-foreground">
                <span className="size-1.5 rounded-full bg-success shadow-[0_0_8px_var(--success)]" /> A real build, replayed below
              </a>
              <h1 className="mt-6 text-[clamp(40px,6vw,76px)] font-bold leading-[1.02] tracking-tight text-balance [text-shadow:0_2px_28px_rgb(4_8_26/0.7)]">Rehearse your AI agent on a copy of your real app.</h1>
              <p className="mx-auto mt-6 max-w-2xl text-lg text-foreground/85 [text-shadow:0_1px_14px_rgb(4_8_26/0.85)] md:text-xl">
                Rehearsal compiles your application into a sandboxed practice world with fictional data, runs your agent through real jobs, and scores every outcome against the application&apos;s own database.
              </p>
              <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
                <StartCta />
                <InstallChip />
              </div>
            </div>
            <div id="live" className="relative mx-auto mt-14 max-w-6xl scroll-mt-24 pb-20">
              <HeroWindow />
              <p className="mt-4 text-center text-sm text-foreground/75">Recorded, not simulated: the World Compiler turning Gitea into a practice world.</p>
            </div>
          </div>

        </div>
      </section>

      {/* Features: bento grid */}
      <section id="features" className="border-t border-border/60">
        <div className="mx-auto max-w-7xl px-4 py-24 md:px-8">
          <SectionHead title="Everything a rehearsal needs, built from your app" body="Mocks agree with whatever the agent does, and production is too risky to practise in. Rehearsal builds the middle ground automatically." />
          <BentoGrid className="mt-14">
            <BentoCard className="lg:col-span-2"Icon={Workflow} name="The World Compiler" description="An agent reads your source, starts your real images in an isolated sandbox, seeds fictional data, chooses the tools each role may use, and writes jobs it proves can be passed and failed." visual={<CompilerVisual />} href="#live" cta="Watch a build" />
            <BentoCard Icon={MessageSquareDiff} name="Customers who change their minds" description="Simulated customers revise requests mid-task. Agents that finish the old request get caught." visual={<CustomerVisual />} />
            <BentoCard Icon={TimerOff} name="Failures on purpose" description="Requests time out after the change went through. Blind retries show up as duplicates." visual={<FaultVisual />} />
            <BentoCard className="lg:col-span-2"Icon={Database} name="Verified in your database, not by an LLM" description="Read-only checks against the application's own records decide every outcome, so a confident agent can't talk its way to a pass." visual={<VerifyVisual />} />
            <BentoCard className="lg:col-span-2"Icon={GitCompareArrows} name="Improve the agent, then compare" description="The improvement agent proposes changes from failed training jobs. Compare versions on jobs neither version has seen." visual={<ImproveVisual />} />
            <BentoCard Icon={Activity} name="Every step traced" description="Each build and rehearsal is a Tracing trace: model calls, tool calls, and checks." visual={<TraceVisual />} />
          </BentoGrid>
          <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-dashed bg-card/40 px-5 py-4">
            <span className="rounded-full border border-primary/40 bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">Coming soon</span>
            <span className="font-medium">Train your own model on your practice worlds.</span>
            <span className="text-sm text-muted-foreground">Every episode already ends with a score verified in your database: the reward reinforcement learning needs.</span>
          </div>
        </div>
      </section>

      {/* What gets measured */}
      <section className="border-t border-border/60 bg-card/30">
        <div className="mx-auto max-w-7xl px-4 py-24 md:px-8">
          <SectionHead title="A readiness verdict, with evidence" body="For every agent on every application: ready to pilot, or not yet. Each verdict links to the episodes behind it." />
          <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {MEASURES.map((m) => (
              <SpotlightCard key={m.title}>
                <m.icon className="size-5 text-primary" />
                <h3 className="mt-4 font-semibold">{m.title}</h3>
                <p className="mt-1.5 text-sm text-muted-foreground">{m.body}</p>
              </SpotlightCard>
            ))}
          </div>
        </div>
      </section>

      <section id="pricing" className="border-t border-border/60 bg-card/30">
        <div className="mx-auto max-w-7xl px-4 py-24 md:px-8">
          <SectionHead title="Pricing" body="Start free and keep the free plan. Pay when you rehearse more often. The open-source core stays free to self-host with your own model key." />
          <div className="mt-14 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {TIERS.map((t) => (
              <SpotlightCard key={t.name} className={t.featured ? "border-primary/60 shadow-[0_0_0_1px_var(--primary),0_20px_60px_-20px_var(--primary)]" : ""}>
                <div className="flex items-center justify-between"><h3 className="font-semibold">{t.name}</h3>{t.featured && <span className="rounded-full bg-primary/15 px-2.5 py-0.5 text-xs font-medium text-primary">Recommended</span>}</div>
                <p className="mt-5"><span className="font-heading text-4xl font-bold">{t.price}</span> <span className="text-sm text-muted-foreground">{t.unit}</span></p>
                <ul className="mt-6 space-y-2.5 text-sm">
                  {t.points.map((p) => <li key={p} className="flex gap-2"><CircleCheck className="mt-0.5 size-4 shrink-0 text-success" />{p}</li>)}
                </ul>
                <Button asChild className="mt-8 w-full" variant={t.featured ? "default" : "outline"}>{t.href.startsWith("/") ? <Link href={t.href}>{t.cta}</Link> : <a href={t.href}>{t.cta}</a>}</Button>
              </SpotlightCard>
            ))}
          </div>
          <p className="mt-8 text-center text-sm text-muted-foreground">Yearly plans get two months free. Need more in a month? Add 1,000 episodes for $30, or a world build for $15. Nothing renews by itself, and every job has a spend cap.</p>
        </div>
      </section>

      <section id="faq" className="border-t border-border/60">
        <div className="mx-auto max-w-3xl px-4 py-24 md:px-8">
          <h2 className="text-center text-3xl font-bold tracking-tight md:text-[44px]">Questions</h2>
          <Accordion type="single" collapsible className="mt-10">
            {FAQ.map(([q, a]) => <AccordionItem key={q} value={q}><AccordionTrigger className="text-left text-base">{q}</AccordionTrigger><AccordionContent className="text-muted-foreground">{a}</AccordionContent></AccordionItem>)}
          </Accordion>
        </div>
      </section>

      {/* The page ends as it began, with a picture in a black frame and the "wave" palette. The closing call to
          action sits on the night sky; the product's name runs across the foot in outline, with the riders passing
          behind it. On a wide screen the panel is as tall as the picture, so all of the picture shows. */}
      <section id="cta" className="bg-black p-2.5">
        <div className="dark wave relative flex min-h-[calc((100vw-1.25rem)*0.563)] flex-col overflow-clip rounded-[26px] text-foreground">
          <PixelBackdrop src="/landing/night-riders.webp" wash={[0.3, 0.5]} />
          <div className="pointer-events-none absolute inset-x-0 top-0 h-[560px] bg-[radial-gradient(ellipse_50%_50%_at_50%_44%,color-mix(in_srgb,var(--background)_55%,transparent),transparent)]" />
          <div className="relative mx-auto max-w-3xl px-4 pt-24 text-center md:px-8 lg:pt-28">
            <h2 className="text-balance text-3xl font-bold tracking-tight [text-shadow:0_2px_28px_rgb(4_8_26/0.7)] md:text-5xl">Find out what breaks before your customers do.</h2>
            <p className="mx-auto mt-4 max-w-2xl text-lg text-foreground/85 [text-shadow:0_1px_14px_rgb(4_8_26/0.85)]">Design-partner pilot: four weeks, free for the first five teams shipping an agent into their own product.</p>
            <div className="mt-8 flex flex-wrap justify-center gap-3">
              <StartCta />
              {CONTACT && <Button asChild size="lg" variant="outline"><a href={CONTACT}>Ask for a pilot</a></Button>}
            </div>
            <p className="mt-6 flex items-center justify-center gap-2 text-sm text-foreground/80 [text-shadow:0_1px_12px_rgb(4_8_26/0.9)]"><ShieldCheck className="size-4 text-success" /> Fictional data only. No production access. Isolated sandboxes.</p>
          </div>
          {/* the ground darkens toward the foot, so the name and the links read over the sand */}
          <footer className="relative mt-auto bg-linear-to-b from-transparent via-background/45 to-background/85 px-5 pb-5 pt-24 md:px-8 md:pb-6">
            {/* The name in outline, as wide as the panel: the type is sized from the panel's own width. The outline is
                cut by a filter (the solid letters minus a slightly shrunken copy of themselves), because stroking this
                font also draws the contours inside its letters as stray lines. The colour is see-through, which
                leaves the letters a faint fill; at full strength, on hover, they are hollow. */}
            <svg className="absolute size-0" aria-hidden="true">
              <filter id="outline-only">
                <feMorphology in="SourceAlpha" operator="erode" radius="1.5" result="inside" />
                <feComposite in="SourceGraphic" in2="inside" operator="out" />
              </filter>
            </svg>
            <div className="@container" aria-hidden="true">
              <div className="flex items-center justify-center gap-[0.16em] whitespace-nowrap font-heading text-[length:16.5cqw] font-bold leading-[0.9] tracking-[-0.035em] text-[rgb(246_239_223/0.72)] transition-colors duration-500 [filter:url(#outline-only)] hover:text-[rgb(246_239_223)]">
                <span className="size-[0.5em] shrink-0 rotate-45 rounded-[0.09em] bg-current" />
                Rehearsal
              </div>
            </div>
            <div className="mt-6 flex flex-wrap items-center justify-between gap-3 font-mono text-xs text-foreground/75">
              <span className="flex items-center gap-2"><span className="size-1.5 rounded-full bg-primary" /> Rehearsal, a dress rehearsal for your AI agent</span>
              <span className="flex gap-6"><a href="#features" className="hover:text-foreground">Product</a><a href="#pricing" className="hover:text-foreground">Pricing</a><Link href="/app/" className="hover:text-foreground">Console</Link></span>
            </div>
          </footer>
        </div>
      </section>
    </div>
  );
}
