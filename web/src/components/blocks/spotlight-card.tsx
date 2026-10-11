"use client";

import { useRef, useState, type PropsWithChildren } from "react";
import { cn } from "@/lib/utils";

/* Adapted from React Bits' SpotlightCard (reactbits.dev): a radial light that follows the pointer, in the accent colour. */

export function SpotlightCard({ children, className, color = "rgba(111, 149, 255, 0.18)" }: PropsWithChildren<{ className?: string; color?: string }>) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [on, setOn] = useState(false);
  return (
    <div
      ref={ref}
      onMouseMove={(e) => {
        const r = ref.current?.getBoundingClientRect();
        if (r) setPos({ x: e.clientX - r.left, y: e.clientY - r.top });
      }}
      onMouseEnter={() => setOn(true)}
      onMouseLeave={() => setOn(false)}
      className={cn("relative overflow-hidden rounded-xl border bg-card p-6", className)}
    >
      <div
        className="pointer-events-none absolute inset-0 transition-opacity duration-500"
        style={{ opacity: on ? 1 : 0, background: `radial-gradient(420px circle at ${pos.x}px ${pos.y}px, ${color}, transparent 70%)` }}
      />
      <div className="relative">{children}</div>
    </div>
  );
}
