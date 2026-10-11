import { DocsShell } from "@/components/docs-shell";
import { source } from "@/lib/source";

/** Every page, the home page included: the header, the sidebar with all six sections, and the page. */
export default function Layout({ children }: LayoutProps<"/">) {
  return <DocsShell tree={source.getPageTree()}>{children}</DocsShell>;
}
