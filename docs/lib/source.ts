import { docs } from "fumadocs-mdx:collections/server";
import { type InferPageType, loader } from "fumadocs-core/source";
import { lucideIconsPlugin } from "fumadocs-core/source/plugins/lucide-icons";
import type * as PageTree from "fumadocs-core/page-tree";

/** Every page under content/, addressed from the site root: content/guides/evaluate.mdx is /guides/evaluate. */
export const source = loader({
  baseUrl: "/",
  source: docs.toFumadocsSource(),
  // "icon" in a meta.json or in a page's front matter names a Lucide icon; the sidebar shows it beside the title
  plugins: [lucideIconsPlugin()],
});

export type DocsPageEntry = InferPageType<typeof source>;

/** The page as Markdown: what "Copy as Markdown", the .md address and llms-full.txt serve. */
export async function pageMarkdown(page: DocsPageEntry): Promise<string> {
  const body = await page.data.getText("processed");
  const lead = page.data.description ? `\n${page.data.description}\n` : "";
  return `# ${page.data.title}\n${lead}\n${body.trim()}\n`;
}

/** Where a page's Markdown is served. The build also copies it to the page's own address with .md added. */
export function markdownUrl(page: DocsPageEntry): string {
  return `/raw/${page.slugs.join("/")}.md`;
}

export type SectionPages = { title: string; pages: DocsPageEntry[] };

/** Pages in reading order, one group for each section, as the sidebar shows them. */
export function pagesBySection(): SectionPages[] {
  const out: SectionPages[] = [];
  function walk(nodes: PageTree.Node[], into: DocsPageEntry[]) {
    for (const node of nodes) {
      if (node.type === "page") {
        const page = source.getNodePage(node);
        if (page) into.push(page);
      } else if (node.type === "folder") {
        if (node.index) {
          const page = source.getNodePage(node.index);
          if (page) into.push(page);
        }
        walk(node.children, into);
      }
    }
  }
  for (const node of source.getPageTree().children) {
    if (node.type !== "folder") continue;
    const pages: DocsPageEntry[] = [];
    walk([node], pages);
    out.push({ title: typeof node.name === "string" ? node.name : String(node.$id ?? "Section"), pages });
  }
  return out;
}
