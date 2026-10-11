"use client";

import { useState } from "react";
import { Check, ChevronDown, Copy, ExternalLink, FileText, Pencil, Sparkles, ThumbsDown, ThumbsUp } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "fumadocs-ui/components/ui/popover";
import { site } from "@/lib/site";
import { useAssistant } from "./assistant/context";

declare global {
  interface Window {
    /** set by the analytics script when one is installed; nothing is recorded without it */
    plausible?: (event: string, options?: { props?: Record<string, string> }) => void;
  }
}

const tool = "inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-md border bg-card px-2.5 text-[13px] font-medium text-foreground transition-colors hover:border-input hover:bg-muted";

function CopyMarkdown({ markdownUrl }: { markdownUrl: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  async function copy() {
    try {
      const res = await fetch(markdownUrl);
      if (!res.ok) throw new Error(String(res.status));
      await navigator.clipboard.writeText(await res.text());
      setState("copied");
    } catch {
      setState("failed");
    }
    setTimeout(() => setState("idle"), 2000);
  }
  return (
    <button type="button" onClick={copy} className={tool}>
      {state === "copied" ? <Check className="size-3.5 text-success" aria-hidden="true" /> : <Copy className="size-3.5 text-muted-foreground" aria-hidden="true" />}
      <span aria-live="polite">{state === "copied" ? "Copied" : state === "failed" ? "Could not copy" : "Copy Markdown"}</span>
    </button>
  );
}

/** The page somewhere else: as plain Markdown, in the reader's own assistant, or in the repository. */
function OpenIn({ markdownUrl, pageUrl, editUrl }: { markdownUrl: string; pageUrl: string; editUrl?: string }) {
  // an assistant reads the Markdown of the page, which the site serves at the page's address with .md added
  const prompt = `Read ${site.url}${pageUrl}.md. I want to ask questions about it.`;
  const items: [label: string, href: string][] = [
    ["View as Markdown", markdownUrl],
    ["Open in Claude", `https://claude.ai/new?${new URLSearchParams({ q: prompt })}`],
    ["Open in ChatGPT", `https://chatgpt.com/?${new URLSearchParams({ prompt, hints: "search" })}`],
    ...(editUrl ? ([["Edit on GitHub", editUrl]] as [string, string][]) : []),
  ];
  return (
    <Popover>
      <PopoverTrigger className={`${tool} data-[state=open]:bg-muted`}>
        Open
        <ChevronDown className="size-3.5 text-muted-foreground" aria-hidden="true" />
      </PopoverTrigger>
      <PopoverContent align="start" className="flex w-56 flex-col p-1">
        {items.map(([label, href], i) => (
          <a key={label} href={href} target="_blank" rel="noreferrer" className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-foreground hover:bg-muted">
            {i === 0 ? <FileText className="size-4 text-muted-foreground" aria-hidden="true" /> : i === items.length - 1 && editUrl ? <Pencil className="size-4 text-muted-foreground" aria-hidden="true" /> : <Sparkles className="size-4 text-muted-foreground" aria-hidden="true" />}
            {label}
            <ExternalLink className="ml-auto size-3.5 text-muted-foreground" aria-hidden="true" />
          </a>
        ))}
      </PopoverContent>
    </Popover>
  );
}

/** Under the title of every page: take the page with you as Markdown, open it elsewhere, or ask about it here. */
export function PageToolbar({ path, markdownUrl, editUrl }: { path: string; markdownUrl: string; editUrl?: string }) {
  const { ask } = useAssistant();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <CopyMarkdown markdownUrl={markdownUrl} />
      <OpenIn markdownUrl={markdownUrl} pageUrl={path} editUrl={editUrl} />
      <button type="button" onClick={() => ask()} className={tool}>
        <Sparkles className="size-3.5 text-link" aria-hidden="true" />
        Ask about this page
      </button>
    </div>
  );
}

function Helpful({ title, path }: { title: string; path: string }) {
  const [vote, setVote] = useState<"yes" | "no" | null>(null);
  function send(v: "yes" | "no") {
    setVote(v);
    window.plausible?.("Helpful", { props: { page: path, answer: v } });
  }
  const issue = `${site.repo}/issues/new?title=${encodeURIComponent(`Docs: ${title}`)}&body=${encodeURIComponent(`Page: ${path}\n\nWhat was missing or wrong?\n`)}`;
  if (vote === "yes") return <p className="text-sm text-muted-foreground">Thank you.</p>;
  if (vote === "no")
    return (
      <p className="text-sm leading-6 text-muted-foreground">
        Thank you.{" "}
        <a href={issue} target="_blank" rel="noreferrer" className="text-link underline underline-offset-2">
          Tell us what was missing
        </a>
        , if you have a minute.
      </p>
    );
  const button = "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-sm text-muted-foreground transition-colors hover:border-input hover:text-foreground";
  return (
    <div>
      <p className="text-sm font-medium text-foreground">Was this page helpful?</p>
      <div className="mt-2 flex gap-2">
        <button type="button" className={button} onClick={() => send("yes")}>
          <ThumbsUp className="size-3.5" aria-hidden="true" /> Yes
        </button>
        <button type="button" className={button} onClick={() => send("no")}>
          <ThumbsDown className="size-3.5" aria-hidden="true" /> No
        </button>
      </div>
    </div>
  );
}

/** The helpful question and "Edit this page". In the right rail, and under the page on a narrow screen. */
export function PageFeedback({ title, path, editUrl }: { title: string; path: string; editUrl?: string }) {
  return (
    <div className="grid gap-4">
      <Helpful title={title} path={path} />
      {editUrl && (
        <a href={editUrl} target="_blank" rel="noreferrer" className="flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground">
          <Pencil className="size-4" aria-hidden="true" />
          Edit this page
        </a>
      )}
    </div>
  );
}
