"use client";

import Link from "next/link";
import { useStaticSearch } from "fumadocs-core/search/client";
import {
  SearchDialog,
  SearchDialogClose,
  SearchDialogContent,
  SearchDialogFooter,
  SearchDialogHeader,
  SearchDialogIcon,
  SearchDialogInput,
  SearchDialogList,
  SearchDialogOverlay,
  type SharedProps,
} from "fumadocs-ui/components/dialog/search";

/** Shown before the reader types, and offered again when a search finds nothing. */
const START: [string, string][] = [
  ["Quickstart: console", "/get-started/quickstart-console"],
  ["Quickstart: CLI and Python", "/get-started/quickstart-cli"],
  ["How scoring works", "/get-started/how-scoring-works"],
  ["Troubleshooting", "/self-hosting/troubleshooting"],
];

function NoResults() {
  return (
    <div className="px-4 py-6 text-sm">
      <p className="font-medium text-foreground">No page matches that.</p>
      <p className="mt-1 text-muted-foreground">
        If you pasted an error message, try a shorter part of it. These pages answer most questions:
      </p>
      <ul className="mt-3 grid gap-1">
        {START.map(([name, href]) => (
          <li key={href}>
            <Link href={href} className="text-link underline-offset-2 hover:underline">
              {name}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Site search. The index is one static file (/api/search) that the browser downloads the first time search is
 * used, so search works with no server and costs nothing until it is opened.
 */
export default function StaticSearchDialog(props: SharedProps) {
  const search = useStaticSearch({ from: "/api/search" });
  return (
    <SearchDialog
      search={search.search}
      onSearchChange={search.onSearchChange}
      isLoading={search.isLoading}
      data={search.data}
      {...props}
    >
      <SearchDialogOverlay />
      <SearchDialogContent>
        <SearchDialogHeader>
          <SearchDialogIcon />
          <SearchDialogInput placeholder="Search, or paste an error message" />
          <SearchDialogClose />
        </SearchDialogHeader>
        <SearchDialogList
          defaultItems={START.map(([name, url]) => ({ type: "page" as const, id: url, content: name, url }))}
          Empty={NoResults}
        />
        <SearchDialogFooter className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>
            <kbd className="rounded border px-1 font-mono">↑</kbd> <kbd className="rounded border px-1 font-mono">↓</kbd> to move
          </span>
          <span>
            <kbd className="rounded border px-1 font-mono">Enter</kbd> to open
          </span>
          <span>
            <kbd className="rounded border px-1 font-mono">Esc</kbd> to close
          </span>
        </SearchDialogFooter>
      </SearchDialogContent>
    </SearchDialog>
  );
}
