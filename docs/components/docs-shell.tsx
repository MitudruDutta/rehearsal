"use client";

import type { ReactNode } from "react";
import type * as PageTree from "fumadocs-core/page-tree";
import { DocsLayout } from "fumadocs-ui/layouts/notebook";
import { AssistantProvider, useAssistant } from "./assistant/context";
import { AssistantPanel } from "./assistant/panel";
import { DocsHeader } from "./docs-header";

/** The sidebar ends with its last section: nothing under the page list, in the sidebar or in the phone drawer. */
function NoSidebarFooter() {
  return null;
}

function Layout({ tree, children }: { tree: PageTree.Root; children: ReactNode }) {
  const assistant = useAssistant();
  return (
    <DocsLayout
      tree={tree}
      nav={{ mode: "top" }}
      // one sidebar holds every section, so there is nothing to switch between
      tabs={false}
      slots={{ header: DocsHeader }}
      sidebar={{ collapsible: false, footer: NoSidebarFooter }}
      themeSwitch={{ enabled: false }}
      searchToggle={{ enabled: false }}
      aiChat={{ open: assistant.open, onOpenChange: assistant.setOpen, panel: <AssistantPanel /> }}
    >
      {children}
    </DocsLayout>
  );
}

/**
 * What every page of the site sits in: the header, the sidebar with all six sections, and the Ask AI panel, which
 * takes the right column when it is open.
 */
export function DocsShell({ tree, children }: { tree: PageTree.Root; children: ReactNode }) {
  return (
    <AssistantProvider>
      <Layout tree={tree}>{children}</Layout>
    </AssistantProvider>
  );
}
