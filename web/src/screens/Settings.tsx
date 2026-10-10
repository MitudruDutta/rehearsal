"use client";

import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader, Tone } from "@/components/rh";
import { useResource } from "../api";

function money(v: number) {
  return v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(3)}`;
}

export function Settings() {
  const artifacts = useResource<any[]>("/v1/artifacts", 8000);
  const creds = useResource<any[]>("/v1/credentials");
  const prices = useResource<any[]>("/v1/pricing");
  return (
    <>
      <PageHeader title="Settings" description={<>Models and their prices, credentials, and exported files for this project. API keys have <a className="underline underline-offset-2" href="/app/api-keys/">their own page</a>.</>} />
      <Tabs defaultValue="models">
        <TabsList>
          <TabsTrigger value="models">Models and pricing</TabsTrigger>
          <TabsTrigger value="creds">Credentials</TabsTrigger>
          <TabsTrigger value="exports">Exports</TabsTrigger>
        </TabsList>
        <TabsContent value="models">
          <Card>
            <CardHeader>
              <CardTitle>Models and where their prices come from</CardTitle>
              <CardDescription>Each call is charged at the provider-reported cost, the serving provider&apos;s published price list, or a dated entry in pricing.yaml, and the source is recorded with the cost. The market column shows what every host on OpenRouter charges for the same model; it is for planning only.</CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader><TableRow><TableHead>Used for</TableHead><TableHead>Model</TableHead><TableHead>Charged at (per 1M tokens in / out)</TableHead><TableHead>Market range across hosts</TableHead></TableRow></TableHeader>
                <TableBody>
                  {prices.data?.map((r, i) => (
                    <TableRow key={i}>
                      <TableCell className="capitalize">{r.purpose}{i > 0 && prices.data![i - 1].purpose === r.purpose && <div className="text-xs text-muted-foreground">fallback</div>}</TableCell>
                      <TableCell><div className="font-medium">{r.model}</div><div className="text-xs text-muted-foreground">via {r.provider}</div></TableCell>
                      <TableCell>{r.billing ? <><div className="tabular-nums">{money(r.billing.input_per_m)} / {money(r.billing.output_per_m)}</div><div className="text-xs text-muted-foreground">{r.billing.source}, {r.billing.as_of}</div></> : <Tone tone="cue">unknown: add to pricing.yaml</Tone>}</TableCell>
                      <TableCell>{r.market ? <><div className="tabular-nums">in {money(r.market.input_per_m.min)}–{money(r.market.input_per_m.max)}, out {money(r.market.output_per_m.min)}–{money(r.market.output_per_m.max)}</div><div className="text-xs text-muted-foreground">{r.market.hosts} hosts, {r.market.as_of}</div></> : <span className="text-muted-foreground">no listing</span>}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="creds">
          <Card>
            <CardHeader><CardTitle>Credentials</CardTitle><CardDescription>Registered by reference: the runner reads them from its own environment, and the console never shows their values.</CardDescription></CardHeader>
            <CardContent>
              {creds.data?.length === 0 && <p className="text-sm text-muted-foreground">No credentials registered.</p>}
              <Table><TableBody>{creds.data?.map((c) => <TableRow key={c.id}><TableCell>{c.name}</TableCell><TableCell><code>{c.env_var}</code></TableCell><TableCell>{c.available_on_runner ? <Tone tone="go">set on runner</Tone> : <Tone tone="stop">missing</Tone>}</TableCell></TableRow>)}</TableBody></Table>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="exports">
          <Card>
            <CardHeader><CardTitle>Exports</CardTitle><CardDescription>World bundles and datasets.</CardDescription></CardHeader>
            <CardContent>
              {artifacts.data?.filter((a) => a.kind !== "source_upload").length === 0 && <p className="text-sm text-muted-foreground">World bundles and datasets you export appear here.</p>}
              <Table><TableBody>{artifacts.data?.filter((a) => a.kind !== "source_upload").map((a) => (
                <TableRow key={a.id}><TableCell><div className="font-medium">{a.name}</div><div className="text-xs text-muted-foreground">{a.kind.replace(/_/g, " ")}, {(a.size / 1e6).toFixed(1)} MB</div></TableCell><TableCell className="text-right"><Button asChild variant="outline" size="sm"><a href={`/v1/artifacts/${a.id}/download`}><Download /> Download</a></Button></TableCell></TableRow>
              ))}</TableBody></Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </>
  );
}
