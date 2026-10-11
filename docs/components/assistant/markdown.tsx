"use client";

import Link from "next/link";
import { type ReactNode, useState } from "react";
import { Check, Copy } from "lucide-react";

/* An answer arrives as Markdown, a few words at a time. This draws the part of Markdown an answer uses (paragraphs,
   lists, headings, code, links, bold) as React elements, so nothing the model writes is ever run as HTML. A code
   block whose closing fence has not arrived yet is drawn as code up to the last word received. */

type Block =
  | { kind: "code"; lang: string; text: string }
  | { kind: "heading"; text: string }
  | { kind: "list"; ordered: boolean; start: number; items: Block[][] }
  | { kind: "quote"; text: string }
  | { kind: "paragraph"; text: string };

const ITEM = /^(\s*)(?:[-*+]|(\d+)[.)])\s+(.*)$/;
const FENCE = /^\s*```(\S*)/;

function blocks(source: string): Block[] {
  const out: Block[] = [];
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(FENCE);
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) body.push(lines[i++]);
      i++; // the closing fence, when it has arrived
      out.push({ kind: "code", lang: fence[1], text: body.join("\n") });
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    if (heading) {
      out.push({ kind: "heading", text: heading[1] });
      i++;
      continue;
    }
    const first = line.match(ITEM);
    if (first) {
      // A step often holds more than its sentence: a command under it, then a remark. Everything set in under an
      // item belongs to it, across empty lines, and is read as Markdown of its own.
      const indent = first[1].length;
      const ordered = first[2] !== undefined;
      const items: Block[][] = [];
      while (i < lines.length) {
        // an empty line between two steps does not end the list
        let at = i;
        while (at < lines.length && !lines[at].trim()) at++;
        const item = lines[at]?.match(ITEM);
        if (!item || item[1].length !== indent || (item[2] !== undefined) !== ordered) break;
        i = at;
        const inner = [item[3]];
        const depth = lines[i].length - item[3].length;
        i++;
        while (i < lines.length) {
          const next = lines[i];
          const leading = next.length - next.trimStart().length;
          if (next.trim() && leading <= indent) break;
          if (!next.trim()) {
            const after = lines.slice(i + 1).find((l) => l.trim());
            if (!after || after.length - after.trimStart().length <= indent) break;
          }
          inner.push(next.slice(Math.min(leading, depth)));
          i++;
        }
        items.push(blocks(inner.join("\n")));
      }
      out.push({ kind: "list", ordered, start: Number(first[2] ?? 1), items });
      continue;
    }
    if (line.startsWith(">")) {
      const body: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) body.push(lines[i++].replace(/^>\s?/, ""));
      out.push({ kind: "quote", text: body.join(" ") });
      continue;
    }
    const body: string[] = [];
    while (i < lines.length && lines[i].trim() && !FENCE.test(lines[i]) && !/^#{1,6}\s/.test(lines[i]) && !ITEM.test(lines[i]) && !lines[i].startsWith(">")) body.push(lines[i++].trim());
    out.push({ kind: "paragraph", text: body.join(" ") });
  }
  return out;
}

/** Only addresses a reader can safely follow: a page of this site, or a web address. */
function safeHref(href: string): { href: string; internal: boolean } | null {
  if (href.startsWith("/") && !href.startsWith("//")) return { href, internal: true };
  if (/^https?:\/\//i.test(href)) return { href, internal: false };
  return null;
}

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\[[^\]\n]+\]\([^)\s]+\))/g;

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const match of text.matchAll(INLINE)) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("`")) {
      out.push(
        <code key={key++} className="rounded-[5px] border bg-muted px-1 py-px font-mono text-[0.8125rem] text-foreground [overflow-wrap:anywhere]">
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("**")) {
      out.push(
        <strong key={key++} className="font-semibold text-foreground">
          {inline(token.slice(2, -2))}
        </strong>,
      );
    } else {
      const [, label, href] = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/) ?? [];
      const target = href ? safeHref(href) : null;
      const className = "font-medium text-link underline decoration-link/35 underline-offset-[3px] hover:decoration-link";
      if (!target) out.push(label ?? token);
      else if (target.internal)
        out.push(
          <Link key={key++} href={target.href} className={className}>
            {inline(label)}
          </Link>,
        );
      else
        out.push(
          <a key={key++} href={target.href} target="_blank" rel="noreferrer" className={className}>
            {inline(label)}
          </a>,
        );
    }
    last = match.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function Code({ lang, text }: { lang: string; text: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // the browser refused the clipboard; the text can still be selected
    }
  }
  return (
    <div className="group/code relative min-w-0 overflow-hidden rounded-lg border bg-code-surface">
      {lang && <div className="border-b px-3 py-1 font-mono text-[11px] text-muted-foreground">{lang}</div>}
      {/* a command wider than the panel continues on the next line instead of hiding behind a scrollbar */}
      <pre className="whitespace-pre-wrap px-3 py-2.5 font-mono text-[0.8125rem] leading-[1.3rem] text-foreground [overflow-wrap:anywhere]">
        <code>{text}</code>
      </pre>
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? "Copied" : "Copy code"}
        className="absolute right-1.5 top-1.5 grid size-7 place-items-center rounded-md border bg-background text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover/code:opacity-100"
      >
        {copied ? <Check className="size-3.5 text-success" aria-hidden="true" /> : <Copy className="size-3.5" aria-hidden="true" />}
      </button>
    </div>
  );
}

function Blocks({ list }: { list: Block[] }) {
  return list.map((block, i) => {
    if (block.kind === "code") return <Code key={i} lang={block.lang} text={block.text} />;
    if (block.kind === "heading")
      return (
        <p key={i} className="mt-1 font-heading font-semibold text-foreground">
          {inline(block.text)}
        </p>
      );
    if (block.kind === "list") {
      const List = block.ordered ? "ol" : "ul";
      return (
        <List key={i} start={block.ordered ? block.start : undefined} className={`grid gap-2 pl-5 marker:text-muted-foreground ${block.ordered ? "list-decimal" : "list-disc"}`}>
          {block.items.map((item, n) => (
            <li key={n} className="min-w-0 pl-0.5">
              <div className="grid min-w-0 gap-2">
                <Blocks list={item} />
              </div>
            </li>
          ))}
        </List>
      );
    }
    if (block.kind === "quote")
      return (
        <blockquote key={i} className="border-l-2 pl-3 text-muted-foreground">
          {inline(block.text)}
        </blockquote>
      );
    return <p key={i}>{inline(block.text)}</p>;
  });
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="grid min-w-0 gap-3 text-[0.9375rem] leading-[1.6] text-prose">
      <Blocks list={blocks(text)} />
    </div>
  );
}
