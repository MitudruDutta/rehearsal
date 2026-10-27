// Every TypeScript sample in the documentation must type-check against this package, so a page cannot show a method,
// an argument or a field shape that the package does not have.
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const pkg = fileURLToPath(new URL("..", import.meta.url));
const repo = join(pkg, "..", "..");
const docs = join(repo, "docs", "content");
// Other pages with TypeScript samples: the READMEs and the agent skill that both packages ship.
const EXTRA = ["README.md", "PACKAGE.md", "rehearsal/ts/README.md", "rehearsal/assets/skill/references/bring-your-own-agent.md", "rehearsal/py/rehearsal/assets/skill/references/bring-your-own-agent.md"];
// Names the samples use without defining them: ids and results from earlier steps of the same page.
const GIVEN = { rh: "RehearsalClient", run: "any", agent: "any", summary: "any",
                myAgentDecide: "(history: unknown[], tools: unknown[]) => Promise<[string, Record<string, unknown>]>" };
const ID = "string";

function* mdx(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) yield* mdx(join(dir, entry.name));
    else if (entry.name.endsWith(".mdx")) yield join(dir, entry.name);
  }
}

test("the documentation's TypeScript samples type-check against the package", (t) => {
  if (!existsSync(docs)) return t.skip("the documentation is not in this checkout");
  const out = join(pkg, "test", ".samples");
  rmSync(out, { recursive: true, force: true });
  mkdirSync(out, { recursive: true });
  const files = [];
  for (const page of [...mdx(docs), ...EXTRA.map((f) => join(repo, f)).filter(existsSync)]) {
    for (const [i, m] of [...readFileSync(page, "utf8").matchAll(/^```ts\n([\s\S]*?)^```/gm)].entries()) {
      const sample = m[1];
      const defined = new Set([...sample.matchAll(/\b(?:const|let|import)\s+\{?\s*([\w\s,]+?)\s*\}?\s*(?:=|from)/g)].flatMap((d) => d[1].split(",").map((x) => x.trim())));
      const used = new Set([...sample.matchAll(/\b([A-Za-z]\w*)\b/g)].map((u) => u[1]));
      const free = [...used].filter((n) => !defined.has(n) && (n in GIVEN || /(Id|^run[AB])$/.test(n) || /^[A-Z][A-Z_]+_ID$/.test(n)));
      const prelude = [
        'import type { Rehearsal as RehearsalClient } from "rehearsal-kit";',
        ...free.map((n) => `declare const ${n}: ${GIVEN[n] ?? ID};`),
        ...(/readFileSync/.test(sample) && !/import .*readFileSync/.test(sample) ? ['import { readFileSync } from "node:fs";'] : []),
      ];
      const name = `${page.slice(repo.length + 1).replace(/[/\\.]/g, "_")}_${i}.mts`;
      writeFileSync(join(out, name), prelude.join("\n") + "\n" + sample + "\nexport {};\n");
      files.push(name);
    }
  }
  assert.ok(files.length > 10, `found only ${files.length} samples`);
  writeFileSync(join(out, "tsconfig.json"), JSON.stringify({
    compilerOptions: { target: "ES2022", module: "NodeNext", moduleResolution: "NodeNext", strict: true, noEmit: true, skipLibCheck: true,
                       types: ["node"], typeRoots: [join(pkg, "node_modules", "@types")] },
    include: ["*.mts"],
  }));
  try {
    execFileSync(process.execPath, [join(pkg, "node_modules", "typescript", "bin", "tsc"), "-p", join(out, "tsconfig.json")], { encoding: "utf8" });
  } catch (e) {
    assert.fail(`documentation samples do not type-check:\n${e.stdout}`);
  }
  rmSync(out, { recursive: true, force: true });
});
