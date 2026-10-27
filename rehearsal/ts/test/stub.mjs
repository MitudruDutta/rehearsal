// A stand-in Rehearsal server for the tests: routes map "METHOD /path" to a handler; every request is recorded.
import { createServer } from "node:http";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export async function stub(routes) {
  const requests = [];
  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const c of req) chunks.push(c);
    const raw = Buffer.concat(chunks);
    const url = new URL(req.url, "http://stub");
    let body = null;
    try { body = JSON.parse(raw.toString()); } catch { body = raw.length ? raw.toString("latin1") : null; }
    const seen = { method: req.method, path: url.pathname, query: Object.fromEntries(url.searchParams), headers: req.headers, body };
    requests.push(seen);
    const handler = routes[`${req.method} ${url.pathname}`];
    if (!handler) { res.writeHead(404, { "Content-Type": "application/json" }); return res.end(JSON.stringify({ detail: `no route ${req.method} ${url.pathname}` })); }
    const out = await handler(seen, res);
    if (out === undefined) return; // the handler wrote the response itself
    const [status, payload] = Array.isArray(out) && typeof out[0] === "number" ? out : [200, out];
    res.writeHead(status, { "Content-Type": "application/json" });
    res.end(JSON.stringify(payload));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const url = `http://127.0.0.1:${server.address().port}`;
  return { url, requests, close: () => new Promise((r) => { server.closeAllConnections(); server.close(r); }) };
}

export const tempDir = () => mkdtempSync(join(tmpdir(), "rehearsal-ts-"));

/** The Python package's source of a module, where the repository has it (before or after the py/ split). */
export function pythonSource(rel) {
  for (const base of [new URL("../../py/rehearsal/", import.meta.url), new URL("../../", import.meta.url)]) {
    const path = new URL(rel, base);
    if (existsSync(path)) return readFileSync(path, "utf8");
  }
  return null;
}
