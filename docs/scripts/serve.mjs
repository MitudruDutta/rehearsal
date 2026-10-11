// Serves the exported site in out/ the way a static host does: /a/b answers from a/b.html, and an unknown path
// gets 404.html. For a look at the real build on your machine: `pnpm build && pnpm start`, then
// http://localhost:4310. Usage: node scripts/serve.mjs [folder] [port]
import { createServer } from "node:http";
import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(process.argv[2] ?? join(dirname(fileURLToPath(import.meta.url)), "..", "out"));
const port = Number(process.argv[3] || 4310);
const types = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".txt": "text/plain; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
  ".woff2": "font/woff2",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".webp": "image/webp",
};

if (!existsSync(root)) {
  console.error(`${root} does not exist. Run the build first.`);
  process.exit(1);
}

createServer((request, response) => {
  const path = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
  const base = join(root, normalize(path));
  if (!base.startsWith(root)) {
    response.writeHead(403).end();
    return;
  }
  const hit = [base, `${base}.html`, join(base, "index.html")].find((p) => existsSync(p) && statSync(p).isFile());
  const file = hit ?? join(root, "404.html");
  const type = types[extname(file)] ?? (file.endsWith("search") ? "application/json" : "application/octet-stream");
  response.writeHead(hit ? 200 : 404, { "Content-Type": type });
  response.end(readFileSync(file));
}).listen(port, "127.0.0.1", () => console.log(`Serving ${root} at http://localhost:${port}`));
