/** How each actor looks, derived from its id so the 3D figure and the log avatar always match. */

const SHIRTS = [0x2f64d6, 0xc4413a, 0x2c8a5a, 0x8a5cc9, 0xe08a2c, 0x1f9aa6, 0x6d4c41, 0xd94f8a];
const SKIN = [0xf1c9a5, 0xd9a47c, 0xa8724d, 0x7a4e30, 0xe8b893];
const HAIR = [0x2b1d12, 0x5a3a22, 0xc89b45, 0x1d1a14, 0x8b5a2b, 0xb0b0b0];

export interface Look {
  shirt: number;
  skin: number;
  hair: number;
  pants: number;
}

function hash(s: string) {
  let h = 7;
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h;
}

export function look(id: string): Look {
  const h = hash(id);
  const base = { skin: SKIN[(h >>> 3) % SKIN.length], hair: HAIR[(h >>> 5) % HAIR.length], pants: 0x30384a };
  if (id === "verifier" || id === "validator") return { ...base, shirt: 0xf4f1e8, pants: 0x3a3f4a };
  if (id === "customer") return { ...base, shirt: 0xe9b319 };
  return { ...base, shirt: SHIRTS[h % SHIRTS.length] };
}

const hex = (n: number) => "#" + n.toString(16).padStart(6, "0");
const cache = new Map<string, string>();

/** Front view of the voxel head and shoulders, as an SVG data URL. */
export function avatar(id: string): string {
  const hit = cache.get(id);
  if (hit) return hit;
  const c = look(id);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" shape-rendering="crispEdges">
<rect width="16" height="16" fill="#1c1d22"/><rect x="2" y="12" width="12" height="4" fill="${hex(c.shirt)}"/>
<rect x="4" y="3" width="8" height="8" fill="${hex(c.skin)}"/><rect x="4" y="2" width="8" height="2" fill="${hex(c.hair)}"/>
<rect x="6" y="6" width="1" height="1" fill="#1d1a14"/><rect x="9" y="6" width="1" height="1" fill="#1d1a14"/></svg>`;
  const url = "data:image/svg+xml," + encodeURIComponent(svg);
  cache.set(id, url);
  return url;
}
