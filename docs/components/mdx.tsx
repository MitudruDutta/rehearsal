import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import type { MDXComponents } from "mdx/types";
import defaultMdxComponents from "fumadocs-ui/mdx";
import { Callout } from "fumadocs-ui/components/callout";
import { Step, Steps } from "fumadocs-ui/components/steps";
import { Tab, Tabs } from "fumadocs-ui/components/tabs";
import { ArrowRight, Clock, ListChecks } from "lucide-react";
import { ArchitectureDiagram, EpisodeDiagram, WorldDiagram } from "./diagrams";

/* ---- Callouts: one idea each, a coloured edge, an icon and a word, so colour is never the only signal ---- */

type CalloutProps = { title?: ReactNode; children: ReactNode };
export const Note = ({ title = "Note", children }: CalloutProps) => <Callout type="info" title={title}>{children}</Callout>;
export const Tip = ({ title = "Tip", children }: CalloutProps) => <Callout type="success" title={title}>{children}</Callout>;
export const Caution = ({ title = "Caution", children }: CalloutProps) => <Callout type="warn" title={title}>{children}</Callout>;
export const Danger = ({ title = "Cannot be undone", children }: CalloutProps) => <Callout type="error" title={title}>{children}</Callout>;

/** Goes before any step that spends model budget: says roughly how much, and how to limit it. */
export function Cost({ amount, children }: { amount?: string; children: ReactNode }) {
  return (
    <aside
      aria-label="Costs money"
      className="my-5 flex max-w-(--rh-measure) gap-3 rounded-lg border border-warning/35 bg-warning/[0.07] p-3.5 text-[0.9375rem] leading-6"
    >
      <span aria-hidden="true" className="mt-px grid size-6 shrink-0 place-items-center rounded-md bg-warning/15 font-mono text-sm font-semibold text-warning">
        $
      </span>
      <div className="min-w-0 [&_p]:my-0 [&_p+p]:mt-2">
        <p className="font-semibold text-foreground">Costs money{amount ? `: ${amount}` : ""}</p>
        {children}
        <p>
          <Link href="/get-started/what-costs-money">What costs money</Link>
        </p>
      </div>
    </aside>
  );
}

/* ---- Small marks ---- */

const LABELS = {
  "coming-soon": ["Coming soon", "border-info/30 bg-info/10 text-info"],
  "self-hosted": ["Self-hosted only", "border-border bg-muted text-muted-foreground"],
  hosted: ["Hosted only", "border-border bg-muted text-muted-foreground"],
  generated: ["Generated from the code", "border-border bg-muted text-muted-foreground"],
  free: ["Free plan", "border-border bg-muted text-muted-foreground"],
  paid: ["Paid plans", "border-border bg-muted text-muted-foreground"],
} as const;

/** A small label beside the title or heading it applies to. */
export function Label({ kind, children }: { kind: keyof typeof LABELS; children?: ReactNode }) {
  const [text, tone] = LABELS[kind];
  return (
    <span className={`not-prose inline-flex items-center whitespace-nowrap rounded-md border px-1.5 py-px align-middle font-sans text-xs font-medium ${tone}`}>
      {children ?? text}
    </span>
  );
}

const VERDICTS = {
  verified: ["verified", "border-success/30 bg-success/15 text-success"],
  "not-achieved": ["not achieved", "border-warning/30 bg-warning/15 text-warning"],
  "rule-violated": ["rule violated", "border-destructive/30 bg-destructive/15 text-danger"],
  "not-scored": ["not scored", "border-border bg-muted text-muted-foreground"],
} as const;

/** An episode's outcome, in the console's words and colours. */
export function Verdict({ is }: { is: keyof typeof VERDICTS }) {
  const [text, tone] = VERDICTS[is];
  return (
    <span className={`not-prose inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border px-1.5 py-px align-middle font-sans text-xs font-medium ${tone}`}>
      <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
      {text}
    </span>
  );
}

/** Time, cost and prerequisites under a guide's title. Filled from the page's front matter. */
export function MetaRow({ time, cost, needs }: { time?: string; cost?: string; needs?: string }) {
  if (!time && !cost && !needs) return null;
  return (
    <dl className="flex flex-wrap gap-x-6 gap-y-2 border-y py-3 text-sm text-muted-foreground">
      {time && (
        <div className="flex items-center gap-1.5">
          <Clock className="size-4" aria-hidden="true" />
          <dt className="sr-only">Time</dt>
          <dd>{time}</dd>
        </div>
      )}
      {cost && (
        <div className="flex items-center gap-1.5">
          <span aria-hidden="true" className="grid size-4 place-items-center font-mono text-[13px] font-semibold text-warning">$</span>
          <dt className="sr-only">Cost</dt>
          <dd>
            <Link href="/get-started/what-costs-money" className="underline decoration-border underline-offset-4 hover:text-foreground">
              {cost}
            </Link>
          </dd>
        </div>
      )}
      {needs && (
        <div className="flex items-center gap-1.5">
          <ListChecks className="size-4" aria-hidden="true" />
          <dt>Needs:</dt>
          <dd>{needs}</dd>
        </div>
      )}
    </dl>
  );
}

/* ---- The ten build phases, with the names and order the console's build view shows ---- */

const PHASES: [key: string, label: string][] = [
  ["inspect", "Read the source"],
  ["research", "Research real use"],
  ["plan", "Plan the runtime"],
  ["materialize", "Start the sandbox"],
  ["discover", "Find the API"],
  ["seed", "Seed fictional data"],
  ["adapt", "Choose agent tools"],
  ["author", "Write scenarios"],
  ["validate", "Validate and repair"],
  ["package", "Publish"],
];

export function PhaseStrip({ at }: { at?: string }) {
  const current = PHASES.findIndex(([key]) => key === at);
  return (
    <ol aria-label="The ten build phases" className="not-prose my-6 grid max-w-(--rh-column) grid-cols-3 gap-x-2 gap-y-4 md:grid-cols-10">
      {PHASES.map(([key, label], i) => (
        <li key={key} className="min-w-0">
          <div className={`h-1.5 rounded-full ${current < 0 || i < current ? "bg-success" : i === current ? "bg-primary" : "bg-muted"}`} />
          <div className="mt-2 text-[13px] font-medium leading-snug text-foreground">
            {i + 1}. {label}
          </div>
          <div className="mt-0.5 font-mono text-[11px] leading-4 text-muted-foreground [overflow-wrap:anywhere]">{key}</div>
        </li>
      ))}
    </ol>
  );
}

/* ---- Reference ---- */

const METHODS: Record<string, string> = {
  GET: "border-info/30 bg-info/10 text-info",
  POST: "border-success/30 bg-success/10 text-success",
  PUT: "border-success/30 bg-success/10 text-success",
  PATCH: "border-success/30 bg-success/10 text-success",
  DELETE: "border-destructive/30 bg-destructive/10 text-danger",
};

/** Method, path and the access an API operation needs. Reading is blue, changing is green, removing is red. */
export function Operation({ method, path, access, costs }: { method: string; path: string; access?: string; costs?: boolean }) {
  return (
    <div className="not-prose my-4 flex max-w-(--rh-column) flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border bg-card px-3 py-2.5">
      <span className={`rounded-md border px-1.5 py-0.5 font-mono text-xs font-semibold ${METHODS[method.toUpperCase()] ?? METHODS.GET}`}>
        {method.toUpperCase()}
      </span>
      <code className="min-w-0 break-all font-mono text-sm text-foreground">{path}</code>
      <span className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
        {access && (
          <span>
            Needs access: <span className="font-medium text-foreground">{access}</span>
          </span>
        )}
        {costs && <span className="font-medium text-warning">$ Costs money</span>}
      </span>
    </div>
  );
}

/** What the reader should see after a step. Quieter than a command, and it has no copy button. */
export function Output({ label = "You see", children }: { label?: string; children: ReactNode }) {
  return (
    <div className="rh-output my-4 max-w-(--rh-column)">
      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      {children}
    </div>
  );
}

/** A product term on first use: a dotted underline, with the definition on hover and on keyboard focus. */
export function Term({ def, children }: { def: string; children: ReactNode }) {
  return (
    <span tabIndex={0} className="group/term relative cursor-help underline decoration-muted-foreground/60 decoration-dotted underline-offset-4">
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute left-0 top-full z-20 mt-1.5 hidden w-64 rounded-lg border bg-fd-popover p-2.5 text-sm font-normal leading-5 text-fd-popover-foreground shadow-lg group-hover/term:block group-focus/term:block"
      >
        {def}
      </span>
    </span>
  );
}

/* ---- Links to other pages ---- */

export function LinkCards({ children }: { children: ReactNode }) {
  return <div className="not-prose my-6 grid max-w-(--rh-column) gap-3 sm:grid-cols-2">{children}</div>;
}

export function LinkCard({ href, title, children }: { href: string; title: string; children?: ReactNode }) {
  return (
    <Link
      href={href}
      data-card
      className="group flex flex-col rounded-lg border bg-card p-4 transition-colors hover:border-primary/50 hover:bg-accent/40"
    >
      <span className="flex items-center gap-1.5 font-heading text-base font-semibold text-foreground">
        {title}
        <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-link" aria-hidden="true" />
      </span>
      {children && <span className="mt-1 text-sm leading-6 text-muted-foreground">{children}</span>}
    </Link>
  );
}

/* ---- Tabs whose choice applies to every group on the site and is remembered ---- */

/** Ways to do one task: Console, CLI, Python, MCP, HTTP. */
export function Ways({ items, children }: { items: string[]; children: ReactNode }) {
  return (
    <Tabs items={items} groupId="way" persist className="max-w-(--rh-column)">
      {children}
    </Tabs>
  );
}

/** Commands that differ by operating system. */
export function OS({ items = ["macOS and Linux", "Windows (PowerShell)"], children }: { items?: string[]; children: ReactNode }) {
  return (
    <Tabs items={items} groupId="os" persist className="max-w-(--rh-column)">
      {children}
    </Tabs>
  );
}

function Table(props: ComponentProps<"table">) {
  const Base = defaultMdxComponents.table;
  return (
    <div className="max-w-(--rh-column)">
      <Base {...props} />
    </div>
  );
}

export function getMDXComponents(components?: MDXComponents): MDXComponents {
  return {
    ...defaultMdxComponents,
    table: Table,
    Note,
    Tip,
    Caution,
    Danger,
    Cost,
    Label,
    Verdict,
    PhaseStrip,
    Operation,
    Output,
    Term,
    LinkCards,
    LinkCard,
    Steps,
    Step,
    Tabs,
    Tab,
    Ways,
    OS,
    WorldDiagram,
    EpisodeDiagram,
    ArchitectureDiagram,
    ...components,
  };
}
