import { notFound } from "next/navigation";
import { pageMarkdown, source } from "@/lib/source";

/** One page as Markdown, at /raw/<page>.md. scripts/postbuild.mjs also copies it to <page>.md. */
export async function GET(_request: Request, { params }: RouteContext<"/raw/[...slug]">) {
  const { slug } = await params;
  const last = slug[slug.length - 1] ?? "";
  if (!last.endsWith(".md")) notFound();
  const page = source.getPage([...slug.slice(0, -1), last.slice(0, -3)]);
  if (!page) notFound();
  return new Response(await pageMarkdown(page), { headers: { "Content-Type": "text/markdown; charset=utf-8" } });
}

export function generateStaticParams() {
  return source.getPages().map((page) => {
    const slugs = page.slugs;
    return { slug: [...slugs.slice(0, -1), `${slugs[slugs.length - 1]}.md`] };
  });
}

// a static export serves this as a file written at build time
export const dynamic = "force-static";
