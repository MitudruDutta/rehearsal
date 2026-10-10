"use client";

import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "../api";

export function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState<boolean | null>(false);
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text); // needs https or localhost
          setDone(true);
        } catch {
          setDone(null);
        }
        setTimeout(() => setDone(false), 2000);
      }}
    >
      {done ? <Check /> : <Copy />} {done ? "Copied" : done === null ? "Select and copy" : label}
    </Button>
  );
}

/** A newly created key, shown once. */
export function KeyReveal({ apiKey }: { apiKey: string }) {
  return (
    <div className="rounded-lg border border-primary/40 bg-primary/10 p-3">
      <div className="mb-2 text-sm font-medium">Your new API key. Copy it now; it is not shown again.</div>
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 break-all rounded bg-background/60 px-2 py-1.5 font-mono text-xs">{apiKey}</code>
        <CopyButton text={apiKey} label="Copy key" />
      </div>
    </div>
  );
}

function Snippet({ code, note }: { code: string; note?: string }) {
  return (
    <div className="min-w-0">
      <div className="relative">
        <pre className="overflow-x-auto rounded-lg bg-muted p-3 pr-28 font-mono text-xs leading-relaxed">{code}</pre>
        <div className="absolute right-2 top-2"><CopyButton text={code} label="Copy" /></div>
      </div>
      {note && <p className="mt-2 text-xs text-muted-foreground">{note}</p>}
    </div>
  );
}

/** How to use a key: from an AI assistant over MCP, the terminal, Python, or plain HTTP. Fills in the key when one was just created. */
export function Connect({ apiKey }: { apiKey?: string | null }) {
  const [wheel, setWheel] = useState<string | null>(null);
  useEffect(() => {
    api<{ client_wheel: string | null }>("/v1/health").then((h) => setWheel(h.client_wheel)).catch(() => setWheel(null));
  }, []);
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const key = apiKey || "rh_your_key";
  const pkg = (extra: string) => (wheel ? `"rehearsal-kit${extra} @ ${origin}${wheel}"` : `"rehearsal-kit${extra}"`);
  const mcpJson = JSON.stringify({ mcpServers: { rehearsal: { command: "rehearsal", args: ["mcp"], env: { REHEARSAL_URL: origin, REHEARSAL_API_KEY: key } } } }, null, 2);
  return (
    <Tabs defaultValue="claude" className="min-w-0">
      <TabsList className="flex-wrap">
        <TabsTrigger value="claude">Claude Code</TabsTrigger>
        <TabsTrigger value="mcp">Other MCP clients</TabsTrigger>
        <TabsTrigger value="cli">Terminal</TabsTrigger>
        <TabsTrigger value="python">Python</TabsTrigger>
        <TabsTrigger value="http">HTTP</TabsTrigger>
      </TabsList>
      <TabsContent value="claude">
        <Snippet
          code={[`pip install ${pkg("[mcp]")}`, `claude mcp add rehearsal -e REHEARSAL_URL=${origin} -e REHEARSAL_API_KEY=${key} -- rehearsal mcp`, "rehearsal skill install"].join("\n")}
          note="Then ask Claude, for example: “Run the baseline agent on the Mattermost world and tell me why it failed.” The skill teaches it the workflow, and it asks you before it starts anything that spends your allowance."
        />
      </TabsContent>
      <TabsContent value="mcp">
        <Snippet code={`pip install ${pkg("[mcp]")}\n\n${mcpJson}`} note="Add the JSON to your client's MCP settings (Cursor, Codex, Windsurf, and others that run stdio MCP servers)." />
      </TabsContent>
      <TabsContent value="cli">
        <Snippet
          code={[`pip install ${pkg("")}`, `export REHEARSAL_URL=${origin}`, `export REHEARSAL_API_KEY=${key}`, "rehearsal apps list", "rehearsal build <application_id> --watch", "rehearsal eval <world_version_id> --profile <agent_id> --split dev"].join("\n")}
        />
      </TabsContent>
      <TabsContent value="python">
        <Snippet
          code={[
            "from rehearsal.sdk import Rehearsal",
            "",
            `rh = Rehearsal(api_key="${key}", base_url="${origin}")`,
            'run = rh.evaluations.create("<world_version_id>", ["<agent_id>"], splits=["dev"])',
            'print(rh.runs.get(run["run_id"])["status"])',
          ].join("\n")}
          note="An agent you run yourself can act inside episodes through rh.external (create the agent with driver “external”)."
        />
      </TabsContent>
      <TabsContent value="http">
        <Snippet code={`curl -H "Authorization: Bearer ${key}" ${origin}/v1/worlds`} note={`Every endpoint is described at ${origin}/docs.`} />
      </TabsContent>
    </Tabs>
  );
}
