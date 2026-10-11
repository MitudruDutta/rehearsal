import { site } from "@/lib/site";
import { pageMarkdown, pagesBySection } from "@/lib/source";

/** Every page as Markdown, in reading order, in one file. */
export async function GET() {
  const parts: string[] = [`<!-- Rehearsal documentation, rehearsal-kit ${site.version}. Source: ${site.url} -->`];
  for (const section of pagesBySection()) {
    for (const page of section.pages) {
      parts.push(`<!-- ${site.url}${page.url} -->\n\n${await pageMarkdown(page)}`);
    }
  }
  return new Response(parts.join("\n\n---\n\n"), { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}

// a static export serves this as a file written at build time
export const dynamic = "force-static";
