"use client";

import { Download, LogOut } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState, type ReactNode } from "react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableRow } from "@/components/ui/table";
import { PageHeader, Tone } from "@/components/rh";
import { InstallChip } from "../landing/InstallChip";
import { api, useResource } from "../api";
import { routes } from "../nav";

export async function signOut() {
  await api("/v1/session", { method: "DELETE" });
  location.reload();
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 border-b py-3 last:border-0 sm:grid-cols-[180px_1fr] sm:gap-4">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="min-w-0 text-sm">{children}</span>
    </div>
  );
}

export function Profile() {
  const me = useResource<any>("/v1/me").data;
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false); // the stored theme is known only in the browser
  useEffect(() => setMounted(true), []);
  const user = me?.user;
  return (
    <>
      <PageHeader title="Profile" description="Who you are signed in as, and your personal preferences." />
      <Card>
        <CardContent className="pt-6">
          <div className="mb-4 flex items-center gap-4">
            <Avatar className="size-14">
              {user?.picture_url && <AvatarImage src={user.picture_url} alt="" referrerPolicy="no-referrer" />}
              <AvatarFallback>{(user?.name || user?.email || "?").slice(0, 1).toUpperCase()}</AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <div className="truncate text-lg font-semibold">{user?.name || "Signed in with an API key"}</div>
              {user?.email && <div className="truncate text-sm text-muted-foreground">{user.email}</div>}
            </div>
          </div>
          <Row label="Workspace">{me?.organization ?? "…"}</Row>
          <Row label="Project">{me?.project ?? "…"}</Row>
          {me?.plan && <Row label="Plan">{me.plan} (<a className="underline underline-offset-2" href={routes.billing}>billing</a>)</Row>}
          {me?.is_admin && <Row label="Access">Operator admin</Row>}
          <Row label="Theme">
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Theme">
              {([["system", "Match system"], ["light", "Light"], ["dark", "Dark"]] as const).map(([t, label]) => (
                <Button key={t} size="sm" variant={mounted && theme === t ? "default" : "outline"} role="radio" aria-checked={mounted && theme === t} onClick={() => setTheme(t)}>
                  {label}
                </Button>
              ))}
            </div>
          </Row>
        </CardContent>
      </Card>
      <div className="mt-6">
        <Button variant="outline" onClick={signOut}><LogOut /> Sign out</Button>
      </div>
    </>
  );
}

export function CodingAgents() {
  const [origin, setOrigin] = useState("");
  useEffect(() => setOrigin(location.origin), []);
  const login = `uvx --from rehearsal-kit rehearsal login${origin && origin !== "https://rehearsalkit.xyz" ? ` --url ${origin}` : ""}`;
  const mcp = JSON.stringify({ mcpServers: { rehearsal: { command: "uvx", args: ["--from", "rehearsal-kit[mcp]>=0.1.1", "rehearsal", "mcp"] } } }, null, 2);
  const step = (title: string, description: ReactNode, commands: string[]) => (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle><CardDescription>{description}</CardDescription></CardHeader>
      <CardContent className="grid justify-items-start gap-2 overflow-x-auto">{commands.map((c) => <InstallChip key={c} command={c} />)}</CardContent>
    </Card>
  );
  return (
    <>
      <PageHeader title="Coding agents" description="Let Claude Code, Codex or another assistant build worlds and run evaluations for you. It uses your workspace through the Rehearsal skill and MCP server, and asks before anything that spends your allowance." />
      <div className="grid gap-4">
        {step("1. Sign in from your terminal", <>Opens this console to approve the sign-in. The terminal receives a &quot;Build and evaluate&quot; key, saved for your user only. You can revoke it on the <a className="underline underline-offset-2" href={routes.apiKeys}>API keys</a> page.</>, [login])}
        {step("2a. Claude Code", "Installs the skill and the MCP server.", ["claude plugin marketplace add MitudruDutta/rehearsal", "claude plugin install rehearsal@rehearsal"])}
        {step("2b. Codex CLI", "Installs the skill and the MCP server.", ["codex plugin marketplace add MitudruDutta/rehearsal", "codex plugin add rehearsal@rehearsal"])}
        <Card>
          <CardHeader>
            <CardTitle>2c. Any other MCP client</CardTitle>
            <CardDescription>Cursor, Claude Desktop, Windsurf, Antigravity and others: add this server to the client&apos;s MCP settings. It needs <a className="underline underline-offset-2" href="https://docs.astral.sh/uv/" target="_blank" rel="noreferrer">uv</a>.</CardDescription>
          </CardHeader>
          <CardContent><pre className="overflow-x-auto rounded-md border bg-muted/40 p-3 font-mono text-xs">{mcp}</pre></CardContent>
        </Card>
      </div>
    </>
  );
}

export function Credentials() {
  const creds = useResource<any[]>("/v1/credentials");
  return (
    <>
      <PageHeader title="Credentials" description="Registered by reference: the runner reads them from its own environment, and the console never shows their values." />
      <Card>
        <CardContent className="pt-6">
          {creds.data?.length === 0 && <p className="text-sm text-muted-foreground">No credentials registered.</p>}
          <Table><TableBody>{creds.data?.map((c) => <TableRow key={c.id}><TableCell>{c.name}</TableCell><TableCell><code>{c.env_var}</code></TableCell><TableCell>{c.available_on_runner ? <Tone tone="go">set on runner</Tone> : <Tone tone="stop">missing</Tone>}</TableCell></TableRow>)}</TableBody></Table>
        </CardContent>
      </Card>
    </>
  );
}

export function Exports() {
  const artifacts = useResource<any[]>("/v1/artifacts", 8000);
  const files = artifacts.data?.filter((a) => a.kind !== "source_upload");
  return (
    <>
      <PageHeader title="Exports" description="World bundles and datasets exported from this project." />
      <Card>
        <CardContent className="pt-6">
          {files?.length === 0 && <p className="text-sm text-muted-foreground">World bundles and datasets you export appear here.</p>}
          <Table><TableBody>{files?.map((a) => (
            <TableRow key={a.id}><TableCell><div className="font-medium">{a.name}</div><div className="text-xs text-muted-foreground">{a.kind.replace(/_/g, " ")}, {(a.size / 1e6).toFixed(1)} MB</div></TableCell><TableCell className="text-right"><Button asChild variant="outline" size="sm"><a href={`/v1/artifacts/${a.id}/download`}><Download /> Download</a></Button></TableCell></TableRow>
          ))}</TableBody></Table>
        </CardContent>
      </Card>
    </>
  );
}
