import { Activity, CircleCheck, Database, GitCompareArrows, MessageSquareDiff, ShieldCheck, TimerOff, Workflow } from "lucide-react";
import Link from "next/link";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { BentoCard, BentoGrid } from "@/components/blocks/bento-grid";
import { SpotlightCard } from "@/components/blocks/spotlight-card";
import { HeroWindow } from "../landing/HeroWindow";
import { InstallChip } from "../landing/InstallChip";
import { PixelBackdrop } from "../landing/PixelBackdrop";
import { PixelTrail } from "../landing/PixelTrail";
import { CompilerScene, CustomerScene, FaultScene, ImproveScene, TraceScene, VerdictReport, VerifyScene } from "../landing/Showcase";
import { NavActions, StartCta } from "../landing/SessionCta";

// Where pilot and enterprise requests go, set at deploy time: a booking page or form, or else an email address.
const CONTACT_EMAIL = process.env.NEXT_PUBLIC_CONTACT_EMAIL;
const CONTACT = process.env.NEXT_PUBLIC_CONTACT_URL || (CONTACT_EMAIL ? `mailto:${CONTACT_EMAIL}?subject=Rehearsal%20Enterprise` : undefined);

// Where "Docs" leads: the documentation site (docs/), whose address is set when the console is built. Without it,
// the link opens the API reference the server generates at /docs.
const DOCS = process.env.NEXT_PUBLIC_DOCS_URL || "/docs";

const TIERS = [
  { name: "Free", price: "$0", unit: "forever", points: ["1 application, built into a practice world once", "40 episodes a month, run in quiet hours", "1 sandbox at a time"], cta: "Start free", href: "/app/?mode=signup" },
  { name: "Pro", price: "$29", unit: "/ month", points: ["3 applications, 2 world builds a month", "750 episodes a month, run at once", "2 sandboxes at a time", "Top-ups when you need more"], cta: "Buy Pro", href: "/app/billing/?buy=pro_monthly", featured: true },
  { name: "Team", price: "$149", unit: "/ month", points: ["20 applications, 8 world builds a month", "3,000 episodes a month", "4 sandboxes at a time", "Top-ups when you need more"], cta: "Buy Team", href: "/app/billing/?buy=team_monthly" },
  { name: "Enterprise", price: "Custom", unit: "from $3,000 a month", points: ["Runner inside your own cloud account", "Single sign-on, audit export, retention controls", "Private held-out evaluation of vendor agents"], cta: "Talk to us", href: CONTACT || "#cta" },
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
            <span className="grid size-8 place-items-center rounded-[9px] bg-[linear-gradient(180deg,#b7cbff_0%,#86a6ff_24%,#3a66e8_25%,#2446b8_100%)] shadow-[inset_0_1px_0_rgb(255_255_255/0.5)]" aria-hidden="true"><span className="size-2.5 rotate-45 rounded-[2px] bg-white" /></span>
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

      {/* Between the two pictures the page is black, like their frames, in both themes; the mouse leaves blue pixels on it */}
      <PixelTrail className="dark bg-black text-foreground">
      {/* Features: bento grid */}
      <section id="features">
        <div className="mx-auto max-w-[1760px] px-4 py-24 md:px-8 xl:px-12">
          <SectionHead title="Everything a rehearsal needs, built from your app" body="Mocks agree with whatever the agent does, and production is too risky to practise in. Rehearsal builds the middle ground automatically." />
          <BentoGrid className="mt-14">
            <BentoCard className="lg:col-span-2"Icon={Workflow} name="The World Compiler" description="An agent reads your source, starts your real images in an isolated sandbox, seeds fictional data, chooses the tools each role may use, and writes jobs it proves can be passed and failed." visual={<CompilerScene />} href="#live" cta="Watch a build" />
            <BentoCard Icon={MessageSquareDiff} name="Customers who change their minds" description="Simulated customers revise requests mid-task. Agents that finish the old request get caught." visual={<CustomerScene />} />
            <BentoCard Icon={TimerOff} name="Failures on purpose" description="Requests time out after the change went through. Blind retries show up as duplicates." visual={<FaultScene />} />
            <BentoCard className="lg:col-span-2"Icon={Database} name="Verified in your database, not by an LLM" description="Read-only checks against the application's own records decide every outcome, so a confident agent can't talk its way to a pass." visual={<VerifyScene />} />
            <BentoCard className="lg:col-span-2"Icon={GitCompareArrows} name="Improve the agent, then compare" description="The improvement agent proposes changes from failed training jobs. Compare versions on jobs neither version has seen." visual={<ImproveScene />} />
            <BentoCard Icon={Activity} name="Every step traced" description="Each build and rehearsal is a Tracing trace: model calls, tool calls, and checks." visual={<TraceScene />} />
          </BentoGrid>
          <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-dashed bg-card/40 px-5 py-4">
            <span className="rounded-full border border-primary/40 bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">Coming soon</span>
            <span className="font-medium">Train your own model on your practice worlds.</span>
            <span className="text-sm text-muted-foreground">Every episode already ends with a score verified in your database: the reward reinforcement learning needs.</span>
          </div>
        </div>
      </section>

      {/* What gets measured */}
      <section className="border-t border-white/10">
        <div className="mx-auto max-w-[2400px] px-4 py-24 md:px-8 xl:px-16 2xl:px-24">
          <SectionHead title="A readiness verdict, with evidence" body="For every agent on every application: ready to pilot, or not yet. Each measure links to the episodes behind it. Switch agents, or pick a measure to see its evidence." />
          <div className="mt-14"><VerdictReport /></div>
        </div>
      </section>

      <section id="pricing" className="border-t border-white/10">
        <div className="mx-auto max-w-[1440px] px-4 py-24 md:px-8 xl:px-12">
          <SectionHead title="Pricing" body="Start free and keep the free plan. Pay when you rehearse more often. The open-source core stays free to self-host with your own model key." />
          <div className="mt-14 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {TIERS.map((t) => (
              <SpotlightCard key={t.name} className={t.featured ? "border-primary/60 shadow-[0_0_0_1px_var(--primary),0_20px_60px_-20px_var(--primary)]" : ""}>
                <div className="flex min-h-[420px] flex-col lg:min-h-[460px] lg:p-2">
                <div className="flex items-center justify-between"><h3 className="text-lg font-semibold">{t.name}</h3>{t.featured && <span className="rounded-full bg-primary/15 px-2.5 py-0.5 text-xs font-medium text-primary">Recommended</span>}</div>
                <p className="mt-6"><span className="font-heading text-5xl font-bold">{t.price}</span> <span className="text-sm text-muted-foreground">{t.unit}</span></p>
                <ul className="mt-8 space-y-3.5 text-[15px]">
                  {t.points.map((p) => <li key={p} className="flex gap-2"><CircleCheck className="mt-0.5 size-4 shrink-0 text-success" />{p}</li>)}
                </ul>
                <div className="mt-auto pt-8"><Button asChild className="w-full" variant={t.featured ? "default" : "outline"}>{t.href.startsWith("/") ? <Link href={t.href}>{t.cta}</Link> : <a href={t.href}>{t.cta}</a>}</Button></div>
                </div>
              </SpotlightCard>
            ))}
          </div>
          <p className="mt-8 text-center text-sm text-muted-foreground">Yearly plans get two months free. Need more in a month? Add 1,000 episodes for $30, or a world build for $15. Nothing renews by itself, and every job has a spend cap.</p>
        </div>
      </section>

      <section id="faq" className="border-t border-white/10">
        <div className="mx-auto grid max-w-[1440px] gap-10 px-4 py-24 md:px-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)] lg:gap-16 xl:px-12">
          <div>
            <h2 className="text-3xl font-bold tracking-tight md:text-[44px]">FAQ</h2>
            <p className="mt-4 max-w-md text-lg text-muted-foreground">How Rehearsal treats your data, what it runs, and what it costs. Anything else: <a href="#cta" className="underline underline-offset-4 hover:text-foreground">ask us</a>.</p>
          </div>
          <Accordion type="single" collapsible>
            {FAQ.map(([q, a]) => <AccordionItem key={q} value={q}><AccordionTrigger className="text-left text-base">{q}</AccordionTrigger><AccordionContent className="text-muted-foreground">{a}</AccordionContent></AccordionItem>)}
          </Accordion>
        </div>
      </section>
      </PixelTrail>

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
