"use client";

import { Download, PlayCircle, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader, Stat, StatusBadge, Tone } from "@/components/rh";
import { post, useResource } from "../api";
import { go, routes } from "../nav";

/** What each job attacks (compiler/stress.py). */
const STRESS: Record<string, string> = {
  changed_request: "Customer changes their mind",
  unknown_outcome: "Write times out after it succeeded",
  failure_recovery: "App refuses or fails",
  permission_boundary: "Work beyond the agent's role",
  social_engineering: "Customer pushes for something forbidden",
  injected_instructions: "Instructions hidden in app data",
  missing_information: "Request is missing a detail",
  privacy: "Data that must not leak",
  conflict: "Conflicting requests",
};

function Check({ ok, label }: { ok: boolean; label: string }) {
  return <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm"><span>{label}</span><Tone tone={ok ? "go" : "stop"}>{ok ? "yes" : "no"}</Tone></div>;
}

function ScenarioSheet({ sc, onClose, onChange }: { sc: any | null; onClose: () => void; onChange: () => void }) {
  const spec = sc?.spec;
  const v = sc?.validation || {};
  const act = async (verb: "approve" | "reject") => {
    await post(`/v1/scenarios/${sc.id}/${verb}`);
    toast.success(verb === "approve" ? "Scenario approved" : "Scenario rejected");
    onChange();
  };
  return (
    <Sheet open={!!sc} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full gap-0 p-0 sm:max-w-2xl">
        {sc && (
          <>
            <SheetHeader className="border-b p-5">
              <SheetTitle>{spec.title}</SheetTitle>
              <SheetDescription>{sc.family} · {sc.split}{STRESS[spec.stress] ? ` · tests: ${STRESS[spec.stress]}` : ""} · <StatusBadge status={sc.status} /></SheetDescription>
            </SheetHeader>
            <ScrollArea className="h-[calc(100vh-110px)]">
              <div className="space-y-6 p-5 text-sm">
                {v.live && (
                  <section className="space-y-1 rounded-md border p-3">
                    <h3 className="font-semibold">Tried by a live agent</h3>
                    <p>{v.live.passed ? "A live agent passed this job, so the checks accept real work."
                      : v.live.cause === "agent" ? "A live agent failed this job. The audit found the job fair: the failure was the agent's."
                      : v.live.cause === "inconclusive" ? "The live trial could not be completed, so this job is not proven yet."
                      : "Withdrawn: a live agent was failed for a reason that was not its fault."}</p>
                    {!v.live.passed && v.live.evidence && <p className="text-muted-foreground">{v.live.evidence}</p>}
                  </section>
                )}
                {spec.sources?.length > 0 && (
                  <section className="space-y-1.5 rounded-md border p-3">
                    <h3 className="font-semibold">Based on real use</h3>
                    <p className="text-muted-foreground">The compiler found this kind of request on the web before writing the job.</p>
                    <ul className="space-y-1">{spec.sources.map((u: string) => <li key={u} className="truncate"><a href={u} target="_blank" rel="noopener noreferrer nofollow" className="text-primary underline-offset-2 hover:underline">{u}</a></li>)}</ul>
                  </section>
                )}
                <section className="space-y-2">
                  <h3 className="font-semibold">The customer</h3>
                  <p><span className="font-medium">{spec.participant.name}</span>: &ldquo;{spec.participant.opening_message}&rdquo;</p>
                </section>
                <section className="space-y-2">
                  <h3 className="font-semibold">What they want, by version</h3>
                  <ol className="space-y-1.5">{spec.goals.map((g: any) => <li key={g.version} className="rounded-md border p-2"><span className="font-medium">v{g.version}</span> {g.instruction}</li>)}</ol>
                </section>
                {spec.events.length > 0 && (
                  <section className="space-y-2">
                    <h3 className="font-semibold">Scheduled events</h3>
                    <ul className="space-y-1.5">{spec.events.map((e: any) => (
                      <li key={e.id} className="rounded-md border p-2">{e.trigger.kind.replace(/_/g, " ")} {e.trigger.step ?? e.trigger.tool ?? ""}: {e.actions.map((a: any) => (a.kind === "fault" ? `${a.fault_mode.replace(/_/g, " ")} on ${a.tool}` : a.kind === "goal_change" ? `the request becomes v${a.goal_version}` : a.kind.replace(/_/g, " "))).join(", ")}</li>
                    ))}</ul>
                  </section>
                )}
                <section className="space-y-2">
                  <h3 className="font-semibold">Validation</h3>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <Check ok={(v.reference?.reward ?? 0) > 0} label="Reference run passes" />
                    <Check ok={!(v.noop && v.noop.reward > 0)} label="Not already true at start" />
                    {Object.entries(v.negatives || {}).map(([name, r]: [string, any]) => <Check key={name} ok={r.reward <= 0} label={`Rejects "${name}"`} />)}
                    {v.deterministic !== undefined && v.deterministic !== null && <Check ok={!!v.deterministic} label="Replays identically" />}
                  </div>
                  {v.reasons?.length > 0 && <p className="text-destructive">{v.reasons.join("; ")}</p>}
                </section>
                <Accordion type="multiple">
                  <AccordionItem value="checks">
                    <AccordionTrigger>Checks ({spec.checks.length})</AccordionTrigger>
                    <AccordionContent className="space-y-2">
                      {spec.checks.map((c: any) => (
                        <div key={c.id} className="rounded-md border p-2.5">
                          <div className="flex items-center justify-between gap-2"><span className="font-medium">{c.description}</span>{spec.constraints.includes(c.id) && <Tone tone="stop">must never fail</Tone>}</div>
                          <pre className="mt-2 overflow-x-auto rounded bg-muted p-2 text-xs">{c.query} {c.op} {JSON.stringify(c.value)}</pre>
                        </div>
                      ))}
                    </AccordionContent>
                  </AccordionItem>
                  <AccordionItem value="ref">
                    <AccordionTrigger>Reference run ({spec.reference.length} steps)</AccordionTrigger>
                    <AccordionContent><ol className="list-decimal space-y-1 pl-5">{spec.reference.map((s: any, i: number) => <li key={i}><code className="text-xs">{s.actor}: {s.tool}({JSON.stringify(s.args)})</code></li>)}</ol></AccordionContent>
                  </AccordionItem>
                  <AccordionItem value="neg">
                    <AccordionTrigger>Careless runs that must fail ({spec.negatives.length})</AccordionTrigger>
                    <AccordionContent className="space-y-2">{spec.negatives.map((n: any) => <div key={n.name} className="rounded-md border p-2"><span className="font-medium">{n.name}</span>: {n.description}</div>)}</AccordionContent>
                  </AccordionItem>
                </Accordion>
                <div className="flex gap-2">
                  {sc.status !== "approved" && sc.status !== "rejected" && <Button onClick={() => act("approve")}>Approve scenario</Button>}
                  {sc.status !== "rejected" && <Button variant="outline" className="text-destructive" onClick={() => act("reject")}>Reject scenario</Button>}
                </div>
              </div>
            </ScrollArea>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

const FINDINGS: [string, string, string][] = [["requests", "request", "What real users ask for"], ["rules", "rule", "Rules the application enforces"], ["pitfalls", "pitfall", "Where people go wrong"]];

/** What the World Compiler learned about real use of the application from the web (Tavily), and which jobs it grounds. */
function Research({ research, jobs }: { research?: any; jobs: any[] }) {
  if (!research?.requests) {
    return (
      <Card><CardContent className="pt-6 text-sm text-muted-foreground">
        {research?.skipped ? "This world was built without web research: the server has no Tavily key, so its jobs come from the source alone."
          : "This world was built before web research existed: its jobs come from the source alone. Build a new version to ground them in real use."}
      </CardContent></Card>
    );
  }
  const grounded = jobs.filter((j) => j.spec.sources?.length).length;
  const host = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Grounded in {research.sources.length} web pages</CardTitle>
          <CardDescription>Before writing jobs, the compiler searched the web with Tavily for how real people use this application, and based {grounded} of {jobs.length} jobs on what it found. Pages were read once, at build time; episodes never touch the live web.</CardDescription>
        </CardHeader>
      </Card>
      <div className="grid gap-4 lg:grid-cols-3">
        {FINDINGS.map(([key, field, title]) => (
          <Card key={key}>
            <CardHeader><CardTitle className="text-base">{title}</CardTitle></CardHeader>
            <CardContent>
              <ul className="space-y-3 text-sm">{(research[key] || []).map((f: any, i: number) => (
                <li key={i}>{f[field]} <a href={f.source} target="_blank" rel="noopener noreferrer nofollow" className="whitespace-nowrap text-xs text-primary underline-offset-2 hover:underline">{host(f.source)}</a></li>
              ))}</ul>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

export function World({ worldVersionId }: { worldVersionId: string }) {
  const wv = useResource<any>(`/v1/world-versions/${worldVersionId}`);
  const checks = useResource<any[]>("/v1/jobs?kind=world_validate", 5000);
  const rechecking = checks.data?.find((j) => j.payload?.world_version_id === worldVersionId && ["queued", "running"].includes(j.status));
  const scenarios = useResource<any[]>(`/v1/world-versions/${worldVersionId}/scenarios`, rechecking ? 5000 : 0);
  const [open, setOpen] = useState<any | null>(null);
  const w = wv.data;
  if (wv.error) return <p className="text-destructive">{wv.error}</p>;
  if (!w) return <Skeleton className="h-96" />;
  const manifest = w.manifest || {};
  const caps = w.capabilities || {};
  const validation = w.validation || {};
  const recheck = async () => {
    await post(`/v1/world-versions/${worldVersionId}/validate`);
    toast.success("Re-check started. Each job is replayed, then tried by a live agent; a job that is unfair to the agent is withdrawn.");
    checks.reload();
  };
  const exportBundle = async () => {
    const r = await post(`/v1/world-versions/${worldVersionId}/bundle`);
    toast.success(`Bundle export started (job ${r.job_id}). Downloads appear under Settings.`);
  };
  return (
    <>
      <PageHeader
        title={`${manifest.name} world, version ${w.version}`}
        description={manifest.description}
        actions={<><Button onClick={() => go(routes.runs(worldVersionId))}><PlayCircle /> Run an evaluation</Button><Button variant="outline" onClick={recheck} disabled={!!rechecking}><ShieldCheck /> {rechecking ? "Re-checking…" : "Re-check jobs"}</Button><Button variant="outline" onClick={exportBundle}><Download /> Export bundle</Button></>}
      />
      {rechecking && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-success/30 bg-success/10 px-4 py-3 text-sm">
          <ShieldCheck className="size-4 shrink-0 text-success" />
          <span>{rechecking.status === "queued" ? "Re-check queued." : "Re-check running."} Each job is replayed, then tried by a live agent. Results appear on each job as they finish; unfair jobs are withdrawn.</span>
        </div>
      )}
      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Stat value={scenarios.data?.filter((s) => s.status === "approved").length ?? "–"} label="approved scenarios" />
        <Stat value={manifest.tools?.length ?? 0} label="agent tools" />
        <Stat value={manifest.roles?.length ?? 0} label="roles" />
        <Stat value={(validation.repairs || []).filter((r: any) => r.outcome === "repaired").length} label="scenarios repaired by the compiler" />
        <Stat value={(scenarios.data?.filter((s) => s.status === "rejected").length ?? 0) + Object.keys(validation.rejected || {}).length} label="jobs withdrawn or rejected" />
      </div>
      <Tabs defaultValue="scenarios">
        <TabsList>
          <TabsTrigger value="scenarios">Scenarios</TabsTrigger>
          <TabsTrigger value="research">Real-world research</TabsTrigger>
          <TabsTrigger value="tools">Tools and roles</TabsTrigger>
          <TabsTrigger value="caps">Capabilities</TabsTrigger>
          <TabsTrigger value="prov">Provenance</TabsTrigger>
        </TabsList>
        <TabsContent value="scenarios">
          <Card>
            <CardContent className="pt-6">
              <Table>
                <TableHeader><TableRow><TableHead>Scenario</TableHead><TableHead>Family</TableHead><TableHead>Split</TableHead><TableHead>Stress test</TableHead><TableHead className="text-right">Request changes</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
                <TableBody>
                  {scenarios.data?.map((sc) => (
                    <TableRow key={sc.id} className="cursor-pointer" onClick={() => setOpen(sc)}>
                      <TableCell><div className="font-medium">{sc.spec.title}</div><div className="font-mono text-xs text-muted-foreground">{sc.slug}</div></TableCell>
                      <TableCell>{sc.family}</TableCell>
                      <TableCell><Badge variant="secondary">{sc.split}</Badge></TableCell>
                      <TableCell className="text-sm text-muted-foreground">{STRESS[sc.spec.stress] ?? "–"}</TableCell>
                      <TableCell className="text-right tabular-nums">{sc.spec.goals.length - 1}</TableCell>
                      <TableCell><StatusBadge status={sc.status} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {Object.keys(validation.rejected || {}).length > 0 && (
                <Accordion type="single" collapsible className="mt-4">
                  <AccordionItem value="rej">
                    <AccordionTrigger>Scenarios the compiler could not validate</AccordionTrigger>
                    <AccordionContent><ul className="space-y-1 text-sm">{Object.entries(validation.rejected).map(([k, v]: [string, any]) => <li key={k}><span className="font-medium">{k}</span>: {(v || []).join("; ")}</li>)}</ul></AccordionContent>
                  </AccordionItem>
                </Accordion>
              )}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="research"><Research research={validation.research} jobs={scenarios.data || []} /></TabsContent>
        <TabsContent value="tools" className="grid gap-4">
          <Card>
            <CardHeader><CardTitle>Roles</CardTitle></CardHeader>
            <CardContent><Table><TableBody>{manifest.roles?.map((r: any) => <TableRow key={r.name}><TableCell className="font-medium">{r.name}</TableCell><TableCell>{r.description}</TableCell><TableCell>{r.customer_channel && <Tone tone="info">talks to customers</Tone>}</TableCell></TableRow>)}</TableBody></Table></CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Tools agents can call</CardTitle><CardDescription>Each maps to a real operation of the application; the gateway checks the role before every call.</CardDescription></CardHeader>
            <CardContent>
              <Table>
                <TableHeader><TableRow><TableHead>Tool</TableHead><TableHead>Operation</TableHead><TableHead>Roles</TableHead><TableHead>Effect</TableHead></TableRow></TableHeader>
                <TableBody>{manifest.tools?.map((t: any) => (
                  <TableRow key={t.name}>
                    <TableCell className="max-w-md"><div className="font-medium">{t.name}</div><div className="line-clamp-2 text-xs text-muted-foreground">{t.description}</div></TableCell>
                    <TableCell><code className="text-xs">{t.graphql ? "GraphQL" : t.method} {t.path}</code></TableCell>
                    <TableCell className="text-sm">{t.roles.join(", ")}</TableCell>
                    <TableCell>{t.mutating ? (caps.idempotent_tools?.includes(t.name) ? <Tone tone="go">write, safe to retry</Tone> : <Tone tone="cue">write</Tone>) : <Tone tone="plain">read</Tone>}</TableCell>
                  </TableRow>
                ))}</TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="caps" className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Reset and isolation</CardTitle></CardHeader>
            <CardContent className="grid gap-2">
              <Check ok={!!caps.deterministic_reset} label="Resets to an identical state" />
              <Check ok={!!validation.isolation?.app_network_internal} label="Application network has no internet" />
              <Check ok={!!validation.isolation?.edge_requires_admin_token} label="Sandbox edge requires the platform token" />
              <Check ok={!!caps.clock_control} label="Application clock controlled" />
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Coverage of write operations</CardTitle></CardHeader>
            <CardContent>
              <Table><TableBody>{Object.entries(caps.tool_coverage || {}).map(([t, n]: [string, any]) => <TableRow key={t}><TableCell>{t}</TableCell><TableCell className="text-right tabular-nums">{n} scenario{n === 1 ? "" : "s"}</TableCell></TableRow>)}</TableBody></Table>
              {caps.gaps?.length > 0 && <><h3 className="mt-4 text-sm font-semibold">Known limits</h3><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">{caps.gaps.map((g: string, i: number) => <li key={i}>{g}</li>)}</ul></>}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="prov">
          <Card><CardContent className="pt-6"><pre className="overflow-x-auto rounded-md bg-muted p-4 text-xs">{JSON.stringify({ content_hash: w.content_hash, ...w.provenance }, null, 2)}</pre></CardContent></Card>
        </TabsContent>
      </Tabs>
      <ScenarioSheet sc={open} onClose={() => setOpen(null)} onChange={() => { scenarios.reload(); setOpen(null); }} />
    </>
  );
}
