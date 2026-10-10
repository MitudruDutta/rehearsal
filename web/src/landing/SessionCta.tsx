"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

type Session = "unknown" | "out" | "in" | "setup";

let cached: Promise<Session> | null = null;

/** Asks the API once per page load whether this browser is signed in. */
function useSession(): Session {
  const [state, setState] = useState<Session>("unknown");
  useEffect(() => {
    cached ??= fetch("/v1/me", { credentials: "same-origin" })
      .then(async (r) => (r.ok ? ((await r.json()).needs_onboarding ? "setup" : "in") : "out"))
      .catch(() => "out" as Session);
    cached.then(setState);
  }, []);
  return state;
}

/** Header actions: Sign in and Start free for visitors; one Open console button for people already signed in. */
export function NavActions() {
  const s = useSession();
  if (s === "in" || s === "setup") {
    return <Button asChild size="sm"><Link href="/app/">{s === "setup" ? "Finish setup" : "Open console"} <ArrowRight /></Link></Button>;
  }
  return (
    <span className={s === "unknown" ? "invisible flex gap-1" : "flex gap-1"}>
      <Button asChild variant="ghost" size="sm"><Link href="/app/">Sign in</Link></Button>
      <Button asChild size="sm"><Link href="/app/">Start free</Link></Button>
    </span>
  );
}

/** A page call to action: Start free for visitors, Open console for people already signed in. */
export function StartCta({ size = "lg" }: { size?: "lg" | "default" }) {
  const s = useSession();
  const label = s === "in" ? "Open console" : s === "setup" ? "Finish setup" : "Start free";
  return <Button asChild size={size} className={s === "unknown" ? "invisible" : undefined}><Link href="/app/">{label}{s === "in" && <ArrowRight />}</Link></Button>;
}
