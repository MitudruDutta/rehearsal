import Link from "next/link";
import { AskAiButton } from "./assistant/buttons";
import { SearchField } from "./site-header";

const START: [string, string][] = [
  ["Quickstart: console", "/get-started/quickstart-console"],
  ["Quickstart: CLI and Python", "/get-started/quickstart-cli"],
  ["Quickstart: with an AI assistant", "/get-started/quickstart-ai-assistant"],
  ["Docs home", "/"],
];

/** What an address with no page shows, between the header and the sidebar every page has. */
export function NotFoundBody() {
  return (
    <main id="content" className="min-w-0 [grid-area:main]">
      <div className="mx-auto w-full max-w-2xl px-4 py-16 md:px-8 md:py-20">
        <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">404</p>
        <h1 className="mt-3 font-heading text-4xl font-bold tracking-tight text-foreground">This page does not exist</h1>
        <p className="mt-4 text-lg leading-[1.875rem] text-muted-foreground">
          The page may have moved. Search for it, ask, or start from one of these.
        </p>
        <div className="mt-6 flex gap-2">
          <SearchField className="h-11 min-w-0 flex-1 bg-card px-3.5 text-[0.9375rem]" />
          <AskAiButton className="h-11 bg-card px-4" />
        </div>
        <ul className="mt-8 grid gap-2 text-[0.9375rem]">
          {START.map(([label, href]) => (
            <li key={href}>
              <Link className="text-link underline underline-offset-4" href={href}>
                {label}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </main>
  );
}
