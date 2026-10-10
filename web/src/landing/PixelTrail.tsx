"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";

const CELL = 14; // px, the size of one pixel of the trail
const LIFE = 700; // ms a pixel takes to fade out
const COLOUR = "rgb(29 78 216)";
// the brush: a 3 x 3 block of pixels, brightest in the middle
const BRUSH: [number, number, number][] = [[0, 0, 1], [-1, 0, 0.85], [1, 0, 0.85], [0, -1, 0.85], [0, 1, 0.85], [-1, -1, 0.6], [1, -1, 0.6], [-1, 1, 0.6], [1, 1, 0.6]];

/** A section of the page where the mouse leaves a trail of blue pixels on the background. The pixels sit behind the
 * content, so they show between cards, never over text. Off for touch and with reduced motion.
 * One canvas the size of the window (not of the section, which is thousands of pixels tall), drawn only inside the
 * section's box and only while pixels are fading. */
export function PixelTrail({ children, className }: { children: ReactNode; className?: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches || !matchMedia("(pointer: fine)").matches) return;
    const el = wrap.current!;
    const cv = canvas.current!;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const cells = new Map<string, { x: number; y: number; born: number; alpha: number }>(); // grid cells, in page coordinates
    let frame = 0;
    let last: { x: number; y: number } | null = null;

    const resize = () => {
      const d = devicePixelRatio || 1;
      cv.width = innerWidth * d;
      cv.height = innerHeight * d;
      ctx.setTransform(d, 0, 0, d, 0, 0);
    };
    const light = (px: number, py: number, now: number, alpha: number) => {
      const x = Math.floor(px / CELL);
      const y = Math.floor(py / CELL);
      const old = cells.get(`${x},${y}`);
      if (!old || old.alpha <= alpha) cells.set(`${x},${y}`, { x, y, born: now, alpha });
    };
    const brush = (px: number, py: number, now: number, strength: number) => {
      for (const [dx, dy, a] of BRUSH) light(px + dx * CELL, py + dy * CELL, now, a * strength);
    };
    const draw = (now: number) => {
      ctx.clearRect(0, 0, innerWidth, innerHeight);
      const box = el.getBoundingClientRect();
      ctx.save();
      ctx.beginPath();
      ctx.rect(box.left, box.top, box.width, box.height);
      ctx.clip();
      ctx.fillStyle = COLOUR;
      for (const [key, c] of cells) {
        const t = (now - c.born) / LIFE;
        if (t >= 1) {
          cells.delete(key);
          continue;
        }
        ctx.globalAlpha = c.alpha * (1 - t) * (1 - t);
        ctx.fillRect(c.x * CELL - scrollX + 1, c.y * CELL - scrollY + 1, CELL - 2, CELL - 2);
      }
      ctx.restore();
      frame = cells.size ? requestAnimationFrame(draw) : 0;
    };
    const move = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      const now = performance.now();
      const { pageX: x, pageY: y } = e;
      if (last) {
        // fill the gap since the last event, so a fast move still leaves an unbroken line
        const steps = Math.min(40, Math.ceil(Math.hypot(x - last.x, y - last.y) / CELL));
        for (let i = 1; i < steps; i++) brush(last.x + ((x - last.x) * i) / steps, last.y + ((y - last.y) * i) / steps, now, 0.9);
      }
      brush(x, y, now, 1);
      // a few loose pixels around the stroke, fainter
      for (let i = 0; i < 3; i++) if (Math.random() < 0.5) light(x + (Math.random() - 0.5) * CELL * 7, y + (Math.random() - 0.5) * CELL * 7, now, 0.35 + Math.random() * 0.35);
      last = { x, y };
      if (!frame) frame = requestAnimationFrame(draw);
    };
    const leave = () => {
      last = null;
    };

    resize();
    addEventListener("resize", resize);
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", leave);
    return () => {
      removeEventListener("resize", resize);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerleave", leave);
      cancelAnimationFrame(frame);
    };
  }, []);
  return (
    <div ref={wrap} className={cn("relative isolate", className)}>
      <canvas ref={canvas} aria-hidden="true" className="pointer-events-none fixed inset-0 -z-10 size-full" />
      {children}
    </div>
  );
}
