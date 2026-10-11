"use client";

import { Menu } from "lucide-react";
import { useNotebookLayout } from "fumadocs-ui/layouts/notebook";
import { SiteHeader } from "./site-header";

/** The site header in its place in the layout. On a narrow screen its menu button opens the sidebar. */
export function DocsHeader() {
  const { slots } = useNotebookLayout();
  const Trigger = slots.sidebar.trigger;
  return (
    <SiteHeader
      // Across the whole window, also where the layout itself is narrower than the window. Its own width must not
      // count when the layout sizes its columns, or the two outer columns grow to hold it and squeeze the page.
      className="sticky top-(--fd-docs-row-1) col-span-full row-start-1 [contain:inline-size] layout:[--fd-header-height:--spacing(14)]"
      menu={
        <Trigger
          aria-label="Open navigation"
          className="grid size-9 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground md:hidden"
        >
          <Menu className="size-5" aria-hidden="true" />
        </Trigger>
      }
    />
  );
}
