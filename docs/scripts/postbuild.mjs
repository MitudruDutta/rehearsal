// Runs after `next build`, on the exported site in out/.
//
//   1. Copies each page's Markdown from out/raw/<page>.md to out/<page>.md, so a page is served at its own
//      address with .md added (the route that writes them cannot share a path with the page itself).
//   2. Checks every internal link and anchor in the exported pages, and that llms.txt lists every page.
//
// It exits with 1 when a link is broken, so a build with a dead link does not ship.
import { cpSync, existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const out = resolve(dirname(fileURLToPath(import.meta.url)), "..", "out");
if (!existsSync(out)) {
  console.error("postbuild: out/ does not exist. Run `next build` first.");
  process.exit(1);
}

function walk(dir, test, found = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name !== "_next") walk(path, test, found);
    } else if (test(path)) found.push(path);
  }
  return found;
}

// ---- 1. Markdown at each page's own address
const raw = join(out, "raw");
const markdown = existsSync(raw) ? walk(raw, (p) => p.endsWith(".md")) : [];
for (const file of markdown) cpSync(file, join(out, relative(raw, file)));

// ---- 2. Links
const pages = walk(out, (p) => p.endsWith(".html"));
const address = (file) => {
  const path = "/" + relative(out, file).replaceAll("\\", "/").replace(/\.html$/, "");
  return path === "/index" ? "/" : path;
};
const html = new Map(pages.map((file) => [address(file), readFileSync(file, "utf8")]));
const ids = new Map([...html].map(([path, text]) => [path, new Set([...text.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]))]));
const exists = (path) => html.has(path) || existsSync(join(out, path));

const broken = [];
for (const [page, text] of html) {
  if (page === "/404" || page === "/_not-found") continue;
  for (const [, href] of text.matchAll(/<a\b[^>]*\shref="([^"]+)"/g)) {
    if (/^(https?:|mailto:|tel:)/.test(href)) continue;
    const [pathPart, hash] = href.replaceAll("&amp;", "&").split("#");
    const target = pathPart === "" ? page : pathPart.length > 1 ? pathPart.replace(/\/$/, "") : pathPart;
    if (!target.startsWith("/")) {
      broken.push(`${page}: the link "${href}" is relative; write it from the site root`);
    } else if (!exists(target)) {
      broken.push(`${page}: "${href}" leads to a page that does not exist`);
    } else if (hash && html.has(target) && !ids.get(target).has(decodeURIComponent(hash))) {
      broken.push(`${page}: "${href}" names a heading that is not on that page`);
    }
  }
}

const docs = [...html.keys()].filter((p) => !["/", "/404", "/_not-found"].includes(p));
const index = readFileSync(join(out, "llms.txt"), "utf8");
for (const page of docs) {
  if (!index.includes(`${page}.md)`)) broken.push(`llms.txt does not list ${page}`);
  if (!existsSync(join(out, `${page}.md`))) broken.push(`${page}.md was not written`);
}

if (broken.length) {
  console.error(`postbuild: ${broken.length} problem${broken.length === 1 ? "" : "s"}\n  ` + [...new Set(broken)].join("\n  "));
  process.exit(1);
}
console.log(`postbuild: ${markdown.length} Markdown pages copied; ${docs.length} pages checked, every internal link and anchor resolves.`);
