"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";

/** Client-side navigation usable from plain event handlers. The console layout
 * mounts <RouterBridge/>, which hands this module the Next router. */

type Push = (href: string) => void;
let push: Push = (href) => window.location.assign(href);

export function RouterBridge() {
  const router = useRouter();
  useEffect(() => {
    push = (href) => router.push(href);
  }, [router]);
  return null;
}

export function go(href: string) {
  push(href);
}

export function useQuery(name: string): string | null {
  return useSearchParams().get(name);
}

export const routes = {
  overview: "/app/",
  applications: "/app/applications/",
  build: (id: string) => `/app/build/?id=${id}`,
  world: (id: string) => `/app/world/?id=${id}`,
  agents: "/app/agents/",
  runs: (world?: string) => `/app/runs/${world ? `?world=${world}` : ""}`,
  run: (id: string, episode?: string) => `/app/run/?id=${id}${episode ? `&episode=${episode}` : ""}`,
  fix: (job: string) => `/app/fix/?job=${job}`,
  compare: (a?: string, b?: string) => `/app/compare/${a ? `?a=${a}${b ? `&b=${b}` : ""}` : ""}`,
  apiKeys: "/app/api-keys/",
  settings: "/app/settings/",
  settingsAgents: "/app/settings/agents/",
  settingsCredentials: "/app/settings/credentials/",
  settingsExports: "/app/settings/exports/",
  billing: "/app/billing/",
  admin: "/app/admin/",
};
