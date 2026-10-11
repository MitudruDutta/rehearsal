"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

const LOOK = {
  quiet: "h-7 gap-1.5 rounded-md border bg-background px-2 text-xs text-muted-foreground hover:border-input hover:text-foreground",
  primary: "h-9 gap-2 rounded-lg bg-primary px-3.5 text-sm text-primary-foreground hover:bg-primary/90",
};

/** Copies `text` and says so for a moment. */
export function CopyButton({ text, label = "Copy", className = "", look = "quiet" }: { text: string; label?: string; className?: string; look?: keyof typeof LOOK }) {
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
    <button
      type="button"
      onClick={copy}
      className={`inline-flex shrink-0 items-center font-medium transition-colors ${LOOK[look]} ${className}`}
    >
      {copied ? <Check className={`size-3.5 ${look === "quiet" ? "text-success" : ""}`} aria-hidden="true" /> : <Copy className="size-3.5" aria-hidden="true" />}
      <span aria-live="polite">{copied ? "Copied" : label}</span>
    </button>
  );
}
