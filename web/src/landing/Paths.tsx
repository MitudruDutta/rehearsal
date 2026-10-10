"use client";

import { Check } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const CLI = `pip install rehearsal-kit
export REHEARSAL_URL=https://your-rehearsal-server
export REHEARSAL_API_KEY=rh_...            # Settings > API keys

rehearsal apps add billing --git https://github.com/acme/billing \\
  --commit 4ebd5e3 --image web=registry.acme.dev/billing@sha256:...
rehearsal build <app_id> --watch
rehearsal eval <world_version_id> --profile <profile_id> --watch`;

const PY = `from rehearsal.sdk import Rehearsal

rh = Rehearsal()   # REHEARSAL_URL and REHEARSAL_API_KEY
app = rh.applications.create("billing",
    {"kind": "git", "url": "https://github.com/acme/billing", "commit": "4ebd5e3"},
    images={"web": "registry.acme.dev/billing@sha256:..."})
build = rh.worlds.build(app["id"])
rh.jobs.wait(build["job_id"])`;

const DASHBOARD = [
  ["Sign in", "With Google or email. A workspace is created for you."],
  ["Add your application", "Paste the repository URL, the commit, and the images you already publish."],
  ["Build the practice world", "Watch the compiler work live; every phase and tool call is visible."],
  ["Rehearse an agent", "Pick a model and instructions, run the jobs, read the verdict."],
];

export function Paths() {
  return (
    <Tabs defaultValue="dashboard" className="w-full">
      <TabsList>
        <TabsTrigger value="dashboard">Dashboard</TabsTrigger>
        <TabsTrigger value="cli">CLI</TabsTrigger>
        <TabsTrigger value="python">Python</TabsTrigger>
      </TabsList>
      <TabsContent value="dashboard" className="mt-4">
        <ol className="grid gap-3 sm:grid-cols-2">
          {DASHBOARD.map(([t, d], i) => (
            <li key={t} className="flex gap-3 rounded-xl border bg-card p-4">
              <span className="grid size-7 shrink-0 place-items-center rounded-full bg-primary/15 text-sm font-semibold text-primary">{i + 1}</span>
              <span><span className="block font-medium">{t}</span><span className="mt-0.5 block text-sm text-muted-foreground">{d}</span></span>
            </li>
          ))}
        </ol>
        <p className="mt-3 flex items-center gap-2 text-sm text-muted-foreground"><Check className="size-4 text-success" /> No code needed. The CLI and SDK do the same things for CI and scripts.</p>
      </TabsContent>
      <TabsContent value="cli" className="mt-4"><pre className="overflow-x-auto rounded-xl border bg-card p-5 font-mono text-[13px] leading-relaxed">{CLI}</pre></TabsContent>
      <TabsContent value="python" className="mt-4"><pre className="overflow-x-auto rounded-xl border bg-card p-5 font-mono text-[13px] leading-relaxed">{PY}</pre></TabsContent>
    </Tabs>
  );
}
