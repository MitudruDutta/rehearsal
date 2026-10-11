"use client";

import { ArrowRight, LayoutDashboard, Play } from "lucide-react";
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

/** Where the button leads: a visitor who is not signed in starts on "Create your account", everyone else on the console. */
const consoleHref = (s: Session) => (s === "out" ? "/app/?mode=signup" : "/app/");

/** The one white button in the black navigation tab: Start free for visitors, Open console for people already signed in. */
export function NavActions() {
  const s = useSession();
  const Icon = s === "in" ? LayoutDashboard : s === "setup" ? ArrowRight : Play;
  return (
    <Button asChild size="sm" className={`h-[38px] gap-2 rounded-[9px] bg-white px-4 text-sm font-semibold text-black hover:bg-white/85 has-[>svg]:px-3.5 ${s === "unknown" ? "invisible" : ""}`}>
      <Link href={consoleHref(s)}><Icon className="size-4" fill={Icon === Play ? "currentColor" : "none"} />{s === "in" ? "Open console" : s === "setup" ? "Finish setup" : "Start free"}</Link>
    </Button>
  );
}

/** A page call to action: Start free for visitors, Open console for people already signed in. */
export function StartCta({ size = "lg" }: { size?: "lg" | "default" }) {
  const s = useSession();
  const label = s === "in" ? "Open console" : s === "setup" ? "Finish setup" : "Start free";
  return <Button asChild size={size} className={s === "unknown" ? "invisible" : undefined}><Link href={consoleHref(s)}>{label}{s === "in" && <ArrowRight />}</Link></Button>;
}
