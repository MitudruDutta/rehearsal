import product from "./generated/product.json";

/** Facts about the site that several components need. Addresses come from the environment at build time. */
export const site = {
  name: "Rehearsal",
  tagline: "Test your AI agent on a copy of your real application.",
  /** the product version the site describes, read from pyproject.toml by scripts/generate_reference.py */
  version: product.version,
  repo: "https://github.com/MitudruDutta/rehearsal",
  /** where the page sources live in the repository, for "Edit this page" */
  editBase: "https://github.com/MitudruDutta/rehearsal/edit/main/docs/content",
  /** the address this site is published at, used in llms.txt and link previews */
  url: (process.env.NEXT_PUBLIC_DOCS_SITE_URL || "http://localhost:3000").replace(/\/$/, ""),
  /** the server's address: the hosted one, or your own. "Open console" goes to its /app/ (the dashboard, or sign-in) */
  consoleUrl: (process.env.NEXT_PUBLIC_CONSOLE_URL || "http://localhost:7800").replace(/\/$/, ""),
  /** where "Ask AI" sends questions: the address of scripts/assistant.mjs. Empty means no answers in the page */
  assistantUrl: (process.env.NEXT_PUBLIC_ASSISTANT_URL || "").replace(/\/$/, ""),
};

export type Section = { title: string; url: string; blurb: string };

/** The six sections, in sidebar order. `url` is also the folder under content/, where meta.json sets the icon. */
export const sections: Section[] = [
  { title: "Get started", url: "/get-started", blurb: "What Rehearsal is and a first result in ten minutes." },
  { title: "Guides", url: "/guides", blurb: "One task on each page, from adding an application to comparing agents." },
  { title: "AI assistants", url: "/ai-assistants", blurb: "Drive Rehearsal from Claude Code, Codex, Cursor and others." },
  { title: "Reference", url: "/reference", blurb: "Every command, tool, error and limit, generated from the code." },
  { title: "Self-hosting", url: "/self-hosting", blurb: "Run the server, workers and sandboxes yourself." },
  { title: "Plans and trust", url: "/plans-and-trust", blurb: "What the product touches, and what each plan allows." },
];
