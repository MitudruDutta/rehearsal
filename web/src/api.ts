"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type Json = any; // API payloads are documented in /v1 OpenAPI; screens read the fields they show.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = Json>(path: string, init: RequestInit & { body?: any } = {}): Promise<T> {
  const body = init.body !== undefined && typeof init.body !== "string" ? JSON.stringify(init.body) : init.body;
  const res = await fetch(path, {
    credentials: "same-origin",
    ...init,
    body,
    headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(init.headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const post = <T = Json>(path: string, body: any = {}) => api<T>(path, { method: "POST", body });
export const del = <T = Json>(path: string) => api<T>(path, { method: "DELETE" });

/** Loads a resource and re-loads it every `pollMs` while `poll` is true. */
export function useResource<T = Json>(path: string | null, pollMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    if (!path) return;
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [path]);
  useEffect(() => {
    load();
    if (!pollMs) return;
    const t = setInterval(load, pollMs);
    return () => clearInterval(t);
  }, [load, pollMs]);
  return { data, error, reload: load };
}

export interface RhEvent {
  event_id: number;
  stream: string;
  sequence: number;
  episode_id: string | null;
  type: string;
  actor_id: string | null;
  goal_version: number | null;
  summary: string;
  data: Json;
  created_at: string;
}

/** Live event stream; EventSource resends Last-Event-ID on reconnect and we drop replays. */
export function useEvents(url: string | null) {
  const [events, setEvents] = useState<RhEvent[]>([]);
  const [ended, setEnded] = useState(false);
  const seen = useRef(new Set<number>());
  useEffect(() => {
    if (!url) return;
    seen.current = new Set();
    setEvents([]);
    setEnded(false);
    const es = new EventSource(url, { withCredentials: true });
    const onAny = (msg: MessageEvent) => {
      const ev = JSON.parse(msg.data) as RhEvent;
      if (!ev.event_id || seen.current.has(ev.event_id)) return;
      seen.current.add(ev.event_id);
      setEvents((prev) => [...prev, ev]);
    };
    es.onmessage = onAny;
    es.addEventListener("stream.end", () => {
      setEnded(true);
      es.close();
    });
    return () => es.close();
  }, [url]);
  return { events, ended };
}

export function pct(x: number | null | undefined) {
  return x === null || x === undefined ? "–" : `${Math.round(x * 100)}%`;
}
