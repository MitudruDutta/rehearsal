# Rehearsal documentation site

The site that users read: quickstarts, guides, reference, self-hosting, and trust. It is a static site, built with
[Fumadocs](https://fumadocs.dev) on Next.js. The requirements are in `handbook/DOCS_PRD.md` and the plan is in
`handbook/DOCS_SITE_PLAN.md`.

## Run it

Use Node.js 22 or later and pnpm. On Windows, run these from Git Bash or PowerShell.

```bash
cd docs
pnpm install
pnpm dev          # http://localhost:3000, reloads when a page changes
```

`pnpm dev` also starts the service that answers "Ask AI" (see [Ask AI](#ask-ai)), on port 4311.

To see the real build, which is what gets published:

```bash
pnpm build        # writes out/, copies each page's Markdown, and checks every internal link
pnpm start        # serves out/ at http://localhost:4310
```

## Where things are

| Path | What |
|---|---|
| `content/<section>/*.mdx` | The pages. One file is one page. The folder is the section |
| `content/<section>/meta.json` | The section's icon, the order of its pages in the sidebar, and the group headings |
| `content/meta.json` | The order of the sections, and the "Overview" row that leads to the home page |
| `app/(docs)/page.tsx` | The home page |
| `components/mdx.tsx` | The components a page can use: `Cost`, `Steps`, `Ways`, `OS`, `Output`, `Verdict`, `PhaseStrip`, ... |
| `components/diagrams.tsx` | The diagrams |
| `components/docs-shell.tsx` | What every page sits in: the header, the sidebar with all six sections, the Ask AI panel |
| `components/site-header.tsx` | The header: search and Ask AI in the middle, then version, theme, console button |
| `components/assistant/` | Ask AI in the browser: the conversation, the panel, and how an answer is drawn |
| `scripts/assistant.mjs` | Ask AI on the server: finds the passages that match a question and asks a model |
| `app/globals.css` | The theme and the layout. Colours and fonts are the console's, copied from `web/src/app/globals.css` |
| `lib/site.ts` | The six sections, and the addresses the site links to |
| `scripts/generate_reference.py` | Writes the reference pages from the product's code |
| `scripts/check_samples.py` | Checks the commands and samples in the pages against the product |
| `scripts/postbuild.mjs` | After a build: Markdown copies, and the link check |

## Write a page

1. Add `content/<section>/<name>.mdx` with this front matter:

   ```mdx
   ---
   title: Evaluate an agent
   description: One or two sentences. It is the line under the title, and the line in search and in llms.txt.
   audience: Agent developers
   last_reviewed: 2026-10-11
   time: 2 to 10 minutes          # guides only: these three make the row under the title
   cost: About $0.02 for each episode
   needs: a published world version
   ---
   ```

2. Add the file's name to `pages` in the section's `meta.json`.
3. Run `pnpm build`. It fails on a broken link or a heading that a link names and the page does not have.

Writing rules, from the plan: short sentences, one idea in each, active voice, instructions as commands ("Open",
"Choose", "Run"), and the console's own words ("world", "job", "episode"). A value the reader must replace is
written `<like_this>`. A step that spends model budget has a `<Cost>` before it. A feature that is not built is not
described, except on `plans-and-trust/not-built-yet.mdx`.

## Generated pages

Seven pages come from the code. Do not edit them: change the code, or the tables in the script, then run it.

```bash
python docs/scripts/generate_reference.py           # from the repository root, with the project's environment
python docs/scripts/generate_reference.py --check   # exit 1 when a page differs from the code
python docs/scripts/check_samples.py                # every `rehearsal ...` command, Python and JSON sample
```

| Page | Comes from |
|---|---|
| `reference/cli.mdx` | The argparse parser in `rehearsal/sdk/cli.py` |
| `reference/api.mdx` | The API schema, and the access rule in `rehearsal/api/auth.py` |
| `reference/python-sdk.mdx` | `rehearsal/sdk/client.py` |
| `reference/configuration.mdx` | Every environment variable the package reads |
| `reference/errors.mdx` | The CLI's hints, and messages that are checked against the files they come from |
| `reference/plans-and-limits.mdx` | `billing.PLANS` |
| `ai-assistants/mcp-tools.mdx` | The tools in `rehearsal/sdk/mcp.py` |

The script reads definitions only. It never reads `.env`, and it never connects to a database. It stops when the
code has a command, an argument, a tool, an operation or a setting that its tables do not describe, so a change in
the product cannot be published without its description. `lib/generated/product.json` holds the version in the
header, which comes from `pyproject.toml`.

## Settings

Set these when you build for publishing. They are read at build time.

| Variable | For | Default |
|---|---|---|
| `NEXT_PUBLIC_DOCS_SITE_URL` | The address the site is published at. Used in `llms.txt` and in link previews | `http://localhost:3000` |
| `NEXT_PUBLIC_CONSOLE_URL` | Where "Open console" goes | `http://localhost:7800` |
| `NEXT_PUBLIC_ASSISTANT_URL` | The address of the Ask AI service. `pnpm dev` sets it for you | Empty: no answers in the page |

The landing page's "Docs" link is set in the console's build, not here: build `web/` with `NEXT_PUBLIC_DOCS_URL`
set to the address of this site.

## Ask AI

The button beside search opens a panel where a reader asks a question and gets an answer written from these
pages, with links to the pages it came from. Ctrl I (or ⌘I) opens it from anywhere.

The site itself is static files, so the answer comes from a small service, `scripts/assistant.mjs`. For each
question it:

1. Finds the passages of `content/` that match the question. A passage is the text under one heading. No index is
   built ahead of time, and a page you edit is read again within a few seconds.
2. Sends those passages, a list of all pages and the conversation to a model, with the instruction to answer from
   them only and to say so when they do not cover the question.
3. Sends the answer to the browser as it is written.

It needs Node.js and no packages. Start it with the site (`pnpm dev`) or alone (`pnpm assistant`).

| Variable | For | Default |
|---|---|---|
| `DOCS_ASSISTANT_MODEL` | The models to ask, in order: `provider:model[,provider:model...]` | The server's `REHEARSAL_MODEL_AGENT` |
| `DOCS_ASSISTANT_PORT` | The port it listens on | `4311` |
| `DOCS_ASSISTANT_HOST` | The address it listens on. Use `0.0.0.0` behind a reverse proxy | `127.0.0.1` |
| `DOCS_ASSISTANT_ORIGINS` | The sites whose pages may ask, separated by commas | The local addresses of the site |
| `DOCS_ASSISTANT_PER_MINUTE` | Questions one address may ask in a minute | `10` |
| `DOCS_ASSISTANT_PER_DAY` | Questions answered in a day, for all readers together | `500` |

It reads these from the environment, then from `docs/.env.local`, then from the server's `.env` in the repository
root. A provider's key has the name the server uses (`NEBIUS_API_KEY`, `OPENROUTER_API_KEY`, and so on), so a
machine that can run the server can answer questions with no more setup. Keys stay in the service: the browser
never receives one.

**Each question costs model budget**: a few thousand tokens in (the passages and the page list) and a few hundred
out. The service prints the size of each question it sends. The two limits above are what stop a stranger from
spending your budget, so set them before you publish the service.

To publish it, run `node scripts/assistant.mjs` on a machine that has the key, put it behind HTTPS, set
`DOCS_ASSISTANT_ORIGINS` to the site's address, and build the site with `NEXT_PUBLIC_ASSISTANT_URL` set to the
service's address. It needs the `content/` folder beside it.

When the site is built without `NEXT_PUBLIC_ASSISTANT_URL`, or the service does not respond, the panel says that
answers are not available and offers search and "Ask Claude" or "Ask ChatGPT", which open the reader's own
assistant with the question and the address of `llms.txt`.

## Publish

`pnpm build` writes plain files to `out/`. Any static host can serve them: point it at `out/`, with clean
addresses on, so that `/guides/evaluate-an-agent` answers from `guides/evaluate-an-agent.html`. Cloudflare Pages and
Vercel do this by default.

The build also writes, for AI assistants:

- `/llms.txt`: every page with one line of description.
- `/llms-full.txt`: every page as Markdown, in one file.
- `<page>.md`: each page as Markdown, at its own address with `.md` added.

## Why some things are the way they are

- **Static export, and no `cacheComponents`.** The site must stay up when the product's servers are down, so it is
  exported as files. The Next.js starter turned on `cacheComponents` and `partialPrefetching`; Next rejects them
  next to the `dynamic = "force-static"` that an export requires on the routes that write files (the search
  index, `llms.txt`, each page's Markdown).
- **Search runs in the browser.** The index is one file, `/api/search`, that the browser downloads the first time
  search is opened. There is no search server and no account.
- **Type rules are scoped to `.rh-prose`.** Fumadocs also puts the class `prose` on small things, such as items of
  the table of contents, which must keep their own size.
- **One sidebar for the whole site.** Every page, the home page included, has the same sidebar with all six
  sections, so a reader always sees where they are and what else exists. A section opens when you are in it.
- **The page width is set on the layout, not on `:root`.** `--rh-column` and `--rh-measure` in `app/globals.css`
  are the width of the page and of a line of text. The build drops a `:root` setting that no theme colour or font
  refers to, so they are set on `#nd-notebook-layout`.
- **Ask AI is a separate service, not part of the site.** The site stays plain files that any host can serve, and
  it works without the service: only answers in the page are missing then.
