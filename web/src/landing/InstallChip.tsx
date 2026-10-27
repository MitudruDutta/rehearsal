"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

function useCopy() {
  const [done, setDone] = useState(false);
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    } catch {
      /* clipboard needs https or localhost; the command stays visible to copy by hand */
    }
  };
  return { done, copy };
}

export function InstallChip({ command = "pip install rehearsal-kit" }: { command?: string }) {
  const { done, copy } = useCopy();
  return (
    <button
      type="button"
      onClick={() => copy(command)}
      className="group inline-flex items-center gap-3 rounded-lg border bg-card/80 px-3.5 py-2 font-mono text-sm text-muted-foreground backdrop-blur-md transition-colors hover:text-foreground"
      aria-label={`Copy: ${command}`}
    >
      <span className="text-primary">$</span>
      {command}
      {done ? <Check className="size-4 text-success" /> : <Copy className="size-4 opacity-60 group-hover:opacity-100" />}
    </button>
  );
}

// The same package for both languages: rehearsal-kit on PyPI (Python) and on npm (TypeScript).
const MANAGERS = [
  { name: "pip", command: "pip install rehearsal-kit" },
  { name: "npm", command: "npm install rehearsal-kit" },
  { name: "pnpm", command: "pnpm add rehearsal-kit" },
  { name: "bun", command: "bun add rehearsal-kit" },
] as const;

/** The install command, with a switch for the package manager. The command area keeps the width of the longest
 * command, so switching never moves the buttons beside it. */
export function InstallPicker() {
  const [picked, setPicked] = useState(0);
  const { done, copy } = useCopy();
  const { command } = MANAGERS[picked];
  return (
    <div className="inline-flex max-w-full flex-col items-stretch overflow-hidden rounded-lg border bg-card/80 font-mono text-sm backdrop-blur-md sm:flex-row sm:items-center">
      <div role="group" aria-label="Package manager" className="flex border-b sm:border-r sm:border-b-0">
        {MANAGERS.map((m, i) => (
          <button
            key={m.name}
            type="button"
            aria-pressed={i === picked}
            onClick={() => setPicked(i)}
            className="flex-1 px-3 py-2 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring aria-pressed:bg-foreground/10 aria-pressed:text-foreground"
          >
            {m.name}
          </button>
        ))}
      </div>
      <button
        type="button"
        onClick={() => copy(command)}
        className="group flex items-center gap-3 px-3.5 py-2 text-left text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
        aria-label={`Copy: ${command}`}
      >
        <span className="text-primary">$</span>
        <span className="min-w-[25ch] whitespace-nowrap">{command}</span>
        {done ? <Check className="size-4 shrink-0 text-success" /> : <Copy className="size-4 shrink-0 opacity-60 group-hover:opacity-100" />}
      </button>
    </div>
  );
}
