import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DocsBody, DocsDescription, DocsPage, DocsTitle } from "fumadocs-ui/layouts/notebook/page";
import { getMDXComponents, Label, MetaRow } from "@/components/mdx";
import { PageFeedback, PageToolbar } from "@/components/page-actions";
import { site } from "@/lib/site";
import { markdownUrl, source } from "@/lib/source";

function reviewed(value: string | Date | undefined): string | null {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}

export default async function Page(props: PageProps<"/[...slug]">) {
  const { slug } = await props.params;
  const page = source.getPage(slug);
  if (!page) notFound();

  const { body: MDX, toc, title, description, time, cost, needs, label, generated, last_reviewed } = page.data;
  const checked = reviewed(last_reviewed);
  // a generated page is changed in the code it comes from, not in its file
  const editUrl = generated ? undefined : `${site.editBase}/${page.path}`;
  const feedback = <PageFeedback title={title} path={page.url} editUrl={editUrl} />;

  return (
    <DocsPage
      toc={toc}
      id="content"
      // the column sits in the middle of the space between the sidebar and the right rail
      className="*:mx-auto *:w-full *:max-w-(--rh-column)"
      tableOfContent={{ style: "clerk", footer: <div className="mt-6 border-t pt-5">{feedback}</div> }}
      tableOfContentPopover={{ style: "clerk" }}
    >
      <div>
        <DocsTitle className="font-heading text-4xl font-bold leading-[2.625rem] tracking-tight">
          {title}
          {label && (
            <span className="ml-3 align-middle">
              <Label kind={label} />
            </span>
          )}
        </DocsTitle>
        <DocsDescription className="mb-0 mt-3 max-w-(--rh-measure) text-lg leading-[1.875rem] text-muted-foreground">{description}</DocsDescription>
        <div className="mt-5">
          <PageToolbar path={page.url} markdownUrl={markdownUrl(page)} editUrl={editUrl} />
        </div>
      </div>
      <MetaRow time={time} cost={cost} needs={needs} />
      <DocsBody className="rh-prose">
        <MDX components={getMDXComponents()} />
      </DocsBody>
      <div className="mt-8 flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
        <span>
          {generated
            ? `Generated from the code of rehearsal-kit ${site.version}.`
            : checked
              ? `Checked against rehearsal-kit ${site.version} on ${checked}.`
              : null}
        </span>
      </div>
      {/* the right rail is hidden under 1280 px, so the same question follows the page there */}
      <div className="mt-2 border-t pt-6 xl:hidden">{feedback}</div>
    </DocsPage>
  );
}

export function generateStaticParams() {
  return source.generateParams();
}

export async function generateMetadata(props: PageProps<"/[...slug]">): Promise<Metadata> {
  const { slug } = await props.params;
  const page = source.getPage(slug);
  if (!page) notFound();
  return {
    title: page.data.title,
    description: page.data.description,
    alternates: { canonical: page.url, types: { "text/markdown": `${page.url}.md` } },
    openGraph: { title: page.data.title, description: page.data.description, url: page.url },
  };
}
