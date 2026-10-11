"use client";

import { createContext, use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { site } from "@/lib/site";

/** A page the answer was written from. */
export type Source = { title: string; heading?: string; url: string };

export type Message = {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  /**
   * An answer is "writing" until its last word arrives. "failed" carries a sentence for the reader in `error`;
   * "offline" means this site has no assistant to ask, or it did not respond.
   */
  state?: "writing" | "done" | "failed" | "offline";
  error?: string;
};

/** What the assistant says about itself at /health. `null` until it has been asked. */
export type Health = { ok: boolean; model?: string; reason?: string } | null;

type Assistant = {
  open: boolean;
  setOpen: (open: boolean) => void;
  /** Opens the panel. With a question, asks it at once. */
  ask: (question?: string) => void;
  messages: Message[];
  busy: boolean;
  health: Health;
  send: (question: string) => void;
  stop: () => void;
  reset: () => void;
};

const AssistantContext = createContext<Assistant | null>(null);

export function useAssistant(): Assistant {
  const value = use(AssistantContext);
  if (!value) throw new Error("useAssistant must be used inside <AssistantProvider>.");
  return value;
}

/** Reads the assistant's reply: lines of "event: name" and "data: json", with an empty line after each event. */
async function* events(body: ReadableStream<Uint8Array>): AsyncGenerator<{ event: string; data: unknown }> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      try {
        yield { event, data: JSON.parse(data) };
      } catch {
        // a line that is not JSON is not ours; skip it
      }
    }
  }
}

/** The conversation with the docs assistant. One for the whole site, so it survives moving between pages. */
export function AssistantProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<Health>(null);
  const nextId = useRef(1);
  const request = useRef<AbortController | null>(null);
  // what `send` reads when it runs, kept out of its dependencies so the function stays the same between renders
  const history = useRef<Message[]>([]);
  const page = useRef(pathname);
  useEffect(() => {
    history.current = messages;
    page.current = pathname;
  }, [messages, pathname]);

  // the first time the panel opens, ask the assistant whether it can answer, so the panel can say so before a question
  const asked = useRef(false);
  useEffect(() => {
    if (!open || asked.current) return;
    asked.current = true;
    if (!site.assistantUrl) {
      setHealth({ ok: false, reason: "This site was built without an assistant address." });
      return;
    }
    fetch(`${site.assistantUrl}/health`)
      .then((res) => res.json())
      .then((body: { ok?: boolean; model?: string; reason?: string }) => setHealth({ ok: Boolean(body.ok), model: body.model, reason: body.reason }))
      .catch(() => setHealth({ ok: false, reason: `Nothing answered at ${site.assistantUrl}.` }));
  }, [open]);

  const patch = useCallback((id: number, change: (m: Message) => Message) => {
    setMessages((all) => all.map((m) => (m.id === id ? change(m) : m)));
  }, []);

  const send = useCallback(
    async (text: string) => {
      const question = text.trim();
      if (!question || request.current) return;
      const user: Message = { id: nextId.current++, role: "user", content: question };
      const answer: Message = { id: nextId.current++, role: "assistant", content: "", state: "writing" };
      // what the assistant needs to follow the conversation: the finished turns, then this question
      const turns = [...history.current.filter((m) => m.role === "user" || (m.state === "done" && m.content)), user].map((m) => ({ role: m.role, content: m.content }));
      setMessages((all) => [...all, user, answer]);

      if (!site.assistantUrl) {
        patch(answer.id, (m) => ({ ...m, state: "offline" }));
        return;
      }
      const controller = new AbortController();
      request.current = controller;
      setBusy(true);
      try {
        const res = await fetch(`${site.assistantUrl}/ask`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages: turns.slice(-9), page: page.current }),
          signal: controller.signal,
        });
        if (!res.ok || !res.body) {
          const body = (await res.json().catch(() => null)) as { error?: string } | null;
          const error = body?.error ?? `The assistant answered with an error (${res.status}).`;
          // 503 is the assistant saying it has no model to ask: the same as having no assistant
          patch(answer.id, (m) => (res.status === 503 ? { ...m, state: "offline", error } : { ...m, state: "failed", error }));
          if (res.status === 503) setHealth({ ok: false, reason: error });
          return;
        }
        let finished = false;
        for await (const { event, data } of events(res.body)) {
          if (event === "sources") patch(answer.id, (m) => ({ ...m, sources: data as Source[] }));
          else if (event === "delta") patch(answer.id, (m) => ({ ...m, content: m.content + String(data) }));
          else if (event === "error") {
            finished = true;
            patch(answer.id, (m) => ({ ...m, state: "failed", error: (data as { message?: string }).message ?? "The answer could not be written." }));
          } else if (event === "done") {
            finished = true;
            patch(answer.id, (m) => ({ ...m, state: "done" }));
          }
        }
        if (!finished) patch(answer.id, (m) => (m.content ? { ...m, state: "done" } : { ...m, state: "failed", error: "The answer stopped before it started. Ask again." }));
      } catch (error) {
        if (controller.signal.aborted) {
          // the reader pressed Stop: keep what was written, drop an answer that had not started
          setMessages((all) => all.flatMap((m) => (m.id !== answer.id ? [m] : m.content ? [{ ...m, state: "done" as const }] : [])));
        } else {
          // the request did not reach the assistant at all
          patch(answer.id, (m) => ({ ...m, state: "offline", error: error instanceof Error ? error.message : undefined }));
          setHealth({ ok: false, reason: `Nothing answered at ${site.assistantUrl}.` });
        }
      } finally {
        request.current = null;
        setBusy(false);
      }
    },
    [patch],
  );

  const stop = useCallback(() => request.current?.abort(), []);

  const reset = useCallback(() => {
    request.current?.abort();
    setMessages([]);
  }, []);

  const ask = useCallback(
    (question?: string) => {
      setOpen(true);
      if (question) void send(question);
    },
    [send],
  );

  // Ctrl I or ⌘I opens and closes the panel from anywhere on the site
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key.toLowerCase() !== "i" || !(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey) return;
      e.preventDefault();
      setOpen((v) => !v);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const value = useMemo(() => ({ open, setOpen, ask, messages, busy, health, send, stop, reset }), [open, ask, messages, busy, health, send, stop, reset]);
  return <AssistantContext value={value}>{children}</AssistantContext>;
}
