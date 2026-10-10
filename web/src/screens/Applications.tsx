"use client";

import { GitBranch, Hammer, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader, StatusBadge, Tone } from "@/components/rh";
import { del, post, useResource } from "../api";
import { go, routes } from "../nav";

function AddApplication({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", url: "", commit: "", images: "", policies: "" });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const images = Object.fromEntries(form.images.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => l.split("=", 2).map((x) => x.trim())));
    try {
      await post("/v1/applications", { name: form.name, source: { kind: "git", url: form.url, commit: form.commit || undefined }, images, policies: form.policies });
      toast.success(`${form.name} added`);
      setOpen(false);
      onAdded();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button><Plus /> Add application</Button></DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Add an application</DialogTitle>
            <DialogDescription>Rehearsal reads the source at a pinned commit and runs the images you list, in an isolated network with fictional data. It never touches production.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-2"><Label htmlFor="n">Name</Label><Input id="n" value={form.name} onChange={set("name")} required /></div>
          <div className="grid gap-2"><Label htmlFor="u">Git repository (https)</Label><Input id="u" value={form.url} onChange={set("url")} placeholder="https://github.com/org/app" required /></div>
          <div className="grid gap-2"><Label htmlFor="c">Commit</Label><Input id="c" value={form.commit} onChange={set("commit")} placeholder="full SHA (recommended)" /></div>
          <div className="grid gap-2"><Label htmlFor="i">Images, one per line</Label><Textarea id="i" value={form.images} onChange={set("images")} placeholder={"app=registry/app:1.2@sha256:…\npostgres=postgres:16@sha256:…"} rows={3} /></div>
          <div className="grid gap-2"><Label htmlFor="p">Rules agents must follow (optional)</Label><Textarea id="p" value={form.policies} onChange={set("policies")} rows={3} /></div>
          <DialogFooter><Button type="submit">Add application</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function Applications() {
  const apps = useResource<any[]>("/v1/applications");
  const worlds = useResource<any[]>("/v1/worlds", 5000);
  const [busy, setBusy] = useState<string | null>(null);
  const [removing, setRemoving] = useState<any | null>(null);
  const remove = async () => {
    try {
      const res = await del(`/v1/applications/${removing.id}`);
      toast(res.builds_stopped ? `${removing.name} removed; ${res.builds_stopped} build stopped` : `${removing.name} removed`);
      setRemoving(null);
      apps.reload();
      worlds.reload();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };
  const build = async (appId: string) => {
    setBusy(appId);
    try {
      const res = await post("/v1/world-builds", { application_id: appId, scenario_target: 8 });
      go(routes.build(res.job_id));
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const restart = async (jobId: string) => {
    try {
      await post(`/v1/jobs/${jobId}/commands`, { command: "retry" });
      go(routes.build(jobId));
    } catch (err) {
      toast.error((err as Error).message);
    }
  };
  return (
    <>
      <PageHeader
        title="Applications"
        description="Each build turns an application into a versioned practice world: the real app, fictional data, scoped tools, and validated scenarios."
        actions={<AddApplication onAdded={apps.reload} />}
      />
      {apps.data?.length === 0 && (
        <Card><CardContent className="flex flex-wrap items-center justify-between gap-4 pt-6">
          <p className="text-muted-foreground">No applications yet. Add yours, or load the pinned open-source applications Rehearsal is tested on.</p>
          <Button variant="outline" onClick={async () => { await post("/v1/applications/import-catalog"); apps.reload(); }}>Load sample applications</Button>
        </CardContent></Card>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        {apps.data?.map((a) => {
          const w = worlds.data?.find((x) => x.application_id === a.id);
          const notes = Object.fromEntries((a.notes || "").split(";").map((p: string) => p.trim().split("=")).filter((p: string[]) => p.length === 2));
          return (
            <Card key={a.id}>
              <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
                <div className="min-w-0">
                  <CardTitle className="flex items-center gap-2 text-lg">{a.name}{notes.split === "holdout" && <Tone tone="info">held out</Tone>}</CardTitle>
                  <CardDescription className="mt-1 flex items-center gap-1.5 truncate"><GitBranch className="size-3.5 shrink-0" />{a.source?.url ? `${a.source.url.replace("https://github.com/", "")} @ ${String(a.source.commit || a.source.ref || "").slice(0, 10)}` : a.source?.kind}</CardDescription>
                  {notes.domain && <CardDescription>{notes.domain}{notes.license ? ` · ${notes.license}` : ""}</CardDescription>}
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button size="sm" onClick={() => build(a.id)} disabled={busy === a.id}><Hammer /> {w ? "Build new version" : "Build world"}</Button>
                  <Button size="icon-sm" variant="ghost" className="text-muted-foreground hover:text-destructive" aria-label={`Remove ${a.name}`} title="Remove application" onClick={() => setRemoving(a)}><Trash2 /></Button>
                </div>
              </CardHeader>
              <CardContent>
                {!w || w.versions.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Not built yet.</p>
                ) : (
                  <Table>
                    <TableHeader><TableRow><TableHead>Version</TableHead><TableHead>Status</TableHead><TableHead>Content hash</TableHead><TableHead /></TableRow></TableHeader>
                    <TableBody>
                      {[...w.versions].reverse().map((v: any) => (
                        <TableRow key={v.id} className="cursor-pointer" onClick={() => go(v.status === "published" ? routes.world(v.id) : routes.build(v.build_job_id))}>
                          <TableCell className="font-medium">v{v.version}</TableCell>
                          <TableCell><StatusBadge status={v.status} /></TableCell>
                          <TableCell className="font-mono text-xs text-muted-foreground">{v.content_hash ? v.content_hash.slice(0, 12) : "–"}</TableCell>
                          <TableCell className="text-right text-sm text-muted-foreground">
                            {["failed", "cancelled"].includes(v.status)
                              ? <Button size="sm" variant="outline" onClick={(e) => { e.stopPropagation(); restart(v.build_job_id); }}><RotateCcw /> Restart</Button>
                              : v.status === "published" ? "Open world" : "Watch build"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
      <Dialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove {removing?.name}?</DialogTitle>
            <DialogDescription>The application and its practice worlds leave the console, and any build in progress stops. Finished runs stay in the run history. You cannot bring it back from the console; add the application again to rebuild it.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemoving(null)}>Keep</Button>
            <Button variant="destructive" onClick={remove}><Trash2 /> Remove application</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
