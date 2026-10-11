"use client";

import { ArrowRight, Boxes, CircleAlert, GitBranch, LoaderCircle, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { AuthShell } from "@/components/auth-shell";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { post, sentence } from "../api";
import { routes } from "../nav";
import { signOut } from "./Settings";

/* First run after sign-up: workspace, first application, first build. Steps after the first can be
   skipped; the dashboard's checklist picks up whatever is left. API keys live in Settings, for the CLI and CI.
   It sits in the same frame as sign-in, so the picture stays where it was and only the work changes. The screen
   shows the step in hand and nothing else: no account menu, no links out. */

const STEPS = [
  { name: "Workspace", title: "Name your workspace", lead: "Your organisation owns its projects. You can invite teammates to it later." },
  { name: "Application", title: "Add your first application", lead: "Rehearsal runs it in an isolated network with fictional data. It never touches production." },
  { name: "First build", title: "Build your first practice world", lead: "The World Compiler starts the application in a sandbox, seeds fictional data, and writes jobs it proves can be passed and failed." },
];

/** Where the person is, above the title: three bars and "Step 2 of 3". */
function Progress({ at }: { at: number }) {
  return (
    <div className="mb-6">
      <ol className="flex gap-1.5" aria-label="Setup steps">
        {STEPS.map((s, i) => (
          <li key={s.name} aria-current={i === at ? "step" : undefined} className={cn("h-1 flex-1 rounded-full", i < at ? "bg-success" : i === at ? "bg-primary" : "bg-muted")}>
            <span className="sr-only">{s.name}{i < at ? ", done" : ""}</span>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-xs font-medium tracking-wide text-muted-foreground uppercase">
        Step {at + 1} of {STEPS.length} <span className="mx-1 opacity-50">/</span> {STEPS[at].name}
      </p>
    </div>
  );
}

function Choice({ icon: Icon, title, body, selected, onSelect }: { icon: typeof Boxes; title: string; body: string; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn(
        "flex w-full items-start gap-3.5 rounded-xl border p-4 text-left outline-none transition-colors hover:bg-accent/60 focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
        selected && "border-primary bg-primary/[0.07] hover:bg-primary/[0.07]",
      )}
    >
      <span className={cn("grid size-9 shrink-0 place-items-center rounded-lg border bg-muted text-muted-foreground", selected && "border-primary/40 bg-primary/15 text-primary")}>
        <Icon className="size-[18px]" aria-hidden="true" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[0.9375rem] font-semibold">{title}</span>
        <span className="mt-0.5 block text-sm leading-5 text-muted-foreground">{body}</span>
      </span>
      <span className={cn("mt-1 grid size-4 shrink-0 place-items-center rounded-full border", selected && "border-primary")} aria-hidden="true">
        {selected && <span className="size-2 rounded-full bg-primary" />}
      </span>
    </button>
  );
}

export function Onboarding({ firstName, onDone }: { firstName: string; onDone: (go?: string) => void }) {
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [workspace, setWorkspace] = useState({ organization: firstName ? `${firstName}'s team` : "", project: "default" });
  const [source, setSource] = useState<"samples" | "own" | null>(null);
  const [own, setOwn] = useState({ name: "", url: "", commit: "", images: "" });
  const [apps, setApps] = useState<{ id: string; name: string }[]>([]);
  const [building, setBuilding] = useState<string | null>(null);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const createWorkspace = (e: React.FormEvent) => {
    e.preventDefault();
    run(async () => {
      await post("/v1/onboarding/workspace", workspace);
      setStep(1);
    });
  };
  const addApplications = () =>
    run(async () => {
      if (source === "samples") {
        const list = await post<any[]>("/v1/applications/import-catalog");
        setApps(list.map((a) => ({ id: a.id, name: a.name })));
      } else {
        const images = Object.fromEntries(own.images.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => l.split("=", 2).map((x) => x.trim())));
        const a = await post<any>("/v1/applications", { name: own.name, source: { kind: "git", url: own.url, commit: own.commit || undefined }, images });
        setApps([{ id: a.id, name: a.name }]);
      }
      setStep(2);
    });
  const build = (appId: string) => {
    setBuilding(appId);
    return run(async () => {
      const r = await post<any>("/v1/world-builds", { application_id: appId });
      toast.success("Build started. The World Compiler is reading the source.");
      onDone(routes.build(r.job_id));
    }).finally(() => setBuilding(null));
  };

  const at = STEPS[step];
  return (
    <AuthShell>
      <Progress at={step} />
      <h1 className="text-[1.75rem] font-bold leading-tight tracking-tight">{at.title}</h1>
      <p className="mt-2 text-[0.9375rem] leading-6 text-muted-foreground">{at.lead}</p>
      <div className="mt-7">
        {error && (
          <Alert variant="destructive" className="mb-4">
            <CircleAlert />
            <AlertDescription>
              {sentence(error)}
              {/* A workspace is refused for reasons that belong to the account (it owns one already, or this browser
                  made one with another account). The way on is the other account, so the way to it is offered here. */}
              {step === 0 && (
                <Button type="button" variant="outline" size="sm" className="mt-2 text-foreground" onClick={signOut}>
                  Sign in with another account
                </Button>
              )}
            </AlertDescription>
          </Alert>
        )}

        {step === 0 && (
          <form onSubmit={createWorkspace}>
            <FieldGroup className="gap-4">
              <Field>
                <FieldLabel htmlFor="org">Organisation</FieldLabel>
                <Input id="org" autoFocus required value={workspace.organization} onChange={(e) => setWorkspace({ ...workspace, organization: e.target.value })} placeholder="Acme" className="h-10" />
              </Field>
              <Field>
                <FieldLabel htmlFor="project">First project</FieldLabel>
                <Input id="project" required value={workspace.project} onChange={(e) => setWorkspace({ ...workspace, project: e.target.value })} className="h-10" />
                <FieldDescription>A project holds applications, worlds, agents, and runs. Use one per product.</FieldDescription>
              </Field>
              <Button type="submit" size="lg" className="mt-1 w-full" disabled={busy || !workspace.organization.trim()}>
                {busy ? <><LoaderCircle className="animate-spin" /> Creating…</> : <>Create workspace <ArrowRight /></>}
              </Button>
            </FieldGroup>
          </form>
        )}

        {step === 1 && (
          <div className="grid gap-3">
            <div role="radiogroup" aria-label="Where the first application comes from" className="grid gap-3">
              <Choice icon={Sparkles} title="Start with the sample applications" body="Open-source applications pinned to exact versions, Gitea, Chatwoot and Saleor among them, ready to build." selected={source === "samples"} onSelect={() => setSource("samples")} />
              <Choice icon={GitBranch} title="Connect your own application" body="A Git repository at a pinned commit, plus the container images you already publish." selected={source === "own"} onSelect={() => setSource("own")} />
            </div>
            {source === "own" && (
              <FieldGroup className="gap-4 rounded-xl border bg-muted/30 p-4">
                <Field><FieldLabel htmlFor="n">Name</FieldLabel><Input id="n" autoFocus value={own.name} onChange={(e) => setOwn({ ...own, name: e.target.value })} placeholder="billing-service" /></Field>
                <Field><FieldLabel htmlFor="u">Git repository URL</FieldLabel><Input id="u" value={own.url} onChange={(e) => setOwn({ ...own, url: e.target.value })} placeholder="https://github.com/acme/billing" /></Field>
                <Field><FieldLabel htmlFor="c">Commit</FieldLabel><Input id="c" value={own.commit} onChange={(e) => setOwn({ ...own, commit: e.target.value })} placeholder="Full SHA; the default branch head if empty" /></Field>
                <Field>
                  <FieldLabel htmlFor="i">Images, one per line</FieldLabel>
                  <Textarea id="i" rows={3} value={own.images} onChange={(e) => setOwn({ ...own, images: e.target.value })} placeholder={"app=registry/app:1.2@sha256:…\npostgres=postgres:16@sha256:…"} className="font-mono text-[13px]" />
                  <FieldDescription>Pin images by digest so every rebuild runs the same software.</FieldDescription>
                </Field>
              </FieldGroup>
            )}
            <div className="mt-3 flex items-center justify-between gap-2">
              <Button variant="ghost" className="text-muted-foreground" disabled={busy} onClick={() => { setError(null); setStep(2); }}>Skip for now</Button>
              <Button size="lg" disabled={busy || !source || (source === "own" && (!own.name.trim() || !own.url.trim()))} onClick={addApplications}>
                {busy ? <><LoaderCircle className="animate-spin" /> Adding…</> : <>{source === "samples" ? "Add sample applications" : "Add application"} <ArrowRight /></>}
              </Button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="grid gap-4">
            {apps.length > 0 ? (
              <>
                <ul className="divide-y overflow-hidden rounded-xl border">
                  {apps.map((a) => (
                    <li key={a.id} className="flex items-center justify-between gap-3 px-3.5 py-2">
                      <span className="flex min-w-0 items-center gap-2.5 text-sm font-medium">
                        <Boxes className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                        <span className="truncate">{a.name}</span>
                      </span>
                      <Button size="sm" variant={apps.length === 1 ? "default" : "outline"} disabled={busy} onClick={() => build(a.id)}>
                        {building === a.id ? <><LoaderCircle className="animate-spin" /> Starting…</> : "Build world"}
                      </Button>
                    </li>
                  ))}
                </ul>
                <p className="text-sm leading-6 text-muted-foreground">
                  A build runs on the server and spends model budget. It can take from under an hour to a few hours. You can leave the page: the console shows its progress.
                </p>
              </>
            ) : (
              <p className="rounded-xl border bg-muted/30 p-4 text-sm leading-6 text-muted-foreground">
                No application yet. Add one from the Applications page when you are ready; its build starts from there.
              </p>
            )}
            <Button size={apps.length ? "default" : "lg"} variant={apps.length ? "ghost" : "default"} className={cn(apps.length ? "justify-self-end text-muted-foreground" : "w-full")} disabled={busy} onClick={() => onDone()}>
              {apps.length ? "Not now, open the console" : "Open the console"} <ArrowRight />
            </Button>
          </div>
        )}
      </div>
    </AuthShell>
  );
}
