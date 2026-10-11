import { site } from "@/lib/site";
import { pagesBySection } from "@/lib/source";

/** An index of every page with one line of description, for AI assistants (llmstxt.org). */
export function GET() {
  const lines = [
    "# Rehearsal documentation",
    "",
    `> Rehearsal builds a practice copy of an application, with fictional data, and tests an AI agent in it. Every outcome is decided by read-only checks on the application's own database. These pages describe rehearsal-kit ${site.version}.`,
    "",
    `Every page is also served as Markdown: add .md to its address. All pages in one file: ${site.url}/llms-full.txt`,
  ];
  for (const section of pagesBySection()) {
    lines.push("", `## ${section.title}`, "");
    for (const page of section.pages) {
      const about = page.data.description ? `: ${page.data.description}` : "";
      lines.push(`- [${page.data.title}](${site.url}${page.url}.md)${about}`);
    }
  }
  return new Response(lines.join("\n") + "\n", { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}

// a static export serves this as a file written at build time
export const dynamic = "force-static";
