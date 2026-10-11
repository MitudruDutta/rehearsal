"use client";

import { type ReactNode, useEffect } from "react";
import { ArrowUpRight, Search, Sparkles } from "lucide-react";
import { useSearchContext } from "fumadocs-ui/contexts/search";
import { site } from "@/lib/site";
import { AskAiButton } from "./assistant/buttons";
import { useAssistant } from "./assistant/context";
import { Logo } from "./logo";
import { ThemeToggle } from "./theme-toggle";

function GitHubMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className={className}>
      <path d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.36-3.88-1.36-.52-1.33-1.28-1.69-1.28-1.69-1.05-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.78 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.38-5.25 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5Z" />
    </svg>
  );
}

/** Opens search with "/", as well as the Ctrl K and ⌘K that the search provider already handles. */
function useSlashToSearch() {
  const { setOpenSearch } = useSearchContext();
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      const el = e.target as HTMLElement | null;
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      e.preventDefault();
      setOpenSearch(true);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpenSearch]);
}

export function SearchField({ className = "", label = "Search the docs" }: { className?: string; label?: string }) {
  const { setOpenSearch } = useSearchContext();
  return (
    <button
      type="button"
      aria-keyshortcuts="Control+K Meta+K /"
      onClick={() => setOpenSearch(true)}
      className={`flex h-9 items-center gap-2.5 rounded-lg border bg-muted/60 px-3 text-sm text-muted-foreground transition-colors hover:border-input hover:text-foreground ${className}`}
    >
      <Search className="size-4 shrink-0" aria-hidden="true" />
      <span className="flex-1 truncate text-start">{label}</span>
      <kbd className="hidden rounded border bg-background px-1.5 font-mono text-[11px] leading-5 sm:inline">Ctrl K</kbd>
    </button>
  );
}

const iconButton = "grid size-9 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground";

/**
 * The one header of the site, 56 px high. The logo sits over the sidebar, search and Ask AI are in the middle of the
 * window, and the version, the theme switch, the source link and the console button are at the end. `menu` is the
 * button that opens the sidebar on a narrow screen.
 */
export function SiteHeader({ menu, className = "" }: { menu?: ReactNode; className?: string }) {
  const { setOpenSearch } = useSearchContext();
  const assistant = useAssistant();
  useSlashToSearch();
  return (
    <header className={`z-30 h-14 border-b bg-background/85 backdrop-blur-md ${className}`}>
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-2.5 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-1.5 focus:text-sm focus:font-medium focus:text-primary-foreground"
      >
        Skip to content
      </a>
      {/* three zones: the middle one is in the middle of the window whenever the outer two fit beside it */}
      <div className="flex h-full items-center gap-3 px-4 md:grid md:grid-cols-[minmax(max-content,1fr)_minmax(0,36rem)_minmax(max-content,1fr)] md:gap-4">
        <Logo />

        <div className="hidden items-center gap-2 md:flex">
          <SearchField className="min-w-0 flex-1" />
          <AskAiButton className="max-lg:px-2.5 max-lg:[&_[data-label]]:hidden" />
        </div>

        <div className="ml-auto flex items-center gap-1 md:ml-0 md:justify-end">
          <button type="button" aria-label="Search the docs" onClick={() => setOpenSearch(true)} className={`${iconButton} md:hidden`}>
            <Search className="size-[18px]" aria-hidden="true" />
          </button>
          <button type="button" aria-label="Ask AI" aria-expanded={assistant.open} onClick={() => assistant.setOpen(!assistant.open)} className={`${iconButton} md:hidden`}>
            <Sparkles className="size-[18px] text-link" aria-hidden="true" />
          </button>
          <span
            title={`These pages describe rehearsal-kit ${site.version}`}
            className="mx-1 hidden rounded-md border px-1.5 py-0.5 font-mono text-xs text-muted-foreground xl:inline"
          >
            v{site.version}
          </span>
          <ThemeToggle />
          <a href={site.repo} target="_blank" rel="noreferrer" aria-label="Source code on GitHub" className={`${iconButton} max-lg:hidden`}>
            <GitHubMark className="size-[18px]" />
          </a>
          <a
            href={`${site.consoleUrl}/app/`}
            className="ml-1 hidden h-9 items-center gap-1 whitespace-nowrap rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 lg:flex"
          >
            Open console
            <ArrowUpRight className="size-4" aria-hidden="true" />
          </a>
          {menu}
        </div>
      </div>
    </header>
  );
}
