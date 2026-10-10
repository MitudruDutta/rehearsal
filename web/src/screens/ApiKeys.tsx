"use client";

import { KeyRound, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Connect, KeyReveal } from "@/components/key-reveal";
import { PageHeader, Tone } from "@/components/rh";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, post, useResource } from "../api";

const ACCESS: Record<string, { label: string; detail: string }> = {
  write: { label: "Build and evaluate", detail: "Add applications, build worlds, run evaluations, improve agents" },
  admin: { label: "Full access", detail: "Everything, including creating and revoking keys" },
  read: { label: "Read only", detail: "See worlds, runs and results" },
  agent: { label: "Agent only", detail: "Act inside episodes, for an agent you run yourself" },
  evaluator: { label: "Evaluator", detail: "See held-out jobs and verdicts" },
};

const KINDS: Record<string, string> = { world_build: "World builds", evaluation: "Evaluations", improvement: "Improvements", world_validate: "Re-checks" };

function day(iso?: string | null) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";
}

function Usage() {
  const u = useResource<any>("/v1/usage", 15000).data;
  if (!u) return null;
  const used = u.allowance_usd ? Math.min(100, (u.spent_usd / u.allowance_usd) * 100) : 0;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Model spend this month</CardTitle>
        <CardDescription>
          Builds, evaluations and the simulated customer run on Rehearsal&apos;s model account, so a key is all you need.
          {u.allowance_usd ? ` Your workspace can use $${u.allowance_usd.toFixed(2)} a month; it renews on ${day(u.renews)}.` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="font-heading text-3xl font-bold tabular-nums">${u.spent_usd.toFixed(2)}</span>
          {u.allowance_usd ? <span className="text-sm text-muted-foreground">of ${u.allowance_usd.toFixed(2)}, ${u.left_usd.toFixed(2)} left to start new work</span> : <span className="text-sm text-muted-foreground">no monthly limit on this server</span>}
        </div>
        {u.allowance_usd ? <Progress value={used} className="h-1.5" aria-label="Share of the monthly allowance used" /> : null}
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted-foreground">
          {Object.entries(u.by_kind).map(([k, v]) => <span key={k}>{KINDS[k] ?? k}: ${(v as number).toFixed(2)}</span>)}
        </div>
        <p className="text-xs text-muted-foreground">An agent you run yourself (bring your own agent) calls its own model with your provider key; that part is billed to you by that provider.</p>
      </CardContent>
    </Card>
  );
}

export function ApiKeys() {
  const keys = useResource<any[]>("/v1/api-keys");
  const [created, setCreated] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [scope, setScope] = useState("write");
  const [revoking, setRevoking] = useState<any | null>(null);
  const active = (keys.data || []).filter((k) => !k.revoked_at);
  const revoked = (keys.data || []).filter((k) => k.revoked_at);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      // "Build and evaluate" must also read results and held-out verdicts, or an assistant using the key cannot explain a run
      const r = await post("/v1/api-keys", { name: name.trim(), scopes: scope === "write" ? ["write", "evaluator"] : [scope] });
      setCreated(r.api_key);
      setName("");
      keys.reload();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };
  const revoke = async () => {
    try {
      await api(`/v1/api-keys/${revoking.id}`, { method: "DELETE" });
      toast.success(`${revoking.name} revoked. Anything still using it stops working now.`);
      setRevoking(null);
      keys.reload();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };

  return (
    <>
      <PageHeader
        title="API keys"
        description="Use Rehearsal from an AI assistant over MCP, from the terminal, from Python, or over HTTP. Give each person, pipeline or agent its own key, so you can revoke one without stopping the others."
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Create a key</CardTitle>
              <CardDescription>The key is shown once. Keep it out of source control.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <form onSubmit={create} className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
                <div className="grid gap-1.5">
                  <Label htmlFor="key-name">Name</Label>
                  <Input id="key-name" placeholder="For example: laptop, ci-pipeline, claude-code" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="key-access">Access</Label>
                  <Select value={scope} onValueChange={setScope}>
                    <SelectTrigger id="key-access"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {Object.entries(ACCESS).map(([k, a]) => (
                        <SelectItem key={k} value={k}><span className="font-medium">{a.label}</span><span className="ml-2 text-muted-foreground">{a.detail}</span></SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <Button type="submit" disabled={!name.trim()}><KeyRound /> Create key</Button>
              </form>
              {created && <KeyReveal apiKey={created} />}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Connect</CardTitle>
              <CardDescription>{created ? "Your new key is filled in below." : "Replace rh_your_key with a key you created."}</CardDescription>
            </CardHeader>
            <CardContent><Connect apiKey={created} /></CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Keys</CardTitle>
              <CardDescription>{active.length === 0 ? "No active keys yet." : `${active.length} active`}</CardDescription>
            </CardHeader>
            <CardContent>
              {active.length > 0 && (
                <Table>
                  <TableHeader>
                    <TableRow><TableHead>Name</TableHead><TableHead>Access</TableHead><TableHead>Created</TableHead><TableHead>Last used</TableHead><TableHead /></TableRow>
                  </TableHeader>
                  <TableBody>
                    {active.map((k) => (
                      <TableRow key={k.id}>
                        <TableCell><div className="font-medium">{k.name}</div><div className="font-mono text-xs text-muted-foreground">rh_{k.prefix}_…</div></TableCell>
                        <TableCell className="text-sm">{(k.scopes || []).includes("write") ? ACCESS.write.label : (k.scopes || []).map((s: string) => ACCESS[s]?.label ?? s).join(", ")}</TableCell>
                        <TableCell className="text-sm text-muted-foreground">{day(k.created_at)}</TableCell>
                        <TableCell className="text-sm text-muted-foreground">{k.last_used_at ? day(k.last_used_at) : "Never"}</TableCell>
                        <TableCell className="text-right">
                          <Button variant="ghost" size="sm" className="text-muted-foreground hover:text-destructive" onClick={() => setRevoking(k)}><Trash2 /> Revoke</Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
              {revoked.length > 0 && (
                <details className="mt-4 text-sm">
                  <summary className="cursor-pointer text-muted-foreground">{revoked.length} revoked</summary>
                  <ul className="mt-2 space-y-1">
                    {revoked.map((k) => <li key={k.id} className="flex items-center gap-2 text-muted-foreground"><Tone tone="plain">revoked {day(k.revoked_at)}</Tone>{k.name}</li>)}
                  </ul>
                </details>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Usage />
          <Card>
            <CardHeader><CardTitle>What a key can do</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              <p>Everything in this console: add applications, build practice worlds, run evaluations, read why an episode failed, and improve an agent.</p>
              <p>With the MCP server, an assistant such as Claude Code does these steps for you, and asks before it starts anything that spends your allowance.</p>
              <p>To test an agent you run yourself, create it as a bring-your-own agent; it receives each turn over the API and answers with an action.</p>
            </CardContent>
          </Card>
        </div>
      </div>

      <Dialog open={!!revoking} onOpenChange={(o) => !o && setRevoking(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revoke {revoking?.name}?</DialogTitle>
            <DialogDescription>Anything that uses this key stops working at once: scripts, pipelines, and assistants. You cannot undo this; create a new key instead.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRevoking(null)}>Keep key</Button>
            <Button variant="destructive" onClick={revoke}><Trash2 /> Revoke key</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
