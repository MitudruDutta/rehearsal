"use client";

import { useEffect, useRef } from "react";

/** A picture drawn as square blocks behind a panel of the landing page (the Great Wave behind the hero, the night
 * riders behind the closing panel). The whole picture spans the width of the panel. Where the panel is taller than
 * the picture and the window (the hero), the picture is held once its foot reaches the bottom of the window while
 * the rest of the panel scrolls over it, and it leaves with the panel's end: it is never cropped to fit and never
 * runs out. The picture is dimmed toward the page colour so text reads over it. Where the cursor passes, blocks
 * scatter away from it a whole block at a time and show their full colour, then spring back. The canvas holds one
 * pixel per block and is scaled up unsmoothed, so a frame is cheap, and nothing runs while the picture is at rest. */

const LEVELS = 9; // steps of brightness: a short palette, as in pixel art
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]; // 4x4 ordered dither, so gradients keep the block grid visible
const DITHER = 0.6; // how far the dither reaches between two steps of brightness
const REACH = 9; // blocks around the cursor that it disturbs
const SWELL = 2.6; // how hard blocks are pushed outward from the cursor
const DRAG = 2.5; // blocks a block next to the cursor is carried along its path
const FOLLOW = 0.35; // how quickly blocks take up that shape while the cursor moves
const SPRING = 0.03; // pull back to rest, per step
const DAMPING = 0.9;
const MAX_SHIFT = 6; // blocks
const STEP_MS = 1000 / 60;

/** Blends two canvas pixels (stored as 0xAABBGGRR): t = 0 gives a, t = 1 gives b. */
function mix(a: number, b: number, t: number) {
  const u = 1 - t;
  return (
    0xff000000 |
    ((((a >>> 16) & 255) * u + ((b >>> 16) & 255) * t) << 16) |
    ((((a >>> 8) & 255) * u + ((b >>> 8) & 255) * t) << 8) |
    ((a & 255) * u + (b & 255) * t)
  );
}

export function PixelBackdrop({
  src,
  focusX = 0.5,
  wash = [0.4, 0.6],
}: {
  src: string;
  /** which part of the picture stays in view when a narrow screen crops its sides: 0 is the left edge, 1 the right */
  focusX?: number;
  /** how far the picture is dimmed toward the page colour, at its top and at its foot */
  wash?: [number, number];
}) {
  const [washTop, washFoot] = wash;
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const window100 = useRef<HTMLElement>(null);

  useEffect(() => {
    const box = wrap.current;
    const el = canvas.current;
    const tall = window100.current;
    const ctx = el?.getContext("2d");
    if (!box || !el || !tall || !ctx) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)");
    const img = new Image();
    let cols = 0;
    let rows = 0;
    let cell = 1; // CSS pixels per block
    let fitW = 0; // the width and the height the picture was last fitted to, in CSS pixels
    let fitH = 0;
    let frame: ImageData | null = null;
    let out = new Uint32Array(0); // what is on screen, one colour per block
    let full = new Uint32Array(0); // the picture in its own colours
    let dim = new Uint32Array(0); // the picture as it rests, dimmed toward the page colour
    let grain = new Float32Array(0); // each block's own share of a disturbance, so neighbours scatter by different amounts
    let ox = new Float32Array(0); // each block's shift, in blocks
    let oy = new Float32Array(0);
    let vx = new Float32Array(0);
    let vy = new Float32Array(0);
    let live = [1, 0, 1, 0]; // the rectangle of blocks that may be disturbed: x0, x1, y0, y1 (empty while x0 > x1)
    let last: [number, number] | null = null;
    let raf = 0;
    let prev = 0;
    let owed = 0;

    // The height the picture has to cover: the panel's, but no more than the window's, because a taller panel
    // scrolls over a picture that is held in view. A hero's height shifts a little as its replay runs; being
    // taller than the window, that does not change this.
    const need = () => Math.min(box.clientHeight, tall.offsetHeight || window.innerHeight);

    const fit = () => {
      const w = box.clientWidth;
      const h = need();
      if (!w || !h || !img.naturalWidth) return;
      const dpr = window.devicePixelRatio || 1;
      // a block is a whole number of device pixels, so every block is the same size
      cell = Math.max(2, Math.round(Math.min(10, Math.max(5, w / 210)) * dpr)) / dpr;
      cols = Math.ceil(w / cell);
      // the whole picture spans the width; it is enlarged, cropping its sides, only where that leaves it too short
      const scale = Math.max(cols / img.naturalWidth, h / cell / img.naturalHeight);
      rows = Math.ceil(img.naturalHeight * scale);
      fitW = w;
      fitH = h;
      el.width = cols;
      el.height = rows;
      el.style.width = `${cols * cell}px`;
      el.style.height = `${rows * cell}px`;
      el.style.top = `min(0px, calc(100lvh - ${rows * cell}px))`; // held once its foot reaches the bottom of the window
      const sw = cols / scale;
      const sx = Math.min(img.naturalWidth - sw, Math.max(0, focusX * img.naturalWidth - sw / 2));
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(img, sx, 0, sw, img.naturalHeight, 0, 0, cols, rows);
      frame = ctx.getImageData(0, 0, cols, rows);
      out = new Uint32Array(frame.data.buffer);
      // the wrapper is painted in the page colour, so the dimming follows the palette the hero is given
      const [r = 0, g = 0, b = 0] = (getComputedStyle(box).backgroundColor.match(/[\d.]+/g) ?? []).map(Number);
      const page = 0xff000000 | (b << 16) | (g << 8) | r;
      const px = frame.data;
      for (let y = 0, p = 0; y < rows; y++) {
        for (let x = 0; x < cols; x++, p += 4) {
          // only brightness is stepped, so every block keeps the hue it has in the print
          const light = 0.299 * px[p] + 0.587 * px[p + 1] + 0.114 * px[p + 2];
          const nudge = ((BAYER[(y & 3) * 4 + (x & 3)] + 0.5) / 16 - 0.5) * DITHER;
          const gain = light ? ((Math.round((light / 255) * (LEVELS - 1) + nudge) / (LEVELS - 1)) * 255) / light : 0;
          for (let c = 0; c < 3; c++) px[p + c] *= gain;
        }
      }
      full = out.slice();
      dim = new Uint32Array(cols * rows);
      for (let y = 0, i = 0; y < rows; y++) {
        const veil = washTop + ((washFoot - washTop) * y) / rows;
        for (let x = 0; x < cols; x++, i++) dim[i] = mix(full[i], page, veil);
      }
      out.set(dim);
      ctx.putImageData(frame, 0, 0);
      grain = new Float32Array(cols * rows);
      for (let i = 0; i < grain.length; i++) grain[i] = 0.35 + (1.3 * (Math.imul(i + 1, 2654435761) >>> 0)) / 2 ** 32;
      ox = new Float32Array(cols * rows);
      oy = new Float32Array(cols * rows);
      vx = new Float32Array(cols * rows);
      vy = new Float32Array(cols * rows);
      live = [1, 0, 1, 0];
      last = null;
    };

    /** One step of every disturbed block springing back; returns whether any is still moving. */
    const step = () => {
      let moving = false;
      for (let y = live[2]; y <= live[3]; y++) {
        for (let x = live[0], i = y * cols + x; x <= live[1]; x++, i++) {
          let px = ox[i];
          let py = oy[i];
          let sx = vx[i];
          let sy = vy[i];
          if (px === 0 && py === 0 && sx === 0 && sy === 0) continue;
          sx = (sx - px * SPRING) * DAMPING;
          sy = (sy - py * SPRING) * DAMPING;
          px = Math.min(MAX_SHIFT, Math.max(-MAX_SHIFT, px + sx));
          py = Math.min(MAX_SHIFT, Math.max(-MAX_SHIFT, py + sy));
          const energy = Math.abs(px) + Math.abs(py) + 5 * (Math.abs(sx) + Math.abs(sy));
          if (energy < 0.08) px = py = sx = sy = 0;
          else moving = true;
          ox[i] = px;
          oy[i] = py;
          vx[i] = sx;
          vy[i] = sy;
          // a shifted block shows the colour that started that many whole blocks away, brighter the more it is disturbed
          const from = Math.min(rows - 1, Math.max(0, y - Math.round(py))) * cols + Math.min(cols - 1, Math.max(0, x - Math.round(px)));
          out[i] = energy < 0.08 ? dim[from] : mix(dim[from], full[from], Math.min(1, energy / 4) * 0.9);
        }
      }
      if (!moving) live = [1, 0, 1, 0];
      return moving;
    };

    const tick = (now: number) => {
      raf = 0;
      owed += Math.min(100, now - prev); // fixed steps, so the motion is the same on a 60 Hz and a 144 Hz screen
      prev = now;
      let moving = true;
      while (owed >= STEP_MS) {
        moving = step();
        owed -= STEP_MS;
      }
      if (frame) ctx.putImageData(frame, 0, 0);
      if (moving) raf = requestAnimationFrame(tick);
    };

    const onMove = (e: PointerEvent) => {
      if (!frame || still.matches) return;
      const at = el.getBoundingClientRect();
      const x = (e.clientX - at.left) / cell;
      const y = (e.clientY - at.top) / cell;
      const from = last;
      last = [x, y];
      if (!from) return;
      const dx = x - from[0];
      const dy = y - from[1];
      const dist = Math.hypot(dx, dy);
      if (dist < 0.02 || dist > 40) return; // a jump (the cursor came back in, or a new touch) disturbs nothing
      const steps = Math.ceil(dist / (REACH / 2));
      for (let s = 1; s <= steps; s++) {
        const cx = from[0] + (dx * s) / steps;
        const cy = from[1] + (dy * s) / steps;
        const x0 = Math.max(0, Math.floor(cx - REACH));
        const x1 = Math.min(cols - 1, Math.ceil(cx + REACH));
        const y0 = Math.max(0, Math.floor(cy - REACH));
        const y1 = Math.min(rows - 1, Math.ceil(cy + REACH));
        if (x0 > x1 || y0 > y1) continue; // the cursor is off the picture
        live = live[0] > live[1] ? [x0, x1, y0, y1] : [Math.min(live[0], x0), Math.max(live[1], x1), Math.min(live[2], y0), Math.max(live[3], y1)];
        for (let by = y0; by <= y1; by++) {
          for (let bx = x0; bx <= x1; bx++) {
            const rx = bx + 0.5 - cx;
            const ry = by + 0.5 - cy;
            const d = Math.hypot(rx, ry);
            if (d >= REACH) continue;
            const i = by * cols + bx;
            const near = (1 - d / REACH) ** 2 * grain[i];
            // blocks swell away from the cursor and are carried a little along its path
            ox[i] += ((rx * SWELL + (dx / dist) * DRAG) * near - ox[i]) * FOLLOW;
            oy[i] += ((ry * SWELL + (dy / dist) * DRAG) * near - oy[i]) * FOLLOW;
            vx[i] *= 1 - FOLLOW;
            vy[i] *= 1 - FOLLOW;
          }
        }
      }
      if (!raf && live[0] <= live[1]) {
        prev = performance.now();
        owed = 0;
        raf = requestAnimationFrame(tick);
      }
    };

    img.onload = () => {
      fit();
      el.style.opacity = "1";
    };
    img.src = src;
    const refit = () => {
      if (box.clientWidth !== fitW || need() !== fitH) fit();
    };
    const resized = new ResizeObserver(refit);
    resized.observe(box);
    const themed = new MutationObserver(fit);
    themed.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    window.addEventListener("resize", refit);
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      img.onload = null;
      cancelAnimationFrame(raf);
      resized.disconnect();
      themed.disconnect();
      window.removeEventListener("resize", refit);
      window.removeEventListener("pointermove", onMove);
    };
  }, [src, focusX, washTop, washFoot]);

  // The canvas is sticky, so nothing between it and the page may scroll or hide overflow (clipping is fine).
  // The empty element measures the window at its tallest, which on a phone does not change as the address bar hides.
  return (
    <div ref={wrap} aria-hidden="true" className="pointer-events-none absolute inset-0 bg-background">
      <canvas ref={canvas} className="sticky block opacity-0 transition-opacity duration-700 [image-rendering:pixelated]" />
      <i ref={window100} className="fixed top-0 h-lvh w-0" />
    </div>
  );
}
