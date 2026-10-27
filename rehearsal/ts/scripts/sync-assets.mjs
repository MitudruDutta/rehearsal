// Copies the assets the TypeScript package shares with the Python package (the application catalog and the
// Rehearsal skill) and the licence from their one source, so both packages ship the same files.
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const source = [join(root, "../py/rehearsal/assets"), join(root, "../assets")].find((p) => existsSync(join(p, "catalog.yaml")));
if (!source) throw new Error("cannot find the shared assets (catalog.yaml) next to the TypeScript package");
rmSync(join(root, "assets"), { recursive: true, force: true });
mkdirSync(join(root, "assets"), { recursive: true });
cpSync(join(source, "catalog.yaml"), join(root, "assets/catalog.yaml"));
cpSync(join(source, "skill"), join(root, "assets/skill"), { recursive: true });
const license = [join(root, "../py/LICENSE"), join(root, "../../LICENSE")].find((p) => existsSync(p));
if (license) cpSync(license, join(root, "LICENSE"));
console.log(`assets copied from ${source}`);
