// The `rehearsal` command is dist/sdk/cli.js; npm links it on install, and a local run needs it executable.
import { chmodSync } from "node:fs";
chmodSync(new URL("../dist/sdk/cli.js", import.meta.url), 0o755);
