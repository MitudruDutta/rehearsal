"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import { ArrowUp, Check, Copy, ExternalLink, RotateCcw, Search, Sparkles, Square, SquarePen, X } from "lucide-react";
import { useSearchContext } from "fumadocs-ui/contexts/search";
import { site } from "@/lib/site";
import { AskChip } from "./buttons";
import { type Message, type Source, useAssistant } from "./context";
import { Markdown } from "./markdown";

const STARTERS = [
  "How do I evaluate an agent from a terminal?",
  "What does a build cost, and how do I limit it?",
  "What does the verdict “not achieved” mean?",
  "How do I run Rehearsal on my own server?",
];

const iconButton = "grid size-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40";

/** The question as a prompt for the reader's own assistant, which can read the site's llms.txt once it is published. */
function handOff(question: string) {
  const prompt = `Read ${site.url}/llms.txt, open the pages it lists that are relevant, and answer this question about Rehearsal: ${question}`;
  return [
    ["Ask Claude", `https://claude.ai/new?${new URLSearchParams({ q: prompt })}`],
    ["Ask ChatGPT", `https://chatgpt.com/?${new URLSearchParams({ prompt, hints: "search" })}`],
  ] as const;
}

/** Shown in place of an answer when this site has no assistant to ask, or it did not respond. */
function Offline({ question, reason }: { question?: string; reason?: string }) {
  const { setOpenSearch } = useSearchContext();
  const action = "inline-flex h-8 items-center gap-1.5 rounded-md border bg-background px-2.5 text-sm font-medium text-foreground transition-colors hover:border-input hover:bg-muted";
  return (
    <div className="rounded-lg border border-warning/35 bg-warning/[0.07] p-3 text-sm leading-6 text-prose">
      <p className="font-semibold text-foreground">Answers in the page are not available right now</p>
      <p className="mt-1">Search still works, and your own assistant can read these docs.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className={action} onClick={() => setOpenSearch(true)}>
          <Search className="size-3.5" aria-hidden="true" />
          Search the docs
        </button>
        {question &&
          handOff(question).map(([label, href]) => (
            <a key={label} href={href} target="_blank" rel="noreferrer" className={action}>
              {label}
              <ExternalLink className="size-3.5 text-muted-foreground" aria-hidden="true" />
            </a>
          ))}
      </div>
      {process.env.NODE_ENV === "development" && (
        <p className="mt-3 border-t border-warning/25 pt-2 text-[13px] leading-5 text-muted-foreground">
          For the person running this site: {reason ?? "the assistant did not respond."} Start the site with{" "}
          <code className="font-mono text-foreground">pnpm dev</code>, which also starts <code className="font-mono text-foreground">scripts/assistant.mjs</code>.
        </p>
      )}
    </div>
  );
}

function Sources({ sources }: { sources: Source[] }) {
  return (
    <div className="mt-3 border-t pt-2.5">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Written from</p>
      <ol className="mt-1.5 grid gap-0.5">
        {sources.map((source, i) => (
          <li key={source.url}>
            <Link href={source.url} className="group flex items-baseline gap-2 rounded-md px-1.5 py-1 text-sm leading-5 transition-colors hover:bg-muted">
              <span className="font-mono text-[11px] text-muted-foreground">{i + 1}</span>
              <span className="min-w-0">
                <span className="text-foreground group-hover:text-link">{source.title}</span>
                {source.heading && <span className="text-muted-foreground"> · {source.heading}</span>}
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </div>
  );
}

function CopyAnswer({ text }: { text: string }) {
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
    <button type="button" onClick={copy} className="mt-2 inline-flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
      {copied ? <Check className="size-3.5 text-success" aria-hidden="true" /> : <Copy className="size-3.5" aria-hidden="true" />}
      <span aria-live="polite">{copied ? "Copied" : "Copy answer"}</span>
    </button>
  );
}

function Answer({ message, question, onRetry }: { message: Message; question?: string; onRetry: () => void }) {
  if (message.state === "offline") return <Offline question={question} reason={message.error} />;
  return (
    <div>
      {message.content ? (
        <Markdown text={message.content} />
      ) : message.state === "writing" ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="flex gap-1" aria-hidden="true">
            {[0, 150, 300].map((delay) => (
              <span key={delay} className="size-1.5 animate-pulse rounded-full bg-current" style={{ animationDelay: `${delay}ms` }} />
            ))}
          </span>
          Reading the docs
        </p>
      ) : null}
      {message.state === "failed" && (
        <div className="mt-2 rounded-lg border border-destructive/30 bg-destructive/[0.07] p-3 text-sm leading-6 text-prose">
          <p>{message.error}</p>
          <button type="button" onClick={onRetry} className="mt-2 inline-flex h-8 items-center gap-1.5 rounded-md border bg-background px-2.5 text-sm font-medium text-foreground hover:bg-muted">
            <RotateCcw className="size-3.5" aria-hidden="true" />
            Ask again
          </button>
        </div>
      )}
      {message.sources && message.sources.length > 0 && message.state !== "failed" && <Sources sources={message.sources} />}
      {message.state === "done" && message.content && <CopyAnswer text={message.content} />}
    </div>
  );
}

/** The assistant: a conversation about the docs, in the right column on a wide screen and over the page on a narrow one. */
export function AssistantPanel() {
  const { open, setOpen, messages, busy, health, send, stop, reset } = useAssistant();
  const pathname = usePathname();
  const [draft, setDraft] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true); // the reader is at the end of the conversation, so new words should stay in view

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  useEffect(() => {
    const el = scroller.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  function submit() {
    if (!draft.trim() || busy) return;
    pinned.current = true;
    send(draft);
    setDraft("");
    if (input.current) input.current.style.height = "auto";
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  function retry(index: number) {
    const question = messages.slice(0, index).findLast((m) => m.role === "user");
    if (question) send(question.content);
  }

  const onDocsPage = pathname !== "/";
  const unavailable = health !== null && !health.ok;

  return (
    <div
      className="flex size-full flex-col"
      onKeyDown={(e) => {
        if (e.key === "Escape") setOpen(false);
      }}
    >
      <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
        <Sparkles className="size-4 text-link" aria-hidden="true" />
        <h2 className="font-heading text-sm font-semibold text-foreground">Ask AI</h2>
        <div className="ml-auto flex items-center gap-0.5">
          <button type="button" className={iconButton} onClick={reset} disabled={messages.length === 0} aria-label="Start a new conversation" title="New conversation">
            <SquarePen className="size-4" aria-hidden="true" />
          </button>
          <button type="button" className={iconButton} onClick={() => setOpen(false)} aria-label="Close Ask AI" title="Close (Esc)">
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>
      </div>

      <div
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget;
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
        }}
        className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4"
        aria-live="polite"
        aria-busy={busy}
      >
        {messages.length === 0 ? (
          <div>
            <p className="font-heading text-base font-semibold text-foreground">Ask about Rehearsal</p>
            <p className="mt-1 text-sm leading-6 text-muted-foreground">
              Answers are written from these docs, and each one lists the pages it came from.
            </p>
            {unavailable ? (
              <div className="mt-4">
                <Offline reason={health?.reason} />
              </div>
            ) : (
              <div className="mt-4 grid gap-2">
                {onDocsPage && <AskChip question="Summarise the page I am reading, in a few points.">Summarise this page</AskChip>}
                {STARTERS.map((question) => (
                  <AskChip key={question} question={question} />
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="grid gap-5">
            {messages.map((message, i) =>
              message.role === "user" ? (
                <p key={message.id} className="ml-8 justify-self-end whitespace-pre-wrap rounded-2xl rounded-br-md bg-muted px-3 py-2 text-[0.9375rem] leading-6 text-foreground [overflow-wrap:anywhere]">
                  {message.content}
                </p>
              ) : (
                <Answer key={message.id} message={message} question={messages[i - 1]?.content} onRetry={() => retry(i)} />
              ),
            )}
          </div>
        )}
      </div>

      <div className="shrink-0 border-t p-3">
        <div className="flex items-end gap-2 rounded-xl border bg-background p-1.5 pl-3 transition-colors focus-within:border-ring">
          <textarea
            ref={input}
            value={draft}
            rows={1}
            maxLength={2000}
            placeholder="Ask a question…"
            aria-label="Your question"
            onChange={(e) => {
              setDraft(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 144)}px`;
            }}
            onKeyDown={onKeyDown}
            className="max-h-36 min-h-8 flex-1 resize-none bg-transparent py-1.5 text-[0.9375rem] leading-5 text-foreground outline-none placeholder:text-muted-foreground"
          />
          {busy ? (
            <button type="button" onClick={stop} aria-label="Stop writing" title="Stop" className="grid size-8 shrink-0 place-items-center rounded-lg bg-muted text-foreground transition-colors hover:bg-accent">
              <Square className="size-3 fill-current" aria-hidden="true" />
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!draft.trim()}
              aria-label="Send question"
              className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:bg-muted disabled:text-muted-foreground"
            >
              <ArrowUp className="size-4" aria-hidden="true" />
            </button>
          )}
        </div>
        <p className="mt-2 px-1 text-[11px] leading-4 text-muted-foreground">
          AI answers can be wrong. Check the pages an answer lists.
          {health?.ok && health.model && <span title="The model that writes the answers"> Model: {health.model}.</span>}
        </p>
      </div>
    </div>
  );
}
