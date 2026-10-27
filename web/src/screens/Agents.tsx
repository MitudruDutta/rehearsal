"use client";

import { Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { ActorAvatar, PageHeader, Tone } from "@/components/rh";
import { post, useResource } from "../api";

const DEFAULT_PROMPT =
  "You are {actor_id}, working as {role} inside a company application. Use only the tools provided. " +
  "Read tool results carefully; never invent IDs or outcomes. Your assignment: {instructions}";

export function Agents() {
  const profiles = useResource<any[]>("/v1/agent-profiles");
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [model, setModel] = useState("");
  const [external, setExternal] = useState(false);
  const [byUrl, setByUrl] = useState(false);
  const [endpoint, setEndpoint] = useState({ url: "", model: "", api_key: "" });
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await post("/v1/agent-profiles", {
        name, system_prompt: prompt, model: model || null, driver: external ? "external" : "llm",
        ...(byUrl ? { endpoint: { url: endpoint.url, model: endpoint.model, api_key: endpoint.api_key || null } } : {}),
      });
      setEndpoint({ url: "", model: "", api_key: "" });
      toast.success(`${name} created`);
      setName("");
      profiles.reload();
    } catch (err) {
      toast.error((err as Error).message);
    }
  };
  return (
    <>
      <PageHeader title="Agents" description="An agent profile is the model and instructions under test. Improved versions keep the name with a new version number, so results stay comparable." />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
        <Card>
          <CardHeader><CardTitle>Profiles</CardTitle></CardHeader>
          <CardContent>
            {profiles.data?.length === 0 && <p className="text-sm text-muted-foreground">No profiles yet. Create one to run an evaluation.</p>}
            <Table>
              <TableHeader><TableRow><TableHead>Agent</TableHead><TableHead>Author</TableHead><TableHead>Why this version</TableHead></TableRow></TableHeader>
              <TableBody>
                {profiles.data?.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell><div className="flex items-center gap-2"><ActorAvatar id={p.name} className="size-7" /><div><div className="font-medium">{p.name} <span className="text-muted-foreground">v{p.version}</span></div><div className="font-mono text-xs text-muted-foreground">{p.id}</div></div></div></TableCell>
                    <TableCell>{p.created_by === "improver" ? <Tone tone="info"><Sparkles className="size-3" /> improvement agent</Tone> : <Tone tone="plain">you</Tone>}{p.spec?.driver === "external" && <div className="mt-1 text-xs text-muted-foreground">your own agent over the API</div>}{p.spec?.endpoint && <div className="mt-1 truncate text-xs text-muted-foreground">your own agent at {p.spec.endpoint.url}</div>}</TableCell>
                    <TableCell className="max-w-md text-sm text-muted-foreground">{p.rationale || "–"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Create a profile</CardTitle><CardDescription>Keep {"{actor_id}"}, {"{role}"} and {"{instructions}"}; each scenario fills them in.</CardDescription></CardHeader>
          <CardContent>
            <form onSubmit={create} className="grid gap-4">
              <div className="grid gap-2"><Label htmlFor="pn">Name</Label><Input id="pn" value={name} onChange={(e) => setName(e.target.value)} required placeholder="support-agent" /></div>
              {!byUrl && <div className="grid gap-2"><Label htmlFor="pm">Model chain (optional)</Label><Input id="pm" value={model} onChange={(e) => setModel(e.target.value)} placeholder="nebius:nvidia/nemotron-3-super-120b-a12b" /></div>}
              <div className="grid gap-2"><Label htmlFor="pp">Instructions</Label><Textarea id="pp" rows={7} value={prompt} onChange={(e) => setPrompt(e.target.value)} /></div>
              <label className="flex items-center gap-2 text-sm"><Checkbox checked={external} onCheckedChange={(v) => { setExternal(v === true); if (v === true) setByUrl(false); }} /> My own agent sends actions through the API</label>
              <label className="flex items-center gap-2 text-sm"><Checkbox checked={byUrl} onCheckedChange={(v) => { setByUrl(v === true); if (v === true) setExternal(false); }} /> My own agent runs at a URL</label>
              {byUrl && (
                <div className="grid gap-3 rounded-lg border p-3">
                  <p className="text-sm text-muted-foreground">Each turn, Rehearsal sends your agent the conversation and the offered tools as an OpenAI-compatible chat request, and expects one tool call back. The URL must be https and reachable from the internet. Its calls cost you nothing here.</p>
                  <div className="grid gap-2"><Label htmlFor="eu">Endpoint URL</Label><Input id="eu" type="url" required value={endpoint.url} onChange={(e) => setEndpoint({ ...endpoint, url: e.target.value })} placeholder="https://agent.example.com/v1" /></div>
                  <div className="grid gap-2"><Label htmlFor="em">Model name it expects (optional)</Label><Input id="em" value={endpoint.model} onChange={(e) => setEndpoint({ ...endpoint, model: e.target.value })} placeholder="support-agent" /></div>
                  <div className="grid gap-2"><Label htmlFor="ek">API key (optional, stored encrypted)</Label><Input id="ek" type="password" autoComplete="off" value={endpoint.api_key} onChange={(e) => setEndpoint({ ...endpoint, api_key: e.target.value })} /></div>
                </div>
              )}
              <Button type="submit" disabled={!name}>Create profile</Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
