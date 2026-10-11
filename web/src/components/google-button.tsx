"use client";

import { useTheme } from "next-themes";
import { useEffect, useRef, useState } from "react";

/* Google Identity Services: Google renders its own button (brand rules) and hands back a signed ID token,
   which the API verifies before creating or signing in the user. */

declare global {
  interface Window {
    google?: { accounts: { id: { initialize: (o: object) => void; renderButton: (el: HTMLElement, o: object) => void } } };
  }
}

let loading: Promise<void> | null = null;
function loadScript(): Promise<void> {
  loading ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => {
      loading = null;
      reject(new Error("Could not reach Google. Check your connection, or sign in with an API key."));
    };
    document.head.appendChild(s);
  });
  return loading;
}

export function GoogleButton({ clientId, onCredential, onError }: { clientId: string; onCredential: (credential: string) => void; onError: (message: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const { resolvedTheme } = useTheme();
  const [ready, setReady] = useState(false);
  // keep the latest callback without re-rendering Google's button on every parent render
  const cb = useRef(onCredential);
  cb.current = onCredential;
  useEffect(() => {
    let live = true;
    loadScript()
      .then(() => {
        if (!live || !box.current || !window.google) return;
        window.google.accounts.id.initialize({ client_id: clientId, callback: (r: { credential: string }) => cb.current(r.credential), ux_mode: "popup", auto_select: false });
        box.current.innerHTML = "";
        window.google.accounts.id.renderButton(box.current, {
          type: "standard",
          theme: resolvedTheme === "light" ? "outline" : "filled_black",
          size: "large",
          text: "continue_with",
          shape: "rectangular",
          logo_alignment: "left",
          width: Math.min(400, Math.max(200, box.current.offsetWidth)),
        });
        setReady(true);
      })
      .catch((e: Error) => onError(e.message));
    return () => {
      live = false;
    };
  }, [clientId, resolvedTheme, onError]);
  // Google draws the button in its own frame, as a light page. On our dark page the browser would paint an opaque
  // white backing behind a frame that does not match, which shows as a white edge around the button. Telling the
  // frame it sits in a light scheme keeps it see-through, so only Google's button shows.
  return <div ref={box} className="flex min-h-10 w-full justify-center [color-scheme:light]" aria-busy={!ready} />;
}
