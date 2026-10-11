"use client";

import { Moon, Sun } from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { PixelBackdrop } from "@/landing/PixelBackdrop";

/* The frame shared by sign-in, sign-up and first-run setup. The work is on the left, in one narrow column in the
   middle of its half, under the logo and nothing else. The right half is a picture, drawn in blocks that scatter
   under the cursor as on the landing page, with no words over it. A person who signs up therefore stays in one
   place from the first field to the console: only the left half changes. Under 1024 px the picture is left out
   and the work takes the whole window. */

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const dark = resolvedTheme !== "light";
  return (
    <Button variant="ghost" size="icon-sm" className="text-muted-foreground" onClick={() => setTheme(dark ? "light" : "dark")} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"} title={dark ? "Light mode" : "Dark mode"}>
      {dark ? <Sun /> : <Moon />}
    </Button>
  );
}

export function AuthShell({ children, foot }: {
  children: ReactNode;
  /** small print under the work */
  foot?: ReactNode;
}) {
  return (
    <div className="grid min-h-svh bg-background lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="flex min-w-0 flex-col px-6 py-5 sm:px-10 lg:px-12">
        <header className="flex min-h-9 items-center justify-between gap-3">
          <Link href="/" className="-ml-1 flex items-center gap-2.5 rounded-md px-1 py-1 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50" aria-label="Rehearsal home">
            <span className="size-3.5 rotate-45 rounded-[3px] bg-primary" aria-hidden="true" />
            <span className="font-heading text-lg font-bold">Rehearsal</span>
          </Link>
          <ThemeToggle />
        </header>
        <main className="flex flex-1 items-center py-8">
          <div className="mx-auto w-full max-w-[25rem]">{children}</div>
        </main>
        {foot && <footer className="mx-auto w-full max-w-[25rem] text-xs leading-5 text-muted-foreground">{foot}</footer>}
      </div>

      <aside className="hidden p-2.5 lg:block lg:pl-0" aria-hidden="true">
        {/* Held in view while a long step scrolls beside it. The panel clips, and does not hide, so the picture can
            be held too. Its dark ground comes from the "wave" palette, so it looks the same in both themes. */}
        <div className="dark wave sticky top-2.5 h-[calc(100svh-1.25rem)] overflow-clip rounded-[22px]">
          <PixelBackdrop src="/landing/city-walk.webp" focusX={0.5} wash={[0.1, 0.22]} />
        </div>
      </aside>
    </div>
  );
}
