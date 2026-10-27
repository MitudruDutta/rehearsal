/**
 * Exports what Rehearsal actually produced for an application into examples/<app>/. The mirror of
 * rehearsal/sdk/examples.py.
 *
 * Only published, validated output is written. Train scenarios are written in full; dev and held-out scenarios are
 * listed by title only, so publishing the example does not leak the evaluation set. Run results come from finished runs.
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { parse } from "yaml";

import type { Json, Rehearsal } from "./client.js";

export function safeName(value: string): string {
  if (!value || value === "." || value === ".." || /[/\\\0]/.test(value)) throw new Error("unsafe example file name");
  return value;
}

export function assetsDir(): string {
  return fileURLToPath(new URL("../../assets/", import.meta.url));
}

function catalog(): Record<string, Json> {
  const data = parse(readFileSync(join(assetsDir(), "catalog.yaml"), "utf8"));
  return Object.fromEntries((data.applications as Json[]).map((a) => [a.name, a]));
}

const dump = (value: unknown) => JSON.stringify(value, null, 1);

export async function exportExample(client: Rehearsal, worldVersionId: string, root = process.cwd()): Promise<Json> {
  const wv = await client.worlds.version(worldVersionId);
  const manifest = wv.manifest;
  const app = safeName(manifest.name);
  const entry = catalog()[app] ?? {};
  const dest = resolve(root, "examples", app);
  if (relative(resolve(root), dest).startsWith("..")) throw new Error("example directory escapes the working directory");
  mkdirSync(join(dest, "scenarios", "train"), { recursive: true });
  mkdirSync(join(dest, "runs"), { recursive: true });
  const scenarios = (await client.worlds.scenarios(worldVersionId)).filter((s) => s.status === "approved");
  for (const s of scenarios) if (s.split === "train") writeFileSync(join(dest, "scenarios", "train", `${safeName(s.slug)}.json`), dump(s.spec));
  const validation = wv.validation ?? {};
  writeFileSync(join(dest, "world.json"), dump({ version: wv.version, content_hash: wv.content_hash, manifest }));
  writeFileSync(join(dest, "capabilities.json"), dump({ capabilities: wv.capabilities, isolation: validation.isolation, repairs: validation.repairs, rejected: validation.rejected }));
  const runs = (await client.get<Json[]>("/v1/runs")).filter((r) => r.world_version_id === worldVersionId && r.status === "finished");
  for (const r of runs) writeFileSync(join(dest, "runs", `${safeName(r.id)}.json`), dump({ config: r.config, summary: r.summary, finished_at: r.finished_at }));
  const prov = wv.provenance ?? {};
  const tools: Json[] = manifest.tools ?? [];
  const bySplit: Record<string, Json[]> = {};
  for (const s of scenarios) (bySplit[s.split] ??= []).push(s);
  const domain = String(entry.domain ?? "");
  const lines = [
    `# ${app}`, "",
    `${domain.charAt(0).toUpperCase() + domain.slice(1)} application, ${entry.license ?? "licence: see upstream"}. Not written by the Rehearsal authors.`,
    `Role in testing: ${entry.split === "holdout" ? "held out (never inspected while developing the compiler)" : "development application"}.`, "",
    "## Source compiled", "",
    `- Repository: ${prov.url ?? entry.source?.url ?? ""} at commit \`${prov.commit ?? entry.source?.commit ?? ""}\``,
    ...Object.entries(prov.images ?? {}).map(([name, img]) => `- Image \`${name}\`: \`${img}\``),
    `- World version ${wv.version}, content hash \`${wv.content_hash}\``,
    `- Compiler model chain: \`${prov.compiler_chain ?? ""}\`; model spend $${Number(prov.spent_usd ?? 0).toFixed(2)}` + (prov.tokens ? `, ${Number(prov.tokens).toLocaleString("en-US")} tokens` : ""), "",
    "## What the World Compiler produced", "",
    `- ${(manifest.services ?? []).length} services in an isolated network: ` + (manifest.services ?? []).map((s: Json) => `\`${s.name}\``).join(", "),
    `- ${(manifest.roles ?? []).length} roles: ` + (manifest.roles ?? []).map((r: Json) => `\`${r.name}\``).join(", "),
    `- ${tools.length} agent tools (${tools.filter((t) => t.mutating).length} that change state)`,
    `- ${scenarios.length} validated scenarios: ` + Object.entries(bySplit).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${v.length} ${k}`).join(", "),
    `- ${(validation.repairs ?? []).filter((r: Json) => r.outcome === "repaired").length} scenarios repaired by the compiler after failing validation; ${Object.keys(validation.rejected ?? {}).length} rejected`, "",
    "## Scenarios", "",
    "| Scenario | Family | Split | Goal changes |", "|---|---|---|---|",
    ...[...scenarios].sort((a, b) => a.split.localeCompare(b.split) || a.slug.localeCompare(b.slug))
      .map((s) => `| ${s.spec?.title ?? s.slug} | ${s.family} | ${s.split} | ${Math.max(0, (s.spec?.goals ?? []).length - 1)} |`),
    "", "Train scenarios are in `scenarios/train/`. Dev and held-out scenarios are kept in the private evaluation bundle.", "",
    "## Tools", "",
    "| Tool | Operation | Roles |", "|---|---|---|",
    ...tools.map((t) => `| \`${t.name}\` | \`${t.graphql ? "GraphQL" : t.method} ${t.path}\` | ${(t.roles ?? []).join(", ")} |`),
    "", "## Results", "",
  ];
  if (!runs.length) lines.push("No finished evaluations yet.");
  else {
    lines.push("| Run | Agent | Scenarios | Verified success | Episodes with rule violations | False completions | Recovered after faults |", "|---|---|---|---|---|---|---|");
    for (const r of runs) {
      for (const [prof, s] of Object.entries<Json>(r.summary?.profiles ?? {})) {
        const o = s.overall;
        const rate = o.success_rate === null || o.success_rate === undefined ? "–" : `${Math.round(o.success_rate * 100)}% (${o.successes}/${o.finished})`;
        lines.push(`| \`${r.id}\` | ${prof} | ${(r.config.splits ?? []).join(", ")} | ${rate} | ${o.hard_violation_episodes} | ${o.false_completions} | ${o.recovered} |`);
      }
    }
  }
  writeFileSync(join(dest, "README.md"), lines.join("\n") + "\n");
  const row = {
    application: app, domain: entry.domain ?? "", license: entry.license ?? "", split: entry.split ?? "development",
    status: "published", world_version: wv.version, scenarios: scenarios.length, tools: tools.length,
    repairs: (validation.repairs ?? []).filter((r: Json) => r.outcome === "repaired").length,
    spend_usd: prov.spent_usd ?? null, tokens: prov.tokens ?? null,
  };
  const indexPath = join(root, "examples", "index.json");
  let index: Json = { applications: [] };
  try { index = JSON.parse(readFileSync(indexPath, "utf8")); } catch { /* first example */ }
  index.applications = [...(index.applications ?? []).filter((a: Json) => a.application !== app), row];
  writeFileSync(indexPath, dump(index));
  const pub = join(root, "web", "public", "examples");
  mkdirSync(pub, { recursive: true });
  writeFileSync(join(pub, "index.json"), dump(index));
  return row;
}
