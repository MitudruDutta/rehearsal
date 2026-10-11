// The service behind "Ask AI". It answers a question about Rehearsal from the pages in content/, and from nothing
// else: it finds the passages that match the question, gives them to a model with the question, and sends the
// answer back as it is written, with the pages it came from.
//
// It needs no packages. `pnpm dev` starts it next to the site; `pnpm assistant` starts it alone.
//
//   GET  /health   { ok, model, reason }      can it answer, and with which model
//   POST /ask      { messages, page }         the conversation so far, and the page the reader is on
//                  answers with a stream of events: sources, delta (a few words), then done or error
//
// Settings, read from the environment, then docs/.env.local, then the server's own .env in the repository root:
//
//   DOCS_ASSISTANT_MODEL        a model chain, "provider:model[,provider:model...]", tried in order. Without it,
//                               the chain the server uses for agents (REHEARSAL_MODEL_AGENT), then the server's default
//   DOCS_ASSISTANT_PORT         4311
//   DOCS_ASSISTANT_HOST         127.0.0.1. Set 0.0.0.0 behind a reverse proxy
//   DOCS_ASSISTANT_ORIGINS      the sites whose pages may ask, separated by commas. Default: the local addresses
//   DOCS_ASSISTANT_PER_MINUTE   questions one address may ask in a minute (10)
//   DOCS_ASSISTANT_PER_DAY      questions answered in a day, for everyone together (500)
//   DOCS_ASSISTANT_BEHIND_PROXY 1 behind a reverse proxy: limit by the visitor address it forwards (X-Forwarded-For)
//
// A provider's key is read under the name the server uses (NEBIUS_API_KEY, OPENROUTER_API_KEY, ...). Keys are
// never printed, and never sent anywhere but to their own provider.
import { createServer } from "node:http";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const docsRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const contentDir = join(docsRoot, "content");

// ---- Settings

/** KEY=VALUE lines, read the way the server reads its .env (rehearsal/config.py). A missing file is empty. */
function dotenv(path) {
  const out = {};
  if (!existsSync(path)) return out;
  for (const raw of readFileSync(path, "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const at = line.indexOf("=");
    out[line.slice(0, at).trim()] = line.slice(at + 1).trim().replace(/^(['"])(.*)\1$/, "$2");
  }
  return out;
}

// the chain the server falls back to when nothing is set, from rehearsal/config.py
const SERVER_DEFAULT_CHAIN = "groq:openai/gpt-oss-120b,openai:gpt-5-mini,anthropic:claude-haiku-4-5,google:gemini-2.5-flash,openrouter:openai/gpt-oss-120b";

export function settings(env = process.env) {
  const files = { ...dotenv(env.REHEARSAL_ENV_FILE ?? resolve(docsRoot, "..", ".env")), ...dotenv(join(docsRoot, ".env.local")) };
  const get = (name) => env[name] || files[name] || "";
  const modal = [get("MODAL_PROXY_TOKEN_ID"), get("MODAL_PROXY_TOKEN_SECRET")];
  // where each provider answers and which key it takes: the same table as PROVIDERS in rehearsal/agents/llm.py
  const providers = {
    nebius: { base: "https://api.tokenfactory.nebius.com/v1", key: get("NEBIUS_API_KEY") },
    openrouter: { base: "https://openrouter.ai/api/v1", key: get("OPENROUTER_API_KEY") },
    groq: { base: "https://api.groq.com/openai/v1", key: get("GROQ_API_KEY") },
    google: { base: "https://generativelanguage.googleapis.com/v1beta/openai", key: get("GOOGLE_API_KEY") },
    openai: { base: "https://api.openai.com/v1", key: get("OPENAI_API_KEY") },
    anthropic: { base: "https://api.anthropic.com/v1", key: get("ANTHROPIC_API_KEY") },
    mistral: { base: "https://api.mistral.ai/v1", key: get("MISTRAL_API_KEY") },
    xai: { base: "https://api.x.ai/v1", key: get("XAI_API_KEY") },
    deepseek: { base: "https://api.deepseek.com/v1", key: get("DEEPSEEK_API_KEY") },
    together: { base: "https://api.together.xyz/v1", key: get("TOGETHER_API_KEY") },
    fireworks: { base: "https://api.fireworks.ai/inference/v1", key: get("FIREWORKS_API_KEY") },
    cerebras: { base: "https://api.cerebras.ai/v1", key: get("CEREBRAS_API_KEY") },
    nvidia: { base: "https://integrate.api.nvidia.com/v1", key: get("NVIDIA_API_KEY") },
    litellm: { base: get("LITELLM_BASE_URL") || "https://litellm.vision.aivar.app/v1", key: get("LITELLM_API_KEY") },
    modal: { base: get("MODAL_BASE_URL"), key: modal[0] && modal[1] ? modal.join(".") : "" },
    local: { base: get("REHEARSAL_LOCAL_BASE_URL") || "http://127.0.0.1:8001/v1", key: get("REHEARSAL_LOCAL_API_KEY") || "local" },
    custom: { base: get("REHEARSAL_CUSTOM_BASE_URL"), key: get("REHEARSAL_CUSTOM_API_KEY") },
  };
  const chain = get("DOCS_ASSISTANT_MODEL") || get("REHEARSAL_MODEL_AGENT") || SERVER_DEFAULT_CHAIN;
  const entries = chain
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const at = part.indexOf(":");
      const [provider, model] = at < 0 ? [part, ""] : [part.slice(0, at), part.slice(at + 1)];
      const known = providers[provider];
      return { name: part, provider, model, base: known?.base.replace(/\/$/, "") ?? "", key: known?.key ?? "", ready: Boolean(known?.base && known?.key && model) };
    });
  const number = (name, fallback) => (Number.isFinite(Number(get(name))) && get(name) !== "" ? Number(get(name)) : fallback);
  return {
    entries,
    usable: entries.filter((e) => e.ready),
    port: number("DOCS_ASSISTANT_PORT", 4311),
    host: get("DOCS_ASSISTANT_HOST") || "127.0.0.1",
    origins: (get("DOCS_ASSISTANT_ORIGINS") || "http://localhost:3000,http://127.0.0.1:3000,http://localhost:4310,http://127.0.0.1:4310")
      .split(",")
      .map((o) => o.trim().replace(/\/$/, ""))
      .filter(Boolean),
    perMinute: number("DOCS_ASSISTANT_PER_MINUTE", 10),
    perDay: number("DOCS_ASSISTANT_PER_DAY", 500),
    // behind a reverse proxy (Caddy) every request comes from the proxy; it adds the visitor's address last to
    // X-Forwarded-For, so the per-address limit uses that. Set only when nothing but the proxy can reach this service.
    behindProxy: get("DOCS_ASSISTANT_BEHIND_PROXY") === "1",
  };
}

// ---- The pages, cut into passages

function walk(dir, found = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, found);
    else if (name.endsWith(".mdx")) found.push(path);
  }
  return found;
}

/** The pages in the order the sidebar shows them, which content/meta.json and each section's meta.json give. */
function inReadingOrder(files) {
  const rank = new Map();
  const list = (file) => {
    try {
      return JSON.parse(readFileSync(file, "utf8")).pages ?? [];
    } catch {
      return [];
    }
  };
  for (const section of list(join(contentDir, "meta.json"))) {
    // a section's own page comes first, also where its meta.json leaves it out because the section row opens it
    for (const page of ["index", ...list(join(contentDir, section, "meta.json"))]) {
      if (!page.startsWith("---") && !rank.has(`${section}/${page}`)) rank.set(`${section}/${page}`, rank.size);
    }
  }
  const key = (file) => relative(contentDir, file).replaceAll("\\", "/").replace(/\.mdx$/, "");
  return [...files].sort((a, b) => (rank.get(key(a)) ?? 1e6) - (rank.get(key(b)) ?? 1e6) || key(a).localeCompare(key(b)));
}

function frontMatter(raw) {
  const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  const meta = {};
  if (match) {
    for (const line of match[1].split(/\r?\n/)) {
      const at = line.indexOf(":");
      if (at > 0 && !line.startsWith(" ")) meta[line.slice(0, at).trim()] = line.slice(at + 1).trim().replace(/^(['"])(.*)\1$/, "$2");
    }
  }
  return { meta, body: match ? raw.slice(match[0].length) : raw };
}

/** A heading as the reader sees it: no Markdown marks, no components. */
function plain(text) {
  return text
    .replace(/\s*\[#[^\]]+\]\s*$/, "")
    .replace(/<[^>]+>/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\\([{}<>_*[\]`#])/g, "$1")
    .trim();
}

/** The id the site gives a heading. Same rule as github-slugger, which the site uses: a second "Next" is "next-1". */
function slugger() {
  const seen = new Map();
  return (text) => {
    const base = text.toLowerCase().trim().replace(/[^\p{L}\p{M}\p{N}\p{Pc}\- ]/gu, "").replace(/ /g, "-");
    let slug = base;
    while (seen.has(slug)) {
      seen.set(base, seen.get(base) + 1);
      slug = `${base}-${seen.get(base)}`;
    }
    seen.set(slug, 0);
    return slug;
  };
}

/** A page's text with its components written out as the words they show, so a model reads what a reader reads. */
function readable(text) {
  return text
    .replace(/<Operation\s+method="([^"]+)"\s+path="([^"]+)"(?:\s+access="([^"]+)")?([^>]*)\/>/g, (_, method, path, access, rest) => `${method} ${path}${access ? ` (needs access: ${access})` : ""}${/\bcosts\b/.test(rest) ? " (costs money)" : ""}`)
    .replace(/<Cost(?:\s+amount="([^"]*)")?\s*>/g, (_, amount) => `Costs money${amount ? `: ${amount}.` : "."}`)
    .replace(/<(Note|Tip|Caution|Danger)(?:\s+title="([^"]*)")?\s*>/g, (_, kind, title) => `${kind === "Danger" ? "Cannot be undone" : kind}${title ? ` (${title})` : ""}:`)
    .replace(/<Output(?:\s+label="([^"]*)")?\s*>/g, (_, label) => `${label ?? "You see"}:`)
    .replace(/<Tab\s+value="([^"]*)"\s*>/g, "[$1]")
    .replace(/<LinkCard\s+href="([^"]*)"\s+title="([^"]*)"\s*>/g, "- [$2]($1): ")
    .replace(/<Verdict\s+is="([^"]*)"\s*\/>/g, (_, is) => is.replaceAll("-", " "))
    .replace(/<Label\s+kind="([^"]*)"\s*\/>/g, (_, kind) => kind.replaceAll("-", " "))
    .replace(/<\/?[A-Z][A-Za-z]*(?:\s[^<>]*?)?\/?>/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

const PASSAGE = 2200; // characters: a passage longer than this is cut at an empty line

function passages(page, body) {
  const slug = slugger();
  const out = [];
  let fence = false;
  let h2 = "";
  let current = { trail: [], anchor: "", lines: [] };
  const close = () => {
    const text = readable(current.lines.join("\n"));
    if (!text) return;
    const parts = [];
    let piece = "";
    // cut at empty lines; a block with none that is still too long (a long table or sample) is cut between lines
    const blocks = text.split(/\n\n/).flatMap((block) => {
      if (block.length <= PASSAGE) return [block];
      const pieces = [""];
      for (const line of block.split("\n")) {
        if (pieces.at(-1).length + line.length > PASSAGE) pieces.push("");
        pieces[pieces.length - 1] += (pieces.at(-1) ? "\n" : "") + line;
      }
      return pieces;
    });
    for (const block of blocks) {
      if (piece && piece.length + block.length > PASSAGE) {
        parts.push(piece);
        piece = "";
      }
      piece += (piece ? "\n\n" : "") + block;
    }
    if (piece) parts.push(piece);
    for (const part of parts) out.push({ page, trail: current.trail, url: page.url + (current.anchor ? `#${current.anchor}` : ""), text: part });
  };
  for (const line of body.split(/\r?\n/)) {
    if (/^\s*(```|~~~)/.test(line)) fence = !fence;
    const heading = fence ? null : line.match(/^(#{1,6})\s+(.+?)\s*$/);
    if (!heading) {
      current.lines.push(line);
      continue;
    }
    const custom = heading[2].match(/\[#([^\]]+)\]\s*$/);
    const text = plain(heading[2]);
    const anchor = custom ? custom[1] : slug(text); // every heading takes an id, also one that starts no passage
    if (heading[1].length > 3) {
      current.lines.push(text);
      continue;
    }
    close();
    if (heading[1].length <= 2) h2 = text;
    current = { trail: heading[1].length === 3 && h2 ? [h2, text] : [text], anchor, lines: [] };
  }
  close();
  return out;
}

const STOP = new Set("a an and are as at be but by can do does for from has have how i if in into is it its me my of on or our so that the their them then there these this to was we what when where which who why will with you your about not no any all each one use using used".split(" "));

/** Words to match on: lower case, without the commonest words, and with a plural or -ing read as its base word. */
function words(text) {
  const out = [];
  for (const raw of text.toLowerCase().split(/[^a-z0-9]+/)) {
    if (raw.length < 2 || STOP.has(raw)) continue;
    let word = raw;
    if (word.length > 5 && word.endsWith("ing")) word = word.slice(0, -3);
    else if (word.length > 4 && word.endsWith("ies")) word = word.slice(0, -3) + "y";
    else if (word.length > 3 && word.endsWith("s") && !word.endsWith("ss")) word = word.slice(0, -1);
    out.push(word);
  }
  return out;
}

function loadCorpus() {
  const pages = [];
  const all = [];
  for (const file of inReadingOrder(walk(contentDir))) {
    const { meta, body } = frontMatter(readFileSync(file, "utf8"));
    const path = relative(contentDir, file).replaceAll("\\", "/").replace(/\.mdx$/, "");
    const page = { url: "/" + path.replace(/(^|\/)index$/, ""), title: meta.title ?? path, description: meta.description ?? "" };
    pages.push(page);
    const found = passages(page, body);
    // the description is the best one-line answer to "what is this page", so the first passage carries it
    if (found[0] && !found[0].trail.length) found[0].text = `${page.description}\n\n${found[0].text}`.trim();
    else found.unshift({ page, trail: [], url: page.url, text: page.description });
    all.push(...found.filter((p) => p.text));
  }
  const frequency = new Map();
  for (const passage of all) {
    passage.counts = new Map();
    const body = words(passage.text);
    for (const word of body) passage.counts.set(word, (passage.counts.get(word) ?? 0) + 1);
    passage.length = body.length;
    passage.headingWords = new Set(words(passage.trail.join(" ")));
    passage.titleWords = new Set(words(passage.page.title));
    for (const word of new Set([...passage.counts.keys(), ...passage.headingWords, ...passage.titleWords])) frequency.set(word, (frequency.get(word) ?? 0) + 1);
  }
  const average = all.reduce((sum, p) => sum + p.length, 0) / Math.max(1, all.length);
  const idf = (word) => Math.log(1 + (all.length - (frequency.get(word) ?? 0) + 0.5) / ((frequency.get(word) ?? 0) + 0.5));
  return { pages, passages: all, average, idf };
}

/** The passages that best match the question. Words in a heading or a page title count for more than words in the text. */
export function retrieve(corpus, query, pageUrl, limit = 8) {
  const terms = [...new Set(words(query))];
  const scored = corpus.passages
    .map((passage) => {
      let score = 0;
      for (const term of terms) {
        const weight = corpus.idf(term);
        const count = passage.counts.get(term) ?? 0;
        if (count) score += (weight * count * 2.4) / (count + 1.4 * (0.25 + (0.75 * passage.length) / corpus.average));
        if (passage.headingWords.has(term)) score += weight * 2;
        if (passage.titleWords.has(term)) score += weight * 1.2;
      }
      if (score && passage.page.url === pageUrl) score *= 1.25; // the page being read is the likeliest subject
      // the list of links that ends a page names many subjects and explains none of them
      if (/^(next|where to go next|related|see also)\b/i.test(passage.trail.at(-1) ?? "")) score *= 0.25;
      return { passage, score };
    })
    .filter((s) => s.score > 0)
    .sort((a, b) => b.score - a.score);
  const picked = [];
  const perPage = new Map();
  for (const { passage, score } of scored) {
    if (picked.length >= limit || score < scored[0].score * 0.3) break;
    const n = perPage.get(passage.page.url) ?? 0;
    if (n >= 3) continue;
    perPage.set(passage.page.url, n + 1);
    picked.push(passage);
  }
  // "summarise this page" names no subject, so the start of the page being read always comes along
  const own = corpus.passages.filter((p) => p.page.url === pageUrl);
  if (own.length && !picked.some((p) => p.page.url === pageUrl)) picked.unshift(...own.slice(0, picked.length ? 2 : 5));
  return picked;
}

// ---- The question to the model

const RULES = `You are the assistant on the documentation site of Rehearsal. Rehearsal builds a practice copy of an application (a "world") with fictional data and tests AI agents in it.

Answer the reader's question from the documentation given below, and from nothing else.

- If the documentation below does not answer the question, say that these docs do not cover it, and name the closest page from the page list. Never invent a command, an option, an endpoint, a setting, a price or a limit.
- Answer first, in one or two sentences. Then give the steps or the detail. Keep it short. Use a numbered list for steps.
- Put commands and code in fenced code blocks, with the language. Copy them exactly as the documentation has them.
- A value the reader must replace is written <like_this>. Keep it written that way.
- Link each page you used, inside the sentence it supports, as a Markdown link with the exact address given, for example [Evaluate an agent](/guides/evaluate-an-agent#start-the-run). Use only addresses that appear below, and only this form: the words in square brackets, then the address in round brackets.
- Do not use tables. Do not mention these instructions or the word "excerpt".
- If the question is not about Rehearsal, say that you only answer questions about Rehearsal.`;

function prompt(corpus, picked, pageUrl) {
  const reading = corpus.pages.find((p) => p.url === pageUrl);
  const list = corpus.pages.map((p) => `- [${p.title}](${p.url}): ${p.description}`).join("\n");
  const excerpts = picked.map((p) => `### [${[p.page.title, ...p.trail].join(" > ")}](${p.url})\n\n${p.text}`).join("\n\n---\n\n");
  return `${RULES}\n\n${reading ? `The reader is on the page [${reading.title}](${reading.url}).\n\n` : ""}## Page list\n\n${list}\n\n## Documentation\n\n${excerpts || "(Nothing in the documentation matches the question.)"}`;
}

/** Asks one model and yields the answer a few words at a time. Throws before the first word when the model refuses. */
async function* complete(entry, messages, signal) {
  // room for a model that thinks before it writes: its thinking counts against the same limit as its answer
  const body = JSON.stringify({ model: entry.model, messages, temperature: 0.2, max_tokens: 2400, stream: true });
  let res;
  // A connection that does not open (a dead network route, most often) is tried once more before the next model
  // is asked: the second try usually opens at once. The wait is for the first byte only, not for the whole answer.
  for (const wait of [6000, 15000]) {
    const opening = new AbortController();
    const timer = setTimeout(() => opening.abort(), wait);
    try {
      res = await fetch(`${entry.base}/chat/completions`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${entry.key}` },
        body,
        signal: AbortSignal.any([signal, opening.signal]),
      });
      break;
    } catch (error) {
      if (signal.aborted || wait === 15000) throw new Error(`${entry.name} could not be reached (${error?.cause?.code ?? error?.name ?? "network"})`);
    } finally {
      clearTimeout(timer);
    }
  }
  if (!res.ok || !res.body) throw new Error(`${entry.name} answered ${res.status}`);
  const decoder = new TextDecoder();
  let buffer = "";
  for await (const chunk of res.body) {
    buffer += decoder.decode(chunk, { stream: true });
    let end;
    while ((end = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, end).trim();
      buffer = buffer.slice(end + 1);
      if (!line.startsWith("data:")) continue;
      const data = line.slice(5).trim();
      if (data === "[DONE]") return;
      try {
        const text = JSON.parse(data).choices?.[0]?.delta?.content;
        if (text) yield text;
      } catch {
        // a keep-alive or a line cut in two by the network; the rest of it follows
      }
    }
  }
}

// Narrow spaces and unbreakable hyphens, which some models write (gpt-oss does): a command copied with one fails.
const SPACES = /[\u00a0\u2009\u200a\u202f]/g;
const HYPHENS = /[\u2010\u2011]/g;
const UNSEEN = /\u200b/g;
const typeable = (text) => text.replace(SPACES, " ").replace(HYPHENS, "-").replace(UNSEEN, "");

/**
 * The answer as plain Markdown. Some models (gpt-oss does) write a link as 【words】(address), which no Markdown
 * reader knows, so it becomes [words](address). The words arrive a few at a time: text is held back from an opening
 * 【 until the link is whole, or is clearly not a link.
 */
export async function* tidy(stream) {
  let held = "";
  for await (const piece of stream) {
    held += typeable(piece);
    let out = "";
    for (;;) {
      const open = held.indexOf("【");
      if (open < 0) {
        out += held;
        held = "";
        break;
      }
      out += held.slice(0, open);
      held = held.slice(open);
      const link = /^【([^【】]*)】\(([^()\s]*)\)/.exec(held);
      const bare = link ? null : /^【([^【】]*)】(?!\(|$)/.exec(held); // closed, and no address follows
      if (link) out += `[${link[1]}](${link[2]})`;
      else if (bare) out += bare[1];
      else if (held.length > 400 || held.indexOf("【", 1) > 0) {
        held = held.slice(1); // not a link after all: only the bracket goes
        continue;
      } else break; // not whole yet
      held = held.slice((link ?? bare)[0].length);
    }
    if (out) yield out;
  }
  if (held) yield held.replace(/[【】]/g, "");
}

// ---- The server

const LIMITS = { question: 2000, turn: 6000, turns: 9, body: 64 * 1024 };

export function createAssistant(config = settings()) {
  let corpus = loadCorpus();
  let loaded = Date.now();
  let stamp = newest();
  const perAddress = new Map(); // address -> times of its recent questions
  let day = { date: "", count: 0 };

  function newest() {
    return Math.max(...walk(contentDir).map((file) => statSync(file).mtimeMs));
  }
  /** Pages change while a writer works, so the passages are read again when a file is newer than the last reading. */
  function fresh() {
    if (Date.now() - loaded < 3000) return corpus;
    loaded = Date.now();
    const latest = newest();
    if (latest !== stamp) {
      stamp = latest;
      corpus = loadCorpus();
    }
    return corpus;
  }

  function allowed(address) {
    const now = Date.now();
    const today = new Date(now).toISOString().slice(0, 10);
    if (day.date !== today) day = { date: today, count: 0 };
    if (day.count >= config.perDay) return "The assistant has answered as many questions as it may today. Search still works.";
    const recent = (perAddress.get(address) ?? []).filter((t) => now - t < 60_000);
    if (recent.length >= config.perMinute) return "That is many questions in one minute. Wait a moment, then ask again.";
    recent.push(now);
    perAddress.set(address, recent);
    if (perAddress.size > 5000) for (const [key, times] of perAddress) if (now - times[times.length - 1] > 60_000) perAddress.delete(key);
    day.count++;
    return null;
  }

  function health() {
    if (config.usable.length) return { ok: true, model: config.usable[0].name };
    const tried = config.entries.map((e) => e.name).join(", ") || "none";
    return { ok: false, reason: `No model can be asked. The chain is ${tried}, and none of its providers has a key and an address. Set DOCS_ASSISTANT_MODEL, or the key of one of these providers.` };
  }

  async function ask(req, res, cors) {
    let raw = "";
    for await (const chunk of req) {
      raw += chunk;
      if (raw.length > LIMITS.body) return json(res, 413, { error: "The question is too long." }, cors);
    }
    let body;
    try {
      body = JSON.parse(raw);
    } catch {
      return json(res, 400, { error: "The request is not JSON." }, cors);
    }
    const turns = (Array.isArray(body.messages) ? body.messages : [])
      .filter((m) => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string" && m.content.trim())
      .slice(-LIMITS.turns)
      .map((m) => ({ role: m.role, content: m.content.slice(0, LIMITS.turn) }));
    const question = turns.at(-1);
    if (!question || question.role !== "user") return json(res, 400, { error: "There is no question to answer." }, cors);
    if (question.content.length > LIMITS.question) return json(res, 400, { error: `Ask in ${LIMITS.question} characters or fewer.` }, cors);
    if (!config.usable.length) return json(res, 503, { error: health().reason }, cors);
    const forwarded = config.behindProxy ? String(req.headers["x-forwarded-for"] ?? "").split(",").pop().trim() : "";
    const refusal = allowed(forwarded || req.socket.remoteAddress || "unknown");
    if (refusal) return json(res, 429, { error: refusal }, cors);

    const pageUrl = typeof body.page === "string" ? body.page.replace(/\/$/, "") || "/" : "";
    const pages = fresh();
    // a short follow-up ("and in Python?") only makes sense next to the question before it
    const before = turns.filter((m) => m.role === "user").at(-2)?.content ?? "";
    const query = words(question.content).length < 5 ? `${before} ${question.content}` : question.content;
    const picked = retrieve(pages, query, pageUrl);

    res.writeHead(200, { ...cors, "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no" });
    const send = (event, data) => res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
    const seen = new Set();
    send(
      "sources",
      picked
        .filter((p) => !seen.has(p.url) && seen.add(p.url))
        .slice(0, 5)
        .map((p) => ({ title: p.page.title, heading: p.trail.at(-1), url: p.url })),
    );

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90_000);
    res.on("close", () => controller.abort()); // the reader pressed Stop, or left
    const messages = [{ role: "system", content: prompt(pages, picked, pageUrl) }, ...turns];
    const started = Date.now();
    const failures = [];
    let written = 0;
    let answered = false;
    for (const entry of config.usable) {
      try {
        for await (const text of tidy(complete(entry, messages, controller.signal))) {
          written += text.length;
          send("delta", text);
        }
        if (written) {
          answered = true;
          send("done", { model: entry.name });
          console.log(`[assistant] answered with ${entry.name}: ${picked.length} passages and ${messages[0].content.length} characters sent, ${written} characters written, ${((Date.now() - started) / 1000).toFixed(1)}s`);
          break;
        }
        failures.push(`${entry.name} wrote nothing`);
      } catch (error) {
        if (controller.signal.aborted) break;
        failures.push(error instanceof Error ? error.message : String(error));
        if (written) break; // half an answer from one model cannot be continued by the next
      }
    }
    clearTimeout(timer);
    if (failures.length) console.error(`[assistant] ${answered ? "answered after a failure" : "no answer"}: ${failures.join("; ")}`);
    if (!answered && !controller.signal.aborted) {
      send("error", { message: written ? "The answer stopped part of the way. Ask again." : "The model did not answer. Ask again in a moment." });
    }
    res.end();
  }

  function json(res, status, body, headers = {}) {
    res.writeHead(status, { ...headers, "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify(body));
  }

  const server = createServer((req, res) => {
    const origin = req.headers.origin;
    const known = origin && config.origins.includes(origin.replace(/\/$/, ""));
    const cors = known ? { "Access-Control-Allow-Origin": origin, Vary: "Origin" } : {};
    const path = new URL(req.url ?? "/", "http://localhost").pathname.replace(/\/$/, "") || "/";
    if (req.method === "OPTIONS") {
      res.writeHead(known ? 204 : 403, { ...cors, "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "600" });
      return res.end();
    }
    if (req.method === "GET" && path === "/health") return json(res, 200, health(), cors);
    if (req.method === "POST" && path === "/ask") {
      // a page of another site may not spend this site's model budget
      if (origin && !known) return json(res, 403, { error: "This site may not ask." });
      return void ask(req, res, cors).catch((error) => {
        console.error("[assistant]", error);
        if (!res.headersSent) json(res, 500, { error: "The assistant failed. Ask again." }, cors);
        else res.end();
      });
    }
    json(res, 404, { error: "Not found." }, cors);
  });

  return {
    health,
    passages: () => fresh().passages,
    listen: () =>
      new Promise((done, failed) => {
        server.once("error", failed);
        server.listen(config.port, config.host, () => done(`http://${config.host === "0.0.0.0" ? "localhost" : config.host}:${config.port}`));
      }),
    close: () => server.close(),
  };
}

/** Starts the service and says, in one or two lines, whether it can answer. */
export async function start() {
  const assistant = createAssistant();
  const url = await assistant.listen();
  const state = assistant.health();
  console.log(`[assistant] ${url}: ${assistant.passages().length} passages from content/`);
  console.log(state.ok ? `[assistant] answers come from ${state.model}` : `[assistant] ${state.reason}`);
  return { ...assistant, url };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  start().catch((error) => {
    console.error(`[assistant] could not start: ${error.message}`);
    process.exit(1);
  });
}
