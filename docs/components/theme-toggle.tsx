"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "fumadocs-ui/provider/base";

/** One button that switches between light and dark. The first visit follows the system; the choice is remembered. */
export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  return (
    <button
      type="button"
      aria-label="Switch between light and dark theme"
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      className="grid size-9 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      {/* both icons are in the page; the theme class shows one, so nothing changes after the page loads */}
      <Sun className="size-[18px] dark:hidden" aria-hidden="true" />
      <Moon className="hidden size-[18px] dark:block" aria-hidden="true" />
    </button>
  );
}
