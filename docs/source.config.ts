import { defineConfig, defineDocs, frontmatterSchema, metaSchema } from "fumadocs-mdx/config";
import { rehypeCodeDefaultOptions } from "fumadocs-core/mdx-plugins";
import { z } from "zod";

// Front matter every page may carry, on top of title and description. From the docs plan, section 4.2.
const pageSchema = frontmatterSchema.extend({
  /** who the page is written for, one line */
  audience: z.string().optional(),
  /** the date the page was last checked against the product (YYYY-MM-DD) */
  last_reviewed: z.union([z.string(), z.date()]).optional(),
  /** true when scripts/generate_reference.py writes the body */
  generated: z.boolean().optional(),
  /** meta row under a guide's title: how long it takes, whether it spends model budget, what is needed first */
  time: z.string().optional(),
  cost: z.string().optional(),
  needs: z.string().optional(),
  /** a label beside the title: "coming-soon", "self-hosted", "hosted" */
  label: z.enum(["coming-soon", "self-hosted", "hosted"]).optional(),
});

export const docs = defineDocs({
  dir: "content",
  docs: {
    schema: pageSchema,
    // the Markdown of each page, for the .md address, "Copy as Markdown" and llms-full.txt
    postprocess: { includeProcessedMarkdown: true },
  },
  meta: { schema: metaSchema },
});

type Transformer = NonNullable<typeof rehypeCodeDefaultOptions.transformers>[number];
type Line = Parameters<NonNullable<Transformer["line"]>>[0];
type Token = Line["children"][number];

/** Languages whose samples hold values the reader must replace. Markup languages are left out: there <div> is code. */
const WITH_PLACEHOLDERS = new Set(["bash", "sh", "shell", "shellscript", "powershell", "ps1", "text", "txt", "plaintext", "python", "py", "json", "http", "yaml", "dotenv", "ini"]);

/** The text of a token that is one element around one piece of text, which is what the highlighter writes. */
function textOf(token: Token): string | null {
  if (token.type !== "element" || token.children.length !== 1) return null;
  const only = token.children[0];
  return only.type === "text" ? only.value : null;
}

/**
 * Marks a value the reader must replace, written <like_this>, so it looks different from text to type as it is.
 * The highlighter may cut "<app_id>" into several tokens, so tokens are cut again at the edges of each placeholder.
 */
function placeholders(): Transformer {
  return {
    name: "rehearsal:placeholders",
    line(node) {
      if (!WITH_PLACEHOLDERS.has(this.options.lang ?? "")) return;
      const texts = node.children.map(textOf);
      if (texts.some((t) => t === null)) return;
      const full = texts.join("");
      const ranges = [...full.matchAll(/<[a-z][a-z0-9_]*>/g)].map((m) => [m.index, m.index + m[0].length] as const);
      if (ranges.length === 0) return;
      const out: Token[] = [];
      let position = 0;
      node.children.forEach((token, index) => {
        if (token.type !== "element") return;
        const start = position;
        const end = start + (texts[index] ?? "").length;
        position = end;
        const cuts = new Set([start, end]);
        for (const [a, b] of ranges) {
          if (a > start && a < end) cuts.add(a);
          if (b > start && b < end) cuts.add(b);
        }
        const edges = [...cuts].sort((x, y) => x - y);
        for (let i = 0; i < edges.length - 1; i++) {
          const [a, b] = [edges[i], edges[i + 1]];
          const inside = ranges.some(([ra, rb]) => a >= ra && b <= rb);
          const existing = token.properties.class;
          const classes = Array.isArray(existing) ? existing.map(String) : existing ? [String(existing)] : [];
          out.push({
            ...token,
            properties: inside ? { ...token.properties, class: [...classes, "rh-placeholder"] } : { ...token.properties },
            children: [{ type: "text", value: full.slice(a, b) }],
          });
        }
      });
      node.children = out;
    },
  };
}

/** What the highlighter's themes (GitHub light and dark) use for the names of commands, functions and classes. */
const THEME_VIOLET: [RegExp, string][] = [
  [/#6f42c1/gi, "#11707e"],
  [/#b392f0/gi, "#56d4dd"],
];

/**
 * The site has no violet: its accent is the blue of the landing page. The highlighter's themes paint the name of a
 * command or a function violet, so those names take a teal instead. Plain blue is taken: flags and constants use it.
 */
function noViolet(): Transformer {
  return {
    name: "rehearsal:no-violet",
    span(node) {
      const style = node.properties.style;
      if (typeof style !== "string") return;
      node.properties.style = THEME_VIOLET.reduce((text, [from, to]) => text.replace(from, to), style);
    },
  };
}

export default defineConfig({
  mdxOptions: {
    rehypeCodeOptions: {
      ...rehypeCodeDefaultOptions,
      transformers: [...(rehypeCodeDefaultOptions.transformers ?? []), noViolet(), placeholders()],
    },
  },
});
