"use client";

import type { ReactNode } from "react";
import { Sparkles } from "lucide-react";
import { useAssistant } from "./context";

/** Opens and closes the assistant panel. In the header beside search, and on the home page. */
export function AskAiButton({ className = "", label = "Ask AI" }: { className?: string; label?: string }) {
  const { open, setOpen } = useAssistant();
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-keyshortcuts="Control+I Meta+I"
      title="Ask AI about these docs (Ctrl I)"
      onClick={() => setOpen(!open)}
      className={`group inline-flex h-9 shrink-0 items-center gap-2 whitespace-nowrap rounded-lg border bg-muted/60 px-3 text-sm font-medium text-foreground transition-colors hover:border-primary/60 hover:bg-accent aria-expanded:border-primary/60 aria-expanded:bg-accent ${className}`}
    >
      <Sparkles className="size-4 text-link transition-transform group-hover:scale-110" aria-hidden="true" />
      <span data-label="">{label}</span>
    </button>
  );
}

/** A question the reader can ask with one click. */
export function AskChip({ question, children, className = "" }: { question: string; children?: ReactNode; className?: string }) {
  const { ask, busy } = useAssistant();
  return (
    <button
      type="button"
      disabled={busy}
      onClick={() => ask(question)}
      className={`rounded-lg border bg-card px-3 py-2 text-start text-sm leading-5 text-prose transition-colors hover:border-primary/50 hover:bg-accent/40 hover:text-foreground disabled:opacity-60 ${className}`}
    >
      {children ?? question}
    </button>
  );
}
