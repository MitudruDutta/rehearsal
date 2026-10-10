"use client";

import { Boxes, GitBranch, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Stepper, StepperIndicator, StepperItem, StepperNav, StepperTitle, StepperTrigger } from "@/components/ui/stepper";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { post } from "../api";
import { routes } from "../nav";

/* First run after sign-up: workspace, first application, first build. Steps after the first can be
   skipped; the dashboard's checklist picks up whatever is left. API keys live in Settings, for the CLI and CI. */

const STEPS = ["Workspace", "Application", "First build"];

function Steps({ at }: { at: number }) {
  // ReUI stepper in its "progress segments" form, matching the build-phase bars elsewhere in the console
  return (
    <Stepper value={at + 1} className="mb-8">
      <StepperNav className="gap-2">
        {STEPS.map((label, i) => (
          <StepperItem key={label} step={i + 1} completed={i < at} disabled className="flex-1">
            <StepperTrigger className="flex w-full flex-col items-start gap-2" tabIndex={-1}>
              <StepperIndicator className="h-1.5 w-full rounded-full data-[state=completed]:bg-success data-[state=inactive]:bg-muted" />
              <StepperTitle className="text-xs font-medium group-data-[state=inactive]/step:text-muted-foreground">{label}</StepperTitle>
            </StepperTrigger>
          </StepperItem>
        ))}
      </StepperNav>
    </Stepper>
  );
}

function Choice({ icon: Icon, title, body, selected, onClick }: { icon: typeof Boxes; title: string; body: string; selected: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={selected} className={cn("flex w-full gap-3 rounded-lg border p-4 text-left transition-colors hover:bg-accent", selected && "border-primary bg-primary/10")}>
      <Icon className="mt-0.5 size-5 shrink-0 text-primary" />
      <span className="min-w-0">
        <span className="block font-medium">{title}</span>
        <span className="mt-0.5 block text-sm text-muted-foreground">{body}</span>
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
  const build = (appId: string) =>
    run(async () => {
      const r = await post<any>("/v1/world-builds", { application_id: appId });
      toast.success("Build started. The World Compiler is reading the source.");
      onDone(routes.build(r.job_id));
    });

  return (
    <div className="flex min-h-svh items-center justify-center bg-muted/40 p-6 md:p-10">
      <Card className="w-full max-w-2xl">
        <CardHeader>
          <div className="mb-2 flex items-center gap-2.5">
            <span className="size-3.5 rotate-45 rounded-[3px] bg-primary" aria-hidden="true" />
            <span className="font-heading text-lg font-bold">Rehearsal</span>
          </div>
          <CardTitle className="text-2xl">{["Name your workspace", "Add your first application", "Build your first practice world"][step]}</CardTitle>
          <CardDescription>
            {[
              "Your organisation owns its projects; invite teammates to it later.",
              "Rehearsal reads the source at a pinned commit and runs the images you list, in an isolated network with fictional data. It never touches production.",
              "The World Compiler starts the application in a sandbox, seeds fictional data, chooses agent tools, and writes jobs it proves can be passed and failed. It takes 20 to 60 minutes.",
            ][step]}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Steps at={step} />
          {error && <Alert variant="destructive" className="mb-4"><AlertDescription>{error}</AlertDescription></Alert>}

          {step === 0 && (
            <form onSubmit={createWorkspace}>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="org">Organisation</FieldLabel>
                  <Input id="org" required value={workspace.organization} onChange={(e) => setWorkspace({ ...workspace, organization: e.target.value })} />
                </Field>
                <Field>
                  <FieldLabel htmlFor="project">First project</FieldLabel>
                  <Input id="project" required value={workspace.project} onChange={(e) => setWorkspace({ ...workspace, project: e.target.value })} />
                  <FieldDescription>A project holds applications, worlds, agents, and runs. Use one per product.</FieldDescription>
                </Field>
                <Button type="submit" disabled={busy || !workspace.organization.trim()}>{busy ? "Creating…" : "Create workspace"}</Button>
              </FieldGroup>
            </form>
          )}

          {step === 1 && (
            <div className="grid gap-4">
              <Choice icon={Sparkles} title="Start with the sample applications" body="Gitea, Chatwoot, and Saleor: real open-source apps pinned to exact versions, ready to build." selected={source === "samples"} onClick={() => setSource("samples")} />
              <Choice icon={GitBranch} title="Connect your own application" body="A Git repository at a pinned commit, plus the container images you already publish." selected={source === "own"} onClick={() => setSource("own")} />
              {source === "own" && (
                <FieldGroup className="gap-4 rounded-lg border p-4">
                  <Field><FieldLabel htmlFor="n">Name</FieldLabel><Input id="n" value={own.name} onChange={(e) => setOwn({ ...own, name: e.target.value })} placeholder="billing-service" /></Field>
                  <Field><FieldLabel htmlFor="u">Git repository URL</FieldLabel><Input id="u" value={own.url} onChange={(e) => setOwn({ ...own, url: e.target.value })} placeholder="https://github.com/acme/billing" /></Field>
                  <Field><FieldLabel htmlFor="c">Commit</FieldLabel><Input id="c" value={own.commit} onChange={(e) => setOwn({ ...own, commit: e.target.value })} placeholder="Full SHA; the default branch head if empty" /></Field>
                  <Field>
                    <FieldLabel htmlFor="i">Images, one per line</FieldLabel>
                    <Textarea id="i" rows={3} value={own.images} onChange={(e) => setOwn({ ...own, images: e.target.value })} placeholder={"app=registry/app:1.2@sha256:…\npostgres=postgres:16@sha256:…"} />
                    <FieldDescription>Pin images by digest so every rebuild runs the same software.</FieldDescription>
                  </Field>
                </FieldGroup>
              )}
              <div className="flex flex-wrap justify-between gap-2">
                <Button variant="ghost" onClick={() => setStep(2)}>Skip for now</Button>
                <Button disabled={busy || !source || (source === "own" && (!own.name.trim() || !own.url.trim()))} onClick={addApplications}>
                  {busy ? "Adding…" : source === "samples" ? "Add sample applications" : "Add application"}
                </Button>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="grid gap-3">
              {apps.length === 0 && <p className="text-sm text-muted-foreground">Add an application from the Applications page when you are ready; its build starts from there.</p>}
              {apps.map((a) => (
                <div key={a.id} className="flex items-center justify-between gap-3 rounded-lg border p-3">
                  <span className="flex items-center gap-2 font-medium"><Boxes className="size-4 text-primary" /> {a.name}</span>
                  <Button size="sm" disabled={busy} onClick={() => build(a.id)}>Build world</Button>
                </div>
              ))}
              <Button variant={apps.length ? "ghost" : "default"} className="justify-self-end" onClick={() => onDone()}>Open the console</Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
