import { DocsShell } from "@/components/docs-shell";
import { NotFoundBody } from "@/components/not-found-body";
import { source } from "@/lib/source";

/** The page a static host serves for an unknown address (404.html). It is outside the docs layout, so it brings its own. */
export default function NotFound() {
  return (
    <DocsShell tree={source.getPageTree()}>
      <NotFoundBody />
    </DocsShell>
  );
}
