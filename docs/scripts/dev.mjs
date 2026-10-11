// `pnpm dev`: the site with live reload, and beside it the service that answers "Ask AI" (scripts/assistant.mjs).
// Anything after `pnpm dev` goes to `next dev`, for example `pnpm dev -p 3001`.
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { start } from "./assistant.mjs";

const env = { ...process.env };
let assistant = null;
if (!env.NEXT_PUBLIC_ASSISTANT_URL) {
  try {
    assistant = await start();
    env.NEXT_PUBLIC_ASSISTANT_URL = assistant.url;
  } catch (error) {
    // the site is still worth having without it: Ask AI then says that answers are not available
    console.error(`[assistant] not started: ${error.message}`);
  }
}

const next = spawn(process.execPath, [fileURLToPath(new URL("../node_modules/next/dist/bin/next", import.meta.url)), "dev", ...process.argv.slice(2)], { stdio: "inherit", env });
const stop = () => next.kill();
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
next.on("exit", (code) => {
  assistant?.close();
  process.exit(code ?? 0);
});
