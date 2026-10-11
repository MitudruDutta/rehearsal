import Link from "next/link";
import { Fragment } from "react";
import { ArrowRight, BookOpen, Bot, Braces, type LucideIcon, MonitorPlay, Rocket, Server, ShieldCheck, SquareTerminal } from "lucide-react";
import { AskAiButton, AskChip } from "@/components/assistant/buttons";
import { CopyButton } from "@/components/copy-button";
import { SearchField } from "@/components/site-header";
import { sections, site } from "@/lib/site";
import { pagesBySection } from "@/lib/source";

const START = [
  {
    href: "/get-started/quickstart-console",
    icon: MonitorPlay,
    title: "In the console",
    body: "Add an application, build a world and run an agent in the browser. No code.",
  },
  {
    href: "/get-started/quickstart-cli",
    icon: SquareTerminal,
    title: "From a terminal",
    body: "The same result with the rehearsal command, or a few lines of Python.",
  },
  {
    href: "/get-started/quickstart-ai-assistant",
    icon: Bot,
    title: "With your AI assistant",
    body: "Install the plugin, then ask Claude Code, Codex or Cursor to do it.",
  },
];

const TASKS: [string, string][] = [
  ["Add my application", "/guides/add-an-application"],
  ["Build a practice world", "/guides/build-a-practice-world"],
  ["Evaluate an agent", "/guides/evaluate-an-agent"],
  ["Read why an episode failed", "/guides/read-results"],
  ["Improve an agent and compare versions", "/guides/improve-an-agent"],
  ["Test an agent I wrote myself", "/guides/bring-your-own-agent"],
  ["Check every pull request in CI", "/guides/use-rehearsal-in-ci"],
  ["Run my own server", "/self-hosting/install-with-docker-compose"],
];

const LOOK_UP: [string, string][] = [
  ["CLI", "/reference/cli"],
  ["REST API", "/reference/api"],
  ["Python SDK", "/reference/python-sdk"],
  ["MCP tools", "/ai-assistants/mcp-tools"],
  ["Errors", "/reference/errors"],
  ["Configuration", "/reference/configuration"],
  ["Plans and limits", "/reference/plans-and-limits"],
  ["Troubleshooting", "/self-hosting/troubleshooting"],
];

const ASK = ["How do I evaluate an agent?", "What does a build cost?", "How does scoring work?"];

// the same icons the sidebar shows, which content/<section>/meta.json names
const ICONS: Record<string, LucideIcon> = {
  "/get-started": Rocket,
  "/guides": BookOpen,
  "/ai-assistants": Bot,
  "/reference": Braces,
  "/self-hosting": Server,
  "/plans-and-trust": ShieldCheck,
};

/** The first run, as the CLI quickstart gives it. A line that starts with # is a remark, not a command. */
const FIRST_RUN = [
  "# 1. Install and sign in",
  "pip install rehearsal-kit",
  "rehearsal login",
  "",
  "# 2. Find a published world version",
  "rehearsal worlds list",
  "",
  "# 3. Run your agent through its jobs, and watch",
  "rehearsal eval <wv_id> --profile <profile_id> --split dev --repeats 2 --watch",
];

function FirstRun() {
  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      <div className="flex items-center gap-2 border-b px-4 py-2.5">
        <SquareTerminal className="size-4 text-muted-foreground" aria-hidden="true" />
        <span className="text-sm font-medium text-foreground">A first run from a terminal</span>
        <CopyButton className="ml-auto" text={FIRST_RUN.filter((line) => line && !line.startsWith("#")).join("\n")} />
      </div>
      {/* a command longer than the card continues on the next line, set in, so it still reads as one command */}
      <pre className="whitespace-pre-wrap px-4 py-3.5 font-mono text-[0.8125rem] leading-6 text-foreground">
        <code>
          {FIRST_RUN.map((line, i) => (
            <span key={i} className={`block min-h-6 pl-[2ch] -indent-[2ch] ${line.startsWith("#") ? "text-muted-foreground" : ""}`}>
              {/* A line breaks between words only, never inside an option such as --split. A value the reader must
                  replace, written <like_this>, is amber and slanted, as in every sample. */}
              {line.split(" ").map((word, n) => (
                <Fragment key={n}>
                  <span className={`whitespace-nowrap ${/^<[a-z_]+>$/.test(word) ? "italic text-warning" : ""}`}>{word}</span>{" "}
                </Fragment>
              ))}
            </span>
          ))}
        </code>
      </pre>
      <Link
        href="/get-started/quickstart-cli"
        className="group flex items-center justify-between gap-3 border-t px-4 py-2.5 text-sm font-medium text-link transition-colors hover:bg-accent/40"
      >
        Each step, with what you should see
        <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
      </Link>
    </div>
  );
}

const heading = "font-heading text-xl font-bold tracking-tight text-foreground";

export default function Home() {
  const pages = new Map(pagesBySection().map((group) => [group.pages[0]?.url, group.pages.slice(1)]));
  return (
    <main id="content" className="@container min-w-0 [grid-area:main]">
      <div className="mx-auto w-full max-w-[86rem] px-4 pb-16 md:px-8 xl:px-10">
        <section className="grid grid-cols-[minmax(0,1fr)] items-center gap-x-12 gap-y-8 border-b py-10 @[62rem]:grid-cols-[minmax(0,1fr)_minmax(0,29rem)] @[62rem]:py-14">
          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">rehearsal-kit {site.version}</p>
            <h1 className="mt-3 font-heading text-4xl font-bold leading-[1.1] tracking-tight text-foreground @[62rem]:text-[2.75rem]">
              Rehearsal documentation
            </h1>
            <p className="mt-4 max-w-2xl text-lg leading-[1.875rem] text-muted-foreground">
              {site.tagline} Rehearsal builds a practice world from your application, runs your agent through real jobs
              in it, and reads the application&apos;s own database to decide each outcome.
            </p>
            <div className="mt-7 flex max-w-2xl gap-2">
              <SearchField className="h-11 min-w-0 flex-1 bg-card px-3.5 text-[0.9375rem]" label="Search, or paste an error message" />
              <AskAiButton className="h-11 bg-card px-4" />
            </div>
            <div className="mt-3 flex max-w-2xl flex-wrap items-center gap-2">
              <span className="text-sm text-muted-foreground">Ask:</span>
              {ASK.map((question) => (
                <AskChip key={question} question={question} className="px-2.5 py-1 text-[13px]" />
              ))}
            </div>
          </div>
          <FirstRun />
        </section>

        <section className="py-10">
          <h2 className={heading}>Start here</h2>
          <p className="mt-1 text-muted-foreground">Three ways to the same first result: a finished run with a verdict you can open.</p>
          <div className="mt-5 grid gap-4 @[44rem]:grid-cols-3">
            {START.map(({ href, icon: Icon, title, body }) => (
              <Link key={href} href={href} className="group flex flex-col rounded-xl border bg-card p-5 transition-colors hover:border-primary/50 hover:bg-accent/40">
                <span className="grid size-9 place-items-center rounded-lg border bg-muted text-foreground">
                  <Icon className="size-[18px]" aria-hidden="true" />
                </span>
                <span className="mt-4 font-heading text-lg font-semibold text-foreground">{title}</span>
                <span className="mt-1 flex-1 text-[0.9375rem] leading-6 text-muted-foreground">{body}</span>
                <span className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-link">
                  Start
                  <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
                </span>
              </Link>
            ))}
          </div>
        </section>

        <section className="border-t py-10">
          <h2 className={heading}>I want to…</h2>
          <ul className="mt-4 grid gap-x-4 gap-y-2 @[36rem]:grid-cols-2 @[66rem]:grid-cols-4">
            {TASKS.map(([label, href]) => (
              <li key={href}>
                <Link
                  href={href}
                  className="group flex h-full items-center justify-between gap-3 rounded-lg border bg-card px-3.5 py-3 text-[0.9375rem] leading-5 text-foreground transition-colors hover:border-primary/50 hover:bg-accent/40"
                >
                  {label}
                  <ArrowRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-link" aria-hidden="true" />
                </Link>
              </li>
            ))}
          </ul>
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <span className="mr-1 text-sm text-muted-foreground">Or look something up:</span>
            {LOOK_UP.map(([label, href]) => (
              <Link key={href} href={href} className="rounded-lg border bg-card px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:border-primary/50 hover:bg-accent/40">
                {label}
              </Link>
            ))}
          </div>
        </section>

        <section className="border-t pt-10">
          <h2 className={heading}>Every page</h2>
          <p className="mt-1 text-muted-foreground">Six sections. The sidebar has the same list on every page.</p>
          <div className="mt-5 grid gap-4 @[40rem]:grid-cols-2 @[66rem]:grid-cols-3">
            {sections.map((section) => {
              const Icon = ICONS[section.url] ?? BookOpen;
              return (
                <div key={section.url} className="flex flex-col rounded-xl border bg-card p-5">
                  <Link href={section.url} className="group flex items-start gap-3">
                    <span className="grid size-9 shrink-0 place-items-center rounded-lg border bg-muted text-foreground">
                      <Icon className="size-[18px]" aria-hidden="true" />
                    </span>
                    <span className="min-w-0">
                      <span className="block font-heading text-base font-semibold text-foreground group-hover:text-link">{section.title}</span>
                      <span className="mt-0.5 block text-sm leading-5 text-muted-foreground">{section.blurb}</span>
                    </span>
                  </Link>
                  <ul className="mt-4 grid gap-px border-t pt-3">
                    {(pages.get(section.url) ?? []).map((page) => (
                      <li key={page.url}>
                        <Link href={page.url} className="-mx-2 block rounded-md px-2 py-1.5 text-sm leading-5 text-prose transition-colors hover:bg-muted hover:text-foreground">
                          {page.data.title}
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </main>
  );
}
