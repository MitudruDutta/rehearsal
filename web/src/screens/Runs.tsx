"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader, StatusBadge } from "@/components/rh";
import { pct, post, useResource } from "../api";
import { go, routes } from "../nav";

function NewEvaluation({ world }: { world: string | null }) {
  const worlds = useResource<any[]>("/v1/worlds");
  const profiles = useResource<any[]>("/v1/agent-profiles");
  const versions = (worlds.data || []).flatMap((w) => w.versions.filter((v: any) => v.status === "published").map((v: any) => ({ ...v, name: w.name })));
  const [wv, setWv] = useState(world || "");
  const [chosen, setChosen] = useState<string[]>([]);
  const [splits, setSplits] = useState<string[]>(["dev"]);
  const [repeats, setRepeats] = useState(1);
  const toggle = (list: string[], set: (x: string[]) => void, v: string) => set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const selected = wv || versions[0]?.id || "";
  const start = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const r = await post("/v1/evaluations", { world_version_id: selected, profile_ids: chosen, splits, repeats });
      toast.success(`${r.episodes} episodes queued`);
      go(routes.run(r.run_id));
    } catch (err) {
      toast.error((err as Error).message);
    }
  };
  return (
    <Card>
      <CardHeader><CardTitle>Run an evaluation</CardTitle><CardDescription>Use train and dev while improving an agent. Run held-out once at the end; the improvement agent never sees it.</CardDescription></CardHeader>
      <CardContent>
        {worlds.data && versions.length === 0 ? (
          <p className="text-sm text-muted-foreground">Build and publish a world first; evaluations run against a published world version.</p>
        ) : (
          <form onSubmit={start} className="grid gap-5">
            <div className="grid gap-2">
              <Label>World version</Label>
              <Select value={selected} onValueChange={setWv}>
                <SelectTrigger><SelectValue placeholder="Choose a world" /></SelectTrigger>
                <SelectContent>{versions.map((v) => <SelectItem key={v.id} value={v.id}>{v.name} v{v.version}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <fieldset className="grid gap-2">
              <legend className="mb-1 text-sm font-medium">Agents</legend>
              {profiles.data?.length === 0 && <span className="text-sm text-muted-foreground">Create a profile on the Agents page.</span>}
              {profiles.data?.map((p) => (
                <label key={p.id} className="flex items-center gap-2 text-sm"><Checkbox checked={chosen.includes(p.id)} onCheckedChange={() => toggle(chosen, setChosen, p.id)} /> {p.name} v{p.version}</label>
              ))}
            </fieldset>
            <fieldset className="flex flex-wrap gap-4">
              <legend className="mb-1 w-full text-sm font-medium">Scenario splits</legend>
              {["train", "dev", "holdout"].map((s) => <label key={s} className="flex items-center gap-2 text-sm"><Checkbox checked={splits.includes(s)} onCheckedChange={() => toggle(splits, setSplits, s)} /> {s}</label>)}
            </fieldset>
            <div className="grid gap-2"><Label htmlFor="rep">Repeats per scenario</Label><Input id="rep" type="number" min={1} max={20} value={repeats} onChange={(e) => setRepeats(Number(e.target.value))} className="w-28" /></div>
            <Button type="submit" disabled={!chosen.length || !splits.length || !selected}>Start evaluation</Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

export function Runs({ world }: { world: string | null }) {
  const runs = useResource<any[]>("/v1/runs", 5000);
  return (
    <>
      <PageHeader title="Runs" description="Every episode starts from the same reset state, and only the application's own records decide whether the agent succeeded." />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
        <Card>
          <CardHeader><CardTitle>Recent runs</CardTitle></CardHeader>
          <CardContent>
            {runs.data?.length === 0 && <p className="text-sm text-muted-foreground">No runs yet.</p>}
            <Table>
              <TableHeader><TableRow><TableHead>Run</TableHead><TableHead>Agents</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Verified</TableHead></TableRow></TableHeader>
              <TableBody>
                {runs.data?.map((r) => (
                  <TableRow key={r.id} className="cursor-pointer" onClick={() => go(routes.run(r.id))}>
                    <TableCell><div className="font-mono text-xs">{r.id}</div><div className="text-xs text-muted-foreground">{(r.config.splits || []).join(", ")} ×{r.config.repeats}</div></TableCell>
                    <TableCell className="text-sm">{(r.config.profiles || []).join(", ")}</TableCell>
                    <TableCell><StatusBadge status={r.status} /></TableCell>
                    <TableCell className="text-right font-semibold tabular-nums">{pct(r.summary?.overall?.success_rate)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <NewEvaluation world={world} />
      </div>
    </>
  );
}
