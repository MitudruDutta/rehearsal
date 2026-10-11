"use client";

import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { ContactShadows, Environment, Html, Lightformer, OrbitControls, QuadraticBezierLine, RoundedBox } from "@react-three/drei";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { RhEvent } from "../api";
import { look } from "./look";
import { DESK_Z, ROOM_D, ROOM_W, RoomModel, type Actor, type Desk, type Tone } from "./model";

/**
 * The rehearsal room, rendered with react-three-fiber. Every movement and label
 * comes from a recorded event via RoomModel; nothing moves on its own. Click a
 * person or a desk to inspect it.
 */

export type Selection = { kind: "actor" | "desk"; id: string };

const TONE_HEX: Record<Tone, string> = { go: "#3ecf8e", stop: "#ff6363", cue: "#f5a524", plain: "#bccdff" };
const TAPE = ["#f2e7cf", "#3ecf8e", "#4f7cf0", "#f5a524", "#d65a8f", "#2aa0c0"]; // spike tape
const hex = (n: number) => "#" + n.toString(16).padStart(6, "0");

function useWoodTexture() {
  return useMemo(() => {
    const c = document.createElement("canvas");
    c.width = 1024;
    c.height = 512;
    const g = c.getContext("2d")!;
    for (let row = 0, y = 0; y < c.height; row++, y += 32) {
      g.fillStyle = row % 2 ? "#a2774f" : "#966d47";
      g.fillRect(0, y, c.width, 31);
      g.fillStyle = "#7a5739";
      g.fillRect(0, y + 31, c.width, 1);
      const off = (row * 173) % 256;
      for (let x = -off; x < c.width; x += 256) g.fillRect(x, y, 2, 31);
      g.fillStyle = "rgba(255,255,255,0.05)";
      for (let i = 0; i < 40; i++) g.fillRect((i * 97 + row * 31) % 1024, y + ((i * 13) % 30), 60, 1);
    }
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(2, 1);
    t.anisotropy = 8;
    return t;
  }, []);
}

function Mat({ color, ...rest }: { color: string } & Record<string, unknown>) {
  return <meshStandardMaterial color={color} roughness={0.75} {...rest} />;
}

function Room({ mode, doorRef }: { mode: "episode" | "compiler"; doorRef: React.RefObject<THREE.Group | null> }) {
  const wood = useWoodTexture();
  const seats: [number, number][] = [[9.6, 6.1], [12, 6.1], [14.4, 6.1], [9.6, 8.7], [12, 8.7], [14.4, 8.7]];
  return (
    <group>
      <mesh rotation-x={-Math.PI / 2} position={[ROOM_W / 2, 0, ROOM_D / 2]} receiveShadow>
        <planeGeometry args={[ROOM_W, ROOM_D]} />
        <meshStandardMaterial map={wood} roughness={0.85} />
      </mesh>
      <mesh position={[ROOM_W / 2, 2.1, -0.1]} receiveShadow>
        <boxGeometry args={[ROOM_W, 4.2, 0.2]} />
        <Mat color="#1c1d22" />
      </mesh>
      <mesh position={[-0.1, 2.1, ROOM_D / 2]} receiveShadow>
        <boxGeometry args={[0.2, 4.2, ROOM_D]} />
        <Mat color="#17181c" />
      </mesh>
      <mesh position={[ROOM_W / 2, 0.1, 0.04]}>
        <boxGeometry args={[ROOM_W, 0.2, 0.08]} />
        <Mat color="#0b0c0e" />
      </mesh>
      <mesh position={[0.03, 2.3, 4.4]}>
        <boxGeometry args={[0.04, 1.8, 3]} />
        <Mat color="#e6edff" emissive="#bfd0ff" emissiveIntensity={0.8} />
      </mesh>
      <mesh rotation-x={-Math.PI / 2} position={[12, 0.01, 7.4]} receiveShadow>
        <planeGeometry args={[9.6, 4.8]} />
        <Mat color="#17203c" />
      </mesh>
      <mesh rotation-x={-Math.PI / 2} position={[12, 0.014, 7.4]} receiveShadow>
        <planeGeometry args={[9.0, 4.2]} />
        <Mat color="#212e58" />
      </mesh>
      <RoundedBox args={[6.2, 0.12, 1.6]} radius={0.05} position={[12, 0.78, 7.4]} castShadow receiveShadow>
        <Mat color="#a0703f" />
      </RoundedBox>
      {[[9.3, 6.8], [14.7, 6.8], [9.3, 8.0], [14.7, 8.0]].map(([x, z]) => (
        <mesh key={`${x}-${z}`} position={[x, 0.36, z]} castShadow>
          <boxGeometry args={[0.1, 0.72, 0.1]} />
          <Mat color="#5a3a22" />
        </mesh>
      ))}
      <mesh position={[10.6, 0.86, 7.2]} castShadow>
        <boxGeometry args={[0.5, 0.03, 0.36]} />
        <Mat color="#f4f1e8" />
      </mesh>
      <mesh position={[13.4, 0.93, 7.6]} castShadow>
        <cylinderGeometry args={[0.08, 0.07, 0.18, 16]} />
        <Mat color="#ef5d70" />
      </mesh>
      {seats.map(([x, z], i) => (
        <group key={i} position={[x, 0.022, z + (z < 7.4 ? -0.55 : 0.55)]}>
          <mesh><boxGeometry args={[0.7, 0.01, 0.09]} /><Mat color={TAPE[i % TAPE.length]} /></mesh>
          <mesh><boxGeometry args={[0.09, 0.01, 0.7]} /><Mat color={TAPE[i % TAPE.length]} /></mesh>
        </group>
      ))}
      <RoundedBox args={[1.7, 0.08, 0.9]} radius={0.03} position={[3.0, 0.82, 8.9]} castShadow receiveShadow>
        <Mat color="#d8dce4" />
      </RoundedBox>
      <mesh position={[3.0, 0.39, 8.9]} castShadow>
        <boxGeometry args={[1.6, 0.76, 0.84]} />
        <Mat color="#7d5638" />
      </mesh>
      <mesh position={[2.8, 0.87, 8.9]}>
        <boxGeometry args={[0.5, 0.02, 0.36]} />
        <Mat color="#f4f1e8" />
      </mesh>
      {[[0.9, 0.9], [ROOM_W - 1.1, ROOM_D - 1.3]].map(([x, z]) => (
        <group key={x} position={[x, 0, z]}>
          <RoundedBox args={[0.55, 0.55, 0.55]} radius={0.06} position={[0, 0.28, 0]} castShadow>
            <Mat color="#2a9dae" />
          </RoundedBox>
          <mesh position={[0, 1.0, 0]} castShadow>
            <icosahedronGeometry args={[0.6, 1]} />
            <Mat color="#3f8f4a" flatShading />
          </mesh>
        </group>
      ))}
      {mode === "episode" && (
        <group>
          <mesh position={[20.6, 1.3, 0.02]}>
            <boxGeometry args={[1.6, 2.6, 0.14]} />
            <Mat color="#1f1710" />
          </mesh>
          <group ref={doorRef} position={[19.9, 0, 0.14]}>
            <RoundedBox args={[1.38, 2.4, 0.08]} radius={0.02} position={[0.69, 1.2, 0]} castShadow>
              <Mat color="#8a5a35" />
            </RoundedBox>
            <mesh position={[1.2, 1.15, 0.07]}>
              <sphereGeometry args={[0.05, 12, 12]} />
              <Mat color="#c8a165" metalness={0.7} />
            </mesh>
          </group>
        </group>
      )}
    </group>
  );
}

// ---------------------------------------------------------------------------- desks

function DeskPiece({ desk, model, onSelect, selected }: { desk: Desk; model: RoomModel; onSelect?: (s: Selection) => void; selected: boolean }) {
  const screen = useRef<THREE.MeshStandardMaterial>(null);
  const leds = useRef<THREE.MeshStandardMaterial[]>([]);
  const [tone, setTone] = useState<Tone | null>(null);
  useFrame(({ clock }) => {
    const now = performance.now();
    const flash = desk.flash && desk.flash.until > now ? desk.flash.tone : null;
    const busy = [...model.actors.values()].some((a) => a.busyUntil > now && Math.abs(a.x - desk.x) < 1.2 && Math.abs(a.z - (DESK_Z + 1.1)) < 0.2);
    const t = flash ?? (busy ? "plain" : null);
    if (t !== tone) setTone(t);
    if (screen.current) {
      screen.current.emissive.set(t ? TONE_HEX[t] : "#1a2236");
      screen.current.emissiveIntensity = t ? (busy ? 0.9 + 0.35 * Math.sin(clock.elapsedTime * 11) : 1.2) : 0.35;
    }
    leds.current.forEach((m, j) => {
      if (m) m.emissiveIntensity = (Math.floor(clock.elapsedTime * 4) + j * 3) % 5 === 0 ? 1.6 : 0.25;
    });
  });
  // without onSelect the room is a recording to watch, and nothing reacts to the pointer
  const hot = onSelect && {
    onClick: (e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); onSelect({ kind: "desk", id: desk.id }); },
    onPointerOver: (e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); document.body.style.cursor = "pointer"; },
    onPointerOut: () => { document.body.style.cursor = ""; },
  };
  let body: React.ReactNode;
  if (desk.kind === "rack") {
    body = (
      <group>
        <RoundedBox args={[0.95, 2.1, 0.8]} radius={0.04} position={[0, 1.05, 0]} castShadow>
          <Mat color="#1c2130" metalness={0.4} />
        </RoundedBox>
        {Array.from({ length: 6 }, (_, i) => (
          <mesh key={i} position={[0.3, 0.42 + i * 0.3, 0.41]}>
            <boxGeometry args={[0.06, 0.06, 0.02]} />
            <meshStandardMaterial ref={(m: THREE.MeshStandardMaterial | null) => { if (m) leds.current[i] = m; }} color="#34b98a" emissive="#34b98a" emissiveIntensity={0.5} />
          </mesh>
        ))}
      </group>
    );
  } else if (desk.kind === "cabinet") {
    body = (
      <RoundedBox args={[0.85, 1.35, 0.7]} radius={0.03} position={[0, 0.68, 0]} castShadow>
        <Mat color="#a9afb8" metalness={0.3} />
      </RoundedBox>
    );
  } else {
    body = (
      <group>
        <RoundedBox args={[1.95, 0.08, 0.92]} radius={0.03} position={[0, 0.82, 0]} castShadow receiveShadow>
          <Mat color="#d8dce4" />
        </RoundedBox>
        <mesh position={[0, 0.39, -0.02]} castShadow>
          <boxGeometry args={[1.88, 0.76, 0.86]} />
          <Mat color="#7d5638" />
        </mesh>
        {desk.kind !== "board" && (
          <group position={[0.25, 0, -0.18]}>
            <mesh position={[0, 0.98, 0]}><boxGeometry args={[0.08, 0.26, 0.08]} /><Mat color="#20242f" /></mesh>
            <RoundedBox args={[1.0, 0.6, 0.06]} radius={0.02} position={[0, 1.34, 0]}>
              <meshStandardMaterial ref={screen} color="#0f1422" emissive="#1a2236" emissiveIntensity={0.35} />
            </RoundedBox>
          </group>
        )}
        {desk.kind === "books" && ["#3a66e8", "#2aa0c0", "#f5a524", "#3ecf8e"].map((c, i) => (
          <mesh key={c} position={[-0.7 + i * 0.12, 1.02, 0]} castShadow><boxGeometry args={[0.1, 0.34 - i * 0.03, 0.26]} /><Mat color={c} /></mesh>
        ))}
        {desk.kind === "images" && [0, 1, 2].map((i) => (
          <RoundedBox key={i} args={[0.3, 0.2, 0.3]} radius={0.02} position={[-0.65, 0.96 + i * 0.21, 0.05]} castShadow><Mat color="#5687e6" /></RoundedBox>
        ))}
        {desk.kind === "board" && (
          <group position={[0, 2.0, -0.45]}>
            <RoundedBox args={[1.8, 1.05, 0.05]} radius={0.02}><Mat color="#f4f6f8" /></RoundedBox>
            <mesh position={[-0.2, 0.2, 0.03]}><boxGeometry args={[1.0, 0.05, 0.01]} /><Mat color="#5687e6" /></mesh>
            <mesh position={[0, -0.05, 0.03]}><boxGeometry args={[0.7, 0.05, 0.01]} /><Mat color="#ef5d70" /></mesh>
          </group>
        )}
      </group>
    );
  }
  const plate = selected ? "bg-primary text-primary-foreground" : tone === "go" ? "bg-success text-white" : tone === "stop" ? "bg-destructive text-white" : tone === "cue" ? "bg-warning text-black" : tone === "plain" ? "bg-[#dfe8ff] text-slate-900" : "bg-white/90 text-slate-900 hover:bg-white";
  return (
    <group position={[desk.x, 0, DESK_Z]} {...hot}>
      {body}
      <Html position={[0, 2.95, -0.3]} center zIndexRange={[20, 0]}>
        <button disabled={!onSelect} onClick={() => onSelect?.({ kind: "desk", id: desk.id })} className={`whitespace-nowrap rounded-md px-2.5 py-1 text-[12px] font-semibold shadow-md ring-1 ring-black/20 transition-colors ${plate} ${onSelect ? "" : "pointer-events-none"}`}>
          {desk.label}
        </button>
      </Html>
    </group>
  );
}

// ---------------------------------------------------------------------------- people

type View = { activity: string; tone: Tone; bubble: string; task: string; badge: Tone | "" };

function Person({ actor, onSelect, selected }: { actor: Actor; onSelect?: (s: Selection) => void; selected: boolean }) {
  const group = useRef<THREE.Group>(null);
  const legL = useRef<THREE.Group>(null);
  const legR = useRef<THREE.Group>(null);
  const armL = useRef<THREE.Group>(null);
  const armR = useRef<THREE.Group>(null);
  const chip = useRef<THREE.Group>(null);
  const [hover, setHover] = useState(false);
  const [view, setView] = useState<View>({ activity: actor.activity, tone: actor.activityTone, bubble: "", task: "", badge: "" });
  const c = look(actor.id);
  useFrame(({ clock }) => {
    const now = performance.now();
    const g = group.current;
    if (!g) return;
    const moving = Math.hypot(actor.tx - actor.x, actor.tz - actor.z) > 0.01;
    g.position.set(actor.x, moving ? Math.abs(Math.sin(clock.elapsedTime * 9)) * 0.04 : 0, actor.z);
    if (chip.current) chip.current.position.y = THREE.MathUtils.lerp(chip.current.position.y, 2.0 + actor.lift * 0.8, 0.15);
    let diff = actor.facing - g.rotation.y;
    diff = Math.atan2(Math.sin(diff), Math.cos(diff));
    g.rotation.y += diff * 0.2;
    const swing = moving ? Math.sin(clock.elapsedTime * 9) * 0.6 : 0;
    const typing = !moving && actor.busyUntil > now;
    if (legL.current) legL.current.rotation.x = swing;
    if (legR.current) legR.current.rotation.x = -swing;
    if (armL.current) armL.current.rotation.x = typing ? -1.1 + Math.sin(clock.elapsedTime * 14) * 0.15 : -swing * 0.8;
    if (armR.current) armR.current.rotation.x = typing ? -1.1 + Math.cos(clock.elapsedTime * 14) * 0.15 : swing * 0.8;
    const bubble = actor.bubble && actor.bubble.until > now ? actor.bubble.text : "";
    const task = actor.task && !bubble ? `${actor.task.from}: ${actor.task.text}` : "";
    const badge = actor.badge && actor.badge.until > now ? actor.badge.tone : "";
    if (view.activity !== actor.activity || view.tone !== actor.activityTone || view.bubble !== bubble || view.task !== task || view.badge !== badge) {
      setView({ activity: actor.activity, tone: actor.activityTone, bubble, task, badge });
    }
  });
  const hot = onSelect && {
    onClick: (e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); onSelect({ kind: "actor", id: actor.id }); },
    onPointerOver: (e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); setHover(true); document.body.style.cursor = "pointer"; },
    onPointerOut: () => { setHover(false); document.body.style.cursor = ""; },
  };
  const limb =(ref: React.RefObject<THREE.Group | null>, x: number, y: number, w: number, len: number, color: number) => (
    <group ref={ref} position={[x, y, 0]}>
      <RoundedBox args={[w, len, w * 1.1]} radius={0.04} position={[0, -len / 2, 0]} castShadow>
        <Mat color={hex(color)} />
      </RoundedBox>
    </group>
  );
  const dot = actor.kind === "customer" ? "#f5a524" : actor.kind === "verifier" ? "#3ecf8e" : hex(c.shirt);
  return (
    <group ref={group} {...hot}>
      {limb(legL, -0.12, 0.52, 0.18, 0.52, c.pants)}
      {limb(legR, 0.12, 0.52, 0.18, 0.52, c.pants)}
      <RoundedBox args={[0.52, 0.6, 0.3]} radius={0.08} position={[0, 0.82, 0]} castShadow><Mat color={hex(c.shirt)} /></RoundedBox>
      {limb(armL, -0.34, 1.06, 0.14, 0.5, c.shirt)}
      {limb(armR, 0.34, 1.06, 0.14, 0.5, c.shirt)}
      <RoundedBox args={[0.4, 0.4, 0.38]} radius={0.09} position={[0, 1.32, 0]} castShadow><Mat color={hex(c.skin)} /></RoundedBox>
      <RoundedBox args={[0.42, 0.12, 0.4]} radius={0.05} position={[0, 1.54, -0.01]} castShadow><Mat color={hex(c.hair)} /></RoundedBox>
      <mesh position={[-0.08, 1.35, 0.195]}><boxGeometry args={[0.06, 0.06, 0.01]} /><Mat color="#141414" /></mesh>
      <mesh position={[0.08, 1.35, 0.195]}><boxGeometry args={[0.06, 0.06, 0.01]} /><Mat color="#141414" /></mesh>
      {actor.kind === "customer" && <mesh position={[0, 1.64, 0]} castShadow><cylinderGeometry args={[0.32, 0.32, 0.05, 24]} /><Mat color="#2b1d12" /></mesh>}
      {actor.kind === "verifier" && <RoundedBox args={[0.28, 0.36, 0.04]} radius={0.01} position={[0.38, 0.72, 0.16]}><Mat color="#8b5a2b" /></RoundedBox>}
      {(hover || selected) && (
        <mesh rotation-x={-Math.PI / 2} position={[0, 0.03, 0]}>
          <ringGeometry args={[0.5, 0.64, 40]} />
          <meshBasicMaterial color={selected ? "#6f95ff" : "#ffffff"} transparent opacity={selected ? 0.95 : 0.5} />
        </mesh>
      )}
      <group ref={chip} position={[0, 2.0, 0]}>
      <Html center zIndexRange={[30, 10]}>
        <div className="pointer-events-none flex w-max flex-col items-center gap-1">
          {view.bubble && <div className="max-w-[240px] rounded-xl border-2 border-slate-900 bg-[#fffdf6] px-3 py-1.5 text-center text-[13px] font-medium leading-snug text-slate-900 shadow-lg">{view.bubble}</div>}
          {!view.bubble && view.task && <div className="max-w-[230px] rounded-lg bg-warning px-2.5 py-1 text-center text-[12px] font-semibold leading-snug text-black shadow-md">Task from {view.task}</div>}
          <button
            disabled={!onSelect}
            onClick={() => onSelect?.({ kind: "actor", id: actor.id })}
            className={`flex items-center gap-1.5 rounded-md px-2 py-[3px] text-[12px] font-semibold shadow-md ring-1 ring-black/30 ${onSelect ? "pointer-events-auto" : ""} ${selected ? "bg-primary text-primary-foreground" : "bg-slate-900/85 text-white hover:bg-slate-900"}`}
          >
            <span className="size-2 rounded-full" style={{ background: dot }} />
            {actor.label}
            {view.badge === "go" && <span className="text-success">✓</span>}
            {view.badge === "stop" && <span className="text-destructive">✕</span>}
          </button>
          {/* two short lines, not one long one: seats are about one name chip apart, and a wide pill covers the neighbour's */}
          <div className="line-clamp-2 max-w-[112px] rounded px-1.5 py-0.5 text-center text-[11px] font-semibold leading-tight text-balance wrap-anywhere shadow" style={{ background: `${TONE_HEX[view.tone]}e6`, color: view.tone === "cue" || view.tone === "plain" ? "#0f1012" : "#fff" }}>
            {view.activity}
          </div>
        </div>
      </Html>
      </group>
    </group>
  );
}

// ---------------------------------------------------------------------------- links, flights, door, clock

function Links({ model }: { model: RoomModel }) {
  const [links, setLinks] = useState<{ key: string; a: Actor; b: Actor }[]>([]);
  const lines = useRef<Record<string, { material?: { dashOffset: number } } | null>>({});
  useFrame(({ clock }) => {
    const now = performance.now();
    const live = model.links
      .filter((l) => l.until > now)
      .map((l) => ({ key: `${l.a}-${l.b}-${l.until}`, a: model.actors.get(l.a), b: model.actors.get(l.b) }))
      .filter((l): l is { key: string; a: Actor; b: Actor } => !!l.a && !!l.b);
    if (live.map((l) => l.key).join() !== links.map((l) => l.key).join()) setLinks(live);
    Object.values(lines.current).forEach((line) => {
      if (line?.material) line.material.dashOffset = -clock.elapsedTime * 1.5;
    });
  });
  return (
    <>
      {links.map((l) => (
        <QuadraticBezierLine
          key={l.key}
          ref={(r: unknown) => { lines.current[l.key] = r as { material?: { dashOffset: number } } | null; }}
          start={[l.a.x, 1.15, l.a.z]}
          end={[l.b.x, 1.15, l.b.z]}
          mid={[(l.a.x + l.b.x) / 2, 2.4, (l.a.z + l.b.z) / 2]}
          color="#6f95ff"
          lineWidth={3}
          dashed
          dashScale={6}
          dashSize={1}
          gapSize={0.6}
        />
      ))}
    </>
  );
}

function Flights({ model }: { model: RoomModel }) {
  const [items, setItems] = useState<{ key: string; label?: string }[]>([]);
  const groups = useRef<Record<string, THREE.Group | null>>({});
  useFrame(() => {
    const now = performance.now();
    model.flights = model.flights.filter((f) => now - f.start < (f.label ? 1800 : 1000));
    const keyed = model.flights.map((f) => ({ key: `${f.start}-${f.fx}-${f.tx}`, label: f.label, f }));
    if (keyed.map((k) => k.key).join() !== items.map((k) => k.key).join()) setItems(keyed.map(({ key, label }) => ({ key, label })));
    keyed.forEach(({ key, f }) => {
      const g = groups.current[key];
      if (!g) return;
      const t = Math.min(1, (now - f.start) / (f.label ? 1800 : 1000));
      g.position.set(f.fx + (f.tx - f.fx) * t, 1.4 + Math.sin(t * Math.PI) * 1.6, f.fz + (f.tz - f.fz) * t);
      g.rotation.y = t * 6;
    });
  });
  return (
    <>
      {items.map((it) => (
        <group key={it.key} ref={(g) => { groups.current[it.key] = g; }}>
          <RoundedBox args={[0.36, 0.06, 0.26]} radius={0.02} castShadow><Mat color="#fbf8ef" /></RoundedBox>
          {it.label && (
            <Html position={[0, 0.4, 0]} center zIndexRange={[40, 20]}>
              <div className="pointer-events-none whitespace-nowrap rounded-md bg-[#dfe8ff] px-2 py-0.5 text-[12px] font-semibold text-slate-900 shadow-md">{it.label}</div>
            </Html>
          )}
        </group>
      ))}
    </>
  );
}

function Door({ model, doorRef }: { model: RoomModel; doorRef: React.RefObject<THREE.Group | null> }) {
  useFrame(() => {
    if (doorRef.current) doorRef.current.rotation.y = THREE.MathUtils.lerp(doorRef.current.rotation.y, performance.now() < model.doorOpenUntil ? -1.2 : 0, 0.1);
  });
  return null;
}

function Clock({ model, queue, onBeat, bump }: { model: React.RefObject<RoomModel>; queue: React.RefObject<RhEvent[]>; onBeat?: (ev: RhEvent) => void; bump: () => void }) {
  const next = useRef(0);
  const last = useRef(performance.now());
  useFrame(() => {
    const m = model.current;
    const now = performance.now();
    if (queue.current.length && now >= next.current) {
      const ev = queue.current.shift()!;
      const before = m.version + m.actors.size;
      m.apply(ev, now);
      onBeat?.(ev);
      if (m.version + m.actors.size !== before) bump();
      next.current = now + (queue.current.length > 3 ? 300 : 1000);
    }
    m.step(Math.max(0, now - last.current), false, now);
    last.current = now;
  });
  return null;
}

// ---------------------------------------------------------------------------- component

const VIEW_DIR = new THREE.Vector3(0, 11.1, 14.5).normalize();
// what must stay in frame: [x, y, z, half width incl. activity pill] for the desk row ends, the validator's corner, the outer seats, and the door in episodes
const KEEP: Record<"compiler" | "episode", [number, number, number, number][]> = {
  compiler: [[3.5, 2.9, 1.3, 0.4], [18.4, 2.9, 1.3, 0.4], [3.6, 2.2, 7.6, 1.9], [16.4, 2.2, 7.4, 1.9]],
  episode: [[3.5, 2.9, 1.3, 0.4], [18.4, 2.9, 1.3, 0.4], [3.6, 2.2, 7.6, 1.9], [16.4, 2.2, 7.4, 1.9], [20.6, 2.2, 2.9, 1.9]],
};
const targetOf = (mode: "compiler" | "episode") => {
  const pts = KEEP[mode];
  return new THREE.Vector3((Math.min(...pts.map((p) => p[0] - p[3])) + Math.max(...pts.map((p) => p[0] + p[3]))) / 2, 0.4, 5.6);
};

/** Pulls the camera back just far enough that every desk, person, and name chip fits the canvas width. */
function FitCamera({ mode }: { mode: "compiler" | "episode" }) {
  const camera = useThree((st) => st.camera);
  const size = useThree((st) => st.size);
  useEffect(() => {
    const cam = camera as THREE.PerspectiveCamera;
    const halfWidth = Math.tan(THREE.MathUtils.degToRad(cam.fov / 2)) * (size.width / Math.max(1, size.height));
    const target = targetOf(mode);
    // a point closer to the camera than the target sees a narrower slice, so it needs the camera further back
    const need = KEEP[mode].map(([x, y, z, half]) => (Math.abs(x - target.x) + half) / halfWidth + (y - target.y) * VIEW_DIR.y + (z - target.z) * VIEW_DIR.z);
    const d = THREE.MathUtils.clamp(Math.max(...need), 16, 40);
    cam.position.copy(target).addScaledVector(VIEW_DIR, d);
    cam.lookAt(target); // OrbitControls re-reads the camera position on its next update
  }, [camera, size.width, size.height, mode]);
  return null;
}

export function Stage({
  events,
  mode,
  label,
  onBeat,
  onSelect,
  selected,
  height = "min(54vw, 60vh)",
}: {
  events: RhEvent[];
  mode: "episode" | "compiler";
  label: string;
  onBeat?: (ev: RhEvent) => void;
  onSelect?: (s: Selection | null) => void;
  selected?: Selection | null;
  height?: string;
}) {
  const model = useRef<RoomModel>(new RoomModel(mode));
  const applied = useRef(0);
  const queue = useRef<RhEvent[]>([]);
  const [, setVersion] = useState(0);
  const bump = () => setVersion((v) => v + 1);
  const doorRef = useRef<THREE.Group>(null);
  const [banner, setBanner] = useState<{ text: string; tone: Tone } | null>(null);
  // drei <Html> labels mounted in the canvas's first commit can lose their DOM to a React 19 root race; mount them after the first frame
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (model.current.mode !== mode || events.length < applied.current) {
      model.current = new RoomModel(mode);
      applied.current = 0;
      queue.current = [];
      bump();
    }
    const fresh = events.slice(applied.current);
    applied.current = events.length;
    // history lands instantly; only the newest beats animate so the room never lags
    const past = performance.now() - 600_000;
    const pending = [...queue.current, ...fresh];
    const before = model.current.version + model.current.actors.size;
    pending.slice(0, Math.max(0, pending.length - 6)).forEach((e) => model.current.apply(e, past));
    queue.current = pending.slice(-6);
    if (model.current.version + model.current.actors.size !== before) bump();
  }, [events, mode]);

  useEffect(() => {
    const t = setInterval(() => {
      const b = model.current.banner;
      const active = b && b.until > performance.now() ? { text: b.text, tone: b.tone } : null;
      setBanner((cur) => (cur?.text === active?.text ? cur : active));
    }, 250);
    return () => clearInterval(t);
  }, []);

  const select = (s: Selection | null) => onSelect?.(s);
  const m = model.current;
  return (
    <div className="relative overflow-hidden rounded-xl border bg-[#08090a]" style={{ height }} role="img" aria-label={label}>
      <Canvas shadows dpr={[1, 2]} camera={{ position: [12, 11.5, 20.5], fov: 30 }} onPointerMissed={() => select(null)} onCreated={() => requestAnimationFrame(() => setReady(true))}>
        <color attach="background" args={["#08090a"]} />
        <hemisphereLight args={["#dfe8ff", "#3a2a1c", 0.55]} />
        <directionalLight position={[4, 16, 14]} intensity={1.8} castShadow shadow-mapSize={[2048, 2048]} shadow-camera-left={-16} shadow-camera-right={16} shadow-camera-top={12} shadow-camera-bottom={-12} shadow-bias={-0.0004} />
        <Environment resolution={256} frames={1}>
          <Lightformer intensity={2.2} position={[0, 6, 10]} scale={[18, 6, 1]} color="#fff2dd" />
          <Lightformer intensity={1.4} position={[-10, 3, 4]} rotation-y={Math.PI / 2} scale={[10, 4, 1]} color="#bcd6ff" />
          <Lightformer intensity={0.8} position={[10, 3, 4]} rotation-y={-Math.PI / 2} scale={[10, 4, 1]} color="#ffd9a8" />
        </Environment>
        <Room mode={mode} doorRef={doorRef} />
        {ready && m.desks.map((d) => (
          <DeskPiece key={`${d.id}-${m.version}`} desk={d} model={m} onSelect={onSelect && select} selected={selected?.kind === "desk" && selected.id === d.id} />
        ))}
        {ready && [...m.actors.values()].map((a) => (
          <Person key={a.id} actor={a} onSelect={onSelect && select} selected={selected?.kind === "actor" && selected.id === a.id} />
        ))}
        <Links model={m} />
        <Flights model={m} />
        <Door model={m} doorRef={doorRef} />
        <ContactShadows position={[12, 0.02, 6.5]} scale={30} opacity={0.35} blur={2.4} far={4} />
        <Clock model={model} queue={queue} onBeat={onBeat} bump={bump} />
        <FitCamera mode={mode} />
        <OrbitControls makeDefault target={targetOf(mode)} enablePan={false} enableZoom={false} enableDamping minDistance={12} maxDistance={44} minPolarAngle={0.45} maxPolarAngle={1.2} minAzimuthAngle={-0.8} maxAzimuthAngle={0.8} />
      </Canvas>
      {banner && (
        <div className={`pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-lg px-4 py-1.5 text-sm font-semibold shadow-lg ${banner.tone === "go" ? "bg-success text-white" : banner.tone === "stop" ? "bg-destructive text-white" : "bg-primary text-primary-foreground"}`}>
          {banner.text}
        </div>
      )}
      <div className="pointer-events-none absolute bottom-2 right-3 text-xs text-white/50">{onSelect ? "Click a person or desk to inspect; drag to look around" : "Drag to look around"}</div>
    </div>
  );
}
