import { Activity, Boxes, CircleCheck, Database, GitCompareArrows, MessageSquareDiff, ShieldCheck, TimerOff, Workflow, Bot, ListChecks, Repeat, BadgeCheck, CopyX, MessageCircleQuestion } from "lucide-react";
import Link from "next/link";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { BentoCard, BentoGrid } from "@/components/blocks/bento-grid";
import { SpotlightCard } from "@/components/blocks/spotlight-card";
import { HeroWindow } from "../landing/HeroWindow";
import { InstallChip } from "../landing/InstallChip";
import { Paths } from "../landing/Paths";
import { NavActions, StartCta } from "../landing/SessionCta";

// Where pilot requests go (booking page, form, or mailto), set at deploy time.
const CONTACT = process.env.NEXT_PUBLIC_CONTACT_URL;

/* ---- small illustrations inside the bento cards: example content, styled like the console ---- */

function Mono({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`font-mono text-[12px] leading-relaxed ${className}`}>{children}</div>;
}

const PHASES = ["Read the source", "Plan the runtime", "Start the sandbox", "Find the API", "Seed fictional data", "Choose agent tools", "Write jobs", "Validate", "Publish"];

function CompilerVisual() {
  return (
    <div className="absolute inset-x-5 top-5 rounded-lg border bg-background/60 p-4">
      <ol className="grid grid-cols-3 gap-x-4 gap-y-2.5 text-[12px]">
        {PHASES.map((p, i) => (
          <li key={p} className="min-w-0">
            <div className={`h-1 rounded-full ${i < 5 ? "bg-success" : i === 5 ? "animate-pulse bg-primary" : "bg-muted"}`} />
            <div className={`mt-1.5 truncate ${i <= 5 ? "text-foreground" : "text-muted-foreground"}`}>{p}</div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function CustomerVisual() {
  return (
    <div className="absolute inset-x-5 top-5 space-y-2 text-[13px]">
      <div className="w-fit max-w-[85%] rounded-2xl rounded-bl-sm bg-muted px-3 py-2 line-through decoration-muted-foreground/70">Refund order 4182, please.</div>
      <div className="w-fit max-w-[85%] rounded-2xl rounded-bl-sm bg-muted px-3 py-2">Actually, make it store credit instead.</div>
      <div className="ml-auto w-fit rounded-full border border-warning/40 bg-warning/10 px-2.5 py-0.5 text-[11px] text-warning">request changed, v2</div>
    </div>
  );
}

function FaultVisual() {
  return (
    <Mono className="absolute inset-x-5 top-5 space-y-1.5 rounded-lg border bg-background/60 p-3">
      <div><span className="text-muted-foreground">POST</span> /refunds <span className="text-destructive">timeout (injected)</span></div>
      <div><span className="text-muted-foreground">GET</span>&nbsp; /refunds?order=4182 <span className="text-foreground">1 found</span></div>
      <div className="text-success">agent: already refunded, no retry</div>
    </Mono>
  );
}

function VerifyVisual() {
  return (
    <div className="absolute inset-x-5 top-5 grid gap-3 sm:grid-cols-[1.4fr_1fr]">
      <Mono className="rounded-lg border bg-background/60 p-3">
        <span className="text-primary">SELECT</span> count(*) <span className="text-primary">FROM</span> refunds<br />
        <span className="text-primary">WHERE</span> order_id = 4182;<br />
        <span className="text-muted-foreground">-- read-only, after the episode</span>
      </Mono>
      <div className="flex flex-col gap-2 text-[12px]">
        <span className="flex items-center gap-1.5 rounded-md border border-success/30 bg-success/10 px-2 py-1 text-success"><CircleCheck className="size-3.5" /> goal reached</span>
        <span className="flex items-center gap-1.5 rounded-md border border-success/30 bg-success/10 px-2 py-1 text-success"><CircleCheck className="size-3.5" /> no duplicate refund</span>
        <span className="flex items-center gap-1.5 rounded-md border border-success/30 bg-success/10 px-2 py-1 text-success"><CircleCheck className="size-3.5" /> claim matches records</span>
      </div>
    </div>
  );
}

function ImproveVisual() {
  return (
    <Mono className="absolute inset-x-5 top-5 rounded-lg border bg-background/60 p-3">
      <div className="text-muted-foreground">baseline v1 → v2, proposed from failed training jobs</div>
      <div className="mt-2 rounded bg-destructive/10 px-2 py-0.5 text-destructive">- Retry any refund call that fails.</div>
      <div className="mt-1 rounded bg-success/10 px-2 py-0.5 text-success">+ Before retrying, check whether the refund already exists.</div>
      <div className="mt-1 rounded bg-success/10 px-2 py-0.5 text-success">+ Re-read the latest customer message before acting.</div>
    </Mono>
  );
}

function TraceVisual() {
  return (
    <Mono className="absolute inset-x-5 top-5 space-y-1 rounded-lg border bg-background/60 p-3">
      <div>rehearse-agent</div>
      <div className="pl-3 text-muted-foreground">└ episode · refund-changed-mind</div>
      <div className="pl-6 text-muted-foreground">├ llm · deepseek-v4.1-flash</div>
      <div className="pl-6 text-muted-foreground">├ tool · create_refund</div>
      <div className="pl-6 text-success">└ verifier · 3 checks passed</div>
    </Mono>
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
  { name: "Pro", price: "$29", unit: "/ month", points: ["3 applications, 2 world builds a month", "750 episodes a month, run at once", "2 sandboxes at a time", "25% off with your own model key"], cta: "Start free", href: "/app/", featured: true },
  { name: "Team", price: "$149", unit: "/ month", points: ["20 applications, 8 world builds a month", "3,000 episodes a month", "4 sandboxes at a time", "25% off with your own model key"], cta: "Start free", href: "/app/" },
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
    <div className="min-h-screen overflow-x-hidden bg-background">
      <header className="sticky top-0 z-40 border-b border-border/60 bg-background/70 backdrop-blur-xl">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-4 px-4 md:px-8">
          <Link href="/" className="flex items-center gap-2"><span className="size-3 rotate-45 rounded-[3px] bg-primary" aria-hidden="true" /><span className="font-heading text-[17px] font-bold">Rehearsal</span></Link>
          <nav className="flex items-center gap-1">
            <Button asChild variant="ghost" size="sm" className="hidden md:inline-flex"><a href="#features">Product</a></Button>
            <Button asChild variant="ghost" size="sm" className="hidden md:inline-flex"><a href="#live">Live build</a></Button>
            <Button asChild variant="ghost" size="sm" className="hidden md:inline-flex"><a href="#pricing">Pricing</a></Button>
            <NavActions />
          </nav>
        </div>
      </header>

      {/* Hero: the product working, replayed in the console's own build view */}
      <section className="relative">
        <div className="pointer-events-none absolute inset-0 [background-image:linear-gradient(to_right,var(--border)_1px,transparent_1px),linear-gradient(to_bottom,var(--border)_1px,transparent_1px)] [background-size:56px_56px] [mask-image:radial-gradient(ellipse_70%_55%_at_50%_0%,#000_40%,transparent_100%)] opacity-50" />
        <div className="pointer-events-none absolute -top-48 left-1/2 h-[520px] w-[900px] -translate-x-1/2 rounded-full bg-primary/20 blur-[130px]" />
        <div className="relative mx-auto max-w-7xl px-4 pt-16 md:px-8 lg:pt-24">
          <div className="mx-auto max-w-4xl text-center">
            <a href="#live" className="inline-flex items-center gap-2 rounded-full border bg-card/60 px-3 py-1 text-sm text-muted-foreground transition-colors hover:text-foreground">
              <span className="size-1.5 rounded-full bg-success shadow-[0_0_8px_var(--success)]" /> A real build, replayed below
            </a>
            <h1 className="mt-6 text-[clamp(40px,6vw,76px)] font-bold leading-[1.02] tracking-tight text-balance">Rehearse your AI agent on a copy of your real app.</h1>
            <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground md:text-xl">
              Rehearsal compiles your application into a sandboxed practice world with fictional data, runs your agent through real jobs, and scores every outcome against the application&apos;s own database.
            </p>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
              <StartCta />
              <InstallChip />
            </div>
          </div>
          <div id="live" className="relative mx-auto mt-14 max-w-6xl scroll-mt-24 pb-20">
            <HeroWindow />
            <p className="mt-4 text-center text-sm text-muted-foreground">Recorded, not simulated: the World Compiler turning Gitea into a practice world. Click any figure to see exactly what it did.</p>
          </div>
        </div>

      </section>

      {/* Features: bento grid */}
      <section id="features" className="border-t border-border/60">
        <div className="mx-auto max-w-7xl px-4 py-24 md:px-8">
          <SectionHead title="Everything a rehearsal needs, built from your app" body="Mocks agree with whatever the agent does, and production is too risky to practise in. Rehearsal builds the middle ground automatically." />
          <BentoGrid className="mt-14">
            <BentoCard className="md:col-span-2" Icon={Workflow} name="The World Compiler" description="An agent reads your source, starts your real images in an isolated sandbox, seeds fictional data, chooses the tools each role may use, and writes jobs it proves can be passed and failed." background={<CompilerVisual />} href="#live" cta="Watch a build" />
            <BentoCard Icon={MessageSquareDiff} name="Customers who change their minds" description="Simulated customers revise requests mid-task. Agents that finish the old request get caught." background={<CustomerVisual />} />
            <BentoCard Icon={TimerOff} name="Failures on purpose" description="Requests time out after the change went through. Blind retries show up as duplicates." background={<FaultVisual />} />
            <BentoCard className="md:col-span-2" Icon={Database} name="Verified in your database, not by an LLM" description="Read-only checks against the application's own records decide every outcome, so a confident agent can't talk its way to a pass." background={<VerifyVisual />} />
            <BentoCard className="md:col-span-2" Icon={GitCompareArrows} name="Improve the agent, then compare" description="The improvement agent proposes changes from failed training jobs. Compare versions on jobs neither version has seen." background={<ImproveVisual />} />
            <BentoCard Icon={Activity} name="Every step traced" description="Each build and rehearsal is a Tracing trace: model calls, tool calls, and checks." background={<TraceVisual />} />
          </BentoGrid>
          <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-dashed bg-card/40 px-5 py-4">
            <span className="rounded-full border border-primary/40 bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">Coming soon</span>
            <span className="font-medium">Train your own model on your practice worlds.</span>
            <span className="text-sm text-muted-foreground">Every episode already ends with a score verified in your database: the reward reinforcement learning needs.</span>
          </div>
        </div>
      </section>

      {/* Dashboard or code */}
      <section className="border-t border-border/60">
        <div className="mx-auto grid max-w-7xl gap-12 px-4 py-24 md:px-8 lg:grid-cols-[0.8fr_1.2fr]">
          <div>
            <h2 className="text-3xl font-bold tracking-tight md:text-[44px] md:leading-[1.08]">From the dashboard, or from code</h2>
            <p className="mt-4 text-lg text-muted-foreground">Everything works without writing code. When you want it in CI, the CLI and the Python SDK call the same API.</p>
            <div className="mt-6 flex flex-wrap gap-2 text-sm text-muted-foreground">
              {[["Google sign-in", Boxes], ["API keys per CI job", Bot], ["Same API everywhere", Workflow]].map(([t, I]) => {
                const Icon = I as typeof Boxes;
                return <span key={t as string} className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1"><Icon className="size-3.5 text-primary" />{t as string}</span>;
              })}
            </div>
          </div>
          <Paths />
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
          <p className="mt-8 text-center text-sm text-muted-foreground">Yearly plans get two months free. Extra use costs $15 per world build and $30 per 1,000 episodes. Every job has a spend cap, so a bill never surprises you.</p>
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

      <section id="cta" className="px-4 pb-24 md:px-8">
        <div className="relative mx-auto max-w-5xl overflow-hidden rounded-2xl border bg-card px-6 py-16 text-center md:px-16">
          <div className="pointer-events-none absolute inset-x-0 -top-24 mx-auto h-64 w-[640px] rounded-full bg-primary/25 blur-[100px]" />
          <h2 className="relative text-3xl font-bold tracking-tight md:text-5xl">Find out what breaks before your customers do.</h2>
          <p className="relative mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">Design-partner pilot: four weeks, free for the first five teams shipping an agent into their own product.</p>
          <div className="relative mt-8 flex flex-wrap justify-center gap-3">
            <StartCta />
            {CONTACT && <Button asChild size="lg" variant="outline"><a href={CONTACT}>Ask for a pilot</a></Button>}
          </div>
          <p className="relative mt-6 flex items-center justify-center gap-2 text-sm text-muted-foreground"><ShieldCheck className="size-4 text-success" /> Fictional data only. No production access. Isolated sandboxes.</p>
        </div>
      </section>

      <footer className="border-t border-border/60">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-8 text-sm text-muted-foreground md:px-8">
          <span className="flex items-center gap-2"><span className="size-2.5 rotate-45 rounded-[2px] bg-primary" /> Rehearsal, a dress rehearsal for your AI agent</span>
          <span className="flex gap-5"><a href="#features" className="hover:text-foreground">Product</a><a href="#pricing" className="hover:text-foreground">Pricing</a><Link href="/app/" className="hover:text-foreground">Console</Link></span>
        </div>
      </footer>
    </div>
  );
}
