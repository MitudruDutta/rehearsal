"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

/** Copies `text` and says so for a moment. */
export function CopyButton({ text, label = "Copy", className = "" }: { text: string; label?: string; className?: string }) {
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
      className={`inline-flex h-7 items-center gap-1.5 rounded-md border bg-background px-2 text-xs font-medium text-muted-foreground transition-colors hover:border-input hover:text-foreground ${className}`}
    >
      {copied ? <Check className="size-3.5 text-success" aria-hidden="true" /> : <Copy className="size-3.5" aria-hidden="true" />}
      <span aria-live="polite">{copied ? "Copied" : label}</span>
    </button>
  );
}
