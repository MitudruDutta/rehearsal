"use client";

import { Gift, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { PageHeader, Tone } from "@/components/rh";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, post, useResource } from "../api";

const PLANS = ["free", "pro", "team", "enterprise", "internal"];
const LIMITS: Record<string, string> = {
  applications: "Applications", builds: "World builds a month", episodes: "Episodes a month", sandboxes: "Sandboxes at once",
  active_builds: "Builds at once", build_budget_usd: "Spend cap per build ($)", allowance_usd: "Model spend a month ($)",
};
const AUTO = "auto";

function used(n: number, limit: number | null) {
  return limit === null ? `${n}` : `${n} / ${limit}`;
}

function Limits({ org, onClose, onSaved }: { org: any; onClose: () => void; onSaved: () => void }) {
  const [plan, setPlan] = useState<string>(org.plan_override ?? AUTO);
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(org.limits_override || {}).map(([k, v]) => [k, v === null ? "none" : String(v)])),
  );
  const save = async () => {
    const limits: Record<string, number | null> = {};
    for (const [k, v] of Object.entries(values)) {
      const t = v.trim().toLowerCase();
      if (!t) continue;
      if (t === "none") limits[k] = null;
      else if (!Number.isNaN(Number(t)) && Number(t) >= 0) limits[k] = Number(t);
      else return toast.error(`${LIMITS[k]}: enter a number, or "none" for no limit`);
    }
    try {
      await api(`/v1/admin/organizations/${org.id}`, { method: "PUT", body: JSON.stringify({ plan_override: plan === AUTO ? null : plan, limits_override: limits }), headers: { "Content-Type": "application/json" } });
      toast.success(`${org.name} updated`);
      onSaved();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Plan for {org.name}</DialogTitle>
          <DialogDescription>Automatic follows the workspace's subscription. Any other plan applies without payment until you set it back. Leave a limit empty to use the plan's own; type none for no limit.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-1.5">
            <Label>Plan</Label>
            <Select value={plan} onValueChange={setPlan}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value={AUTO}>Automatic (subscription or free)</SelectItem>
                {PLANS.map((p) => <SelectItem key={p} value={p} className="capitalize">{p}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {Object.entries(LIMITS).map(([k, label]) => (
              <div key={k} className="grid gap-1.5">
                <Label htmlFor={`lim-${k}`}>{label}</Label>
                <Input id={`lim-${k}`} placeholder={org.limits[k] === null ? "no limit" : String(org.limits[k])} value={values[k] ?? ""} onChange={(e) => setValues({ ...values, [k]: e.target.value })} />
              </div>
            ))}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Grant({ org, onClose, onSaved }: { org: any; onClose: () => void; onSaved: () => void }) {
  const [kind, setKind] = useState("episodes");
  const [quantity, setQuantity] = useState("100");
  const [note, setNote] = useState("");
  const save = async () => {
    try {
      await post(`/v1/admin/organizations/${org.id}/credits`, { kind, quantity: Number(quantity), note });
      toast.success(`Added ${quantity} ${kind} to ${org.name} for this month`);
      onSaved();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add to {org.name} for this month</DialogTitle>
          <DialogDescription>Like a top-up, without payment. It ends with the month.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="grid gap-1.5">
            <Label>What</Label>
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="episodes">Episodes</SelectItem><SelectItem value="builds">World builds</SelectItem></SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5"><Label htmlFor="grant-q">How many</Label><Input id="grant-q" type="number" min={1} value={quantity} onChange={(e) => setQuantity(e.target.value)} /></div>
          <div className="grid gap-1.5 sm:col-span-2"><Label htmlFor="grant-n">Note</Label><Input id="grant-n" placeholder="For example: design-partner pilot" value={note} onChange={(e) => setNote(e.target.value)} /></div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={!(Number(quantity) >= 1)}>Add</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function Admin() {
  const orgs = useResource<any[]>("/v1/admin/organizations", 30000);
  const [editing, setEditing] = useState<any | null>(null);
  const [granting, setGranting] = useState<any | null>(null);
  const done = () => { setEditing(null); setGranting(null); orgs.reload(); };
  return (
    <>
      <PageHeader title="Workspaces" description="Every workspace on this server, its plan, and what it used this month. Only operator admins see this page." />
      <Card>
        <CardContent className="pt-6">
          {orgs.error && <p className="text-sm text-destructive">{orgs.error}</p>}
          <Table>
            <TableHeader>
              <TableRow><TableHead>Workspace</TableHead><TableHead>Plan</TableHead><TableHead>Apps</TableHead><TableHead>Builds</TableHead><TableHead>Episodes</TableHead><TableHead>Model spend</TableHead><TableHead /></TableRow>
            </TableHeader>
            <TableBody>
              {(orgs.data || []).map((o) => (
                <TableRow key={o.id}>
                  <TableCell><div className="font-medium">{o.name}</div><div className="text-xs text-muted-foreground">{o.owner || "no owner"}</div></TableCell>
                  <TableCell>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Tone tone={o.plan === "free" ? "plain" : "go"}>{o.plan_title}</Tone>
                      {o.plan_override && <Tone tone="info">set by admin</Tone>}
                      {o.subscription && <Tone tone={["active", "past_due"].includes(o.subscription.status) ? "go" : "stop"}>{o.subscription.plan} {o.subscription.status}</Tone>}
                    </div>
                  </TableCell>
                  <TableCell className="tabular-nums">{used(o.usage.applications, o.limits.applications)}</TableCell>
                  <TableCell className="tabular-nums">{used(o.usage.builds, o.limits.builds === null ? null : o.limits.builds + o.usage.extra_builds)}</TableCell>
                  <TableCell className="tabular-nums">{used(o.usage.episodes, o.limits.episodes === null ? null : o.limits.episodes + o.usage.extra_episodes)}</TableCell>
                  <TableCell className="tabular-nums">${o.spent_usd.toFixed(2)}</TableCell>
                  <TableCell className="whitespace-nowrap text-right">
                    <Button variant="ghost" size="sm" onClick={() => setEditing(o)}><SlidersHorizontal /> Plan</Button>
                    <Button variant="ghost" size="sm" onClick={() => setGranting(o)}><Gift /> Add</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      {editing && <Limits org={editing} onClose={() => setEditing(null)} onSaved={done} />}
      {granting && <Grant org={granting} onClose={() => setGranting(null)} onSaved={done} />}
    </>
  );
}
