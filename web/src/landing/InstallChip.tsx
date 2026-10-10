"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

export function InstallChip({ command = "pip install rehearsal-kit" }: { command?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(command);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          /* clipboard needs https or localhost; the command stays visible to copy by hand */
        }
      }}
      className="group inline-flex items-center gap-3 rounded-lg border bg-card/80 px-3.5 py-2 font-mono text-sm text-muted-foreground transition-colors hover:text-foreground"
      aria-label={`Copy: ${command}`}
    >
      <span className="text-primary">$</span>
      {command}
      {done ? <Check className="size-4 text-success" /> : <Copy className="size-4 opacity-60 group-hover:opacity-100" />}
    </button>
  );
}
