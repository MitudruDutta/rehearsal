"use client";

import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/rh";
import { pct, useResource } from "../api";
import { go, routes } from "../nav";

const METRICS: [string, string, boolean][] = [
  ["success_rate", "Verified success", true],
  ["hard_violation_episodes", "Episodes with a rule violation", false],
  ["false_completions", "Claimed done but was not", false],
  ["duplicate_effects", "Duplicate side effects", false],
  ["unnecessary_interruptions", "Unneeded customer interruptions", false],
  ["rejected_attempts", "Blocked tool calls", false],
  ["cost_usd", "Model cost (USD)", false],
];

function fmt(key: string, v: any) {
  if (v === null || v === undefined) return "–";
  if (key === "success_rate") return pct(v);
  if (key === "cost_usd") return `$${Number(v).toFixed(4)}`;
  return String(v);
}

function Delta({ k, a, b, better }: { k: string; a: any; b: any; better: boolean }) {
  if (typeof a !== "number" || typeof b !== "number" || a === b) return <span className="text-muted-foreground">no change</span>;
  const up = b > a;
  const text = k === "success_rate" ? `${up ? "+" : ""}${Math.round((b - a) * 100)} pts` : `${up ? "+" : ""}${k === "cost_usd" ? (b - a).toFixed(4) : b - a}`;
  return <span className={`font-semibold ${up === better ? "text-success" : "text-destructive"}`}>{text}</span>;
}

export function Compare({ runA, runB }: { runA?: string; runB?: string }) {
  const runs = useResource<any[]>("/v1/runs");
  const [split, setSplit] = useState("overall");
  const cmp = useResource<any>(runA ? `/v1/compare?run_a=${runA}${runB ? `&run_b=${runB}` : ""}` : null);
  const columns: [string, any][] = [];
  if (cmp.data) for (const [rid, summary] of Object.entries(cmp.data.runs) as [string, any][]) for (const [prof, s] of Object.entries(summary?.profiles || {}) as [string, any][]) columns.push([`${prof} (run ${rid.slice(-6)})`, s]);
  const splits = ["overall", "train", "dev", "holdout"].filter((sp) => columns.some(([, s]) => s[sp]));
  const [left, right] = columns;
  const scenarios = [...new Set(columns.flatMap(([, s]) => Object.keys(s.per_scenario || {})))];
  const finished = runs.data?.filter((r) => r.status === "finished") ?? [];
  return (
    <>
      <PageHeader title="Compare" description="Compare agent versions on the same pinned world version. Runs on different world versions are refused because their checks differ." />
      <Card className="mb-6">
        <CardContent className="grid gap-4 pt-6 md:grid-cols-2">
          <div className="grid gap-2"><Label>Run</Label>
            <Select value={runA ?? ""} onValueChange={(v) => go(routes.compare(v, runB))}><SelectTrigger><SelectValue placeholder="Choose a run" /></SelectTrigger><SelectContent>{finished.map((r) => <SelectItem key={r.id} value={r.id}>{r.id} ({(r.config.profiles || []).join(", ")})</SelectItem>)}</SelectContent></Select>
          </div>
          <div className="grid gap-2"><Label>Second run (optional)</Label>
            <Select value={runB ?? "none"} onValueChange={(v) => go(routes.compare(runA, v === "none" ? undefined : v))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">Compare agents within the first run</SelectItem>{finished.filter((r) => r.id !== runA).map((r) => <SelectItem key={r.id} value={r.id}>{r.id} ({(r.config.profiles || []).join(", ")})</SelectItem>)}</SelectContent></Select>
          </div>
        </CardContent>
      </Card>
      {cmp.error && <p className="text-destructive">{cmp.error}</p>}
      {columns.length > 0 && (
        <div className="grid gap-6">
          <Tabs value={split} onValueChange={setSplit}><TabsList>{splits.map((sp) => <TabsTrigger key={sp} value={sp}>{sp === "overall" ? "All scenarios" : sp}</TabsTrigger>)}</TabsList></Tabs>
          <Card>
            <CardHeader><CardTitle>Measures</CardTitle><CardDescription>World content hash {cmp.data.world_content_hash?.slice(0, 12)}</CardDescription></CardHeader>
            <CardContent>
              <Table>
                <TableHeader><TableRow><TableHead>Measure</TableHead>{columns.map(([n]) => <TableHead key={n} className="text-right">{n}</TableHead>)}{columns.length === 2 && <TableHead className="text-right">Change</TableHead>}</TableRow></TableHeader>
                <TableBody>
                  <TableRow><TableCell>Episodes scored</TableCell>{columns.map(([n, s]) => <TableCell key={n} className="text-right tabular-nums">{s[split]?.finished ?? "–"} of {s[split]?.episodes ?? "–"}</TableCell>)}{columns.length === 2 && <TableCell />}</TableRow>
                  {METRICS.map(([k, label, better]) => (
                    <TableRow key={k}><TableCell>{label}</TableCell>{columns.map(([n, s]) => <TableCell key={n} className="text-right tabular-nums">{fmt(k, s[split]?.[k])}</TableCell>)}{columns.length === 2 && <TableCell className="text-right"><Delta k={k} a={left[1][split]?.[k]} b={right[1][split]?.[k]} better={better} /></TableCell>}</TableRow>
                  ))}
                  <TableRow><TableCell>Recovered after a fault</TableCell>{columns.map(([n, s]) => <TableCell key={n} className="text-right tabular-nums">{s[split]?.recovered ?? "–"}</TableCell>)}{columns.length === 2 && <TableCell />}</TableRow>
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Per scenario</CardTitle></CardHeader>
            <CardContent>
              <Table>
                <TableHeader><TableRow><TableHead>Scenario</TableHead>{columns.map(([n]) => <TableHead key={n} className="text-right">{n}</TableHead>)}</TableRow></TableHeader>
                <TableBody>{scenarios.map((sc) => <TableRow key={sc}><TableCell>{sc}</TableCell>{columns.map(([n, s]) => { const x = s.per_scenario?.[sc]; return <TableCell key={n} className="text-right tabular-nums">{x ? `${x.successes}/${x.finished}` : "–"}</TableCell>; })}</TableRow>)}</TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      )}
    </>
  );
}
