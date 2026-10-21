import type { MatchEvent, Team } from "./types";

/** Ball keyframes from the event feed: where the ball is at each event, and where it ends up. */
export interface Key { t: number; x: number; y: number }

const TRAVEL: Record<string, (e: MatchEvent) => number> = {
  pass: (e) => (e.distance_m ?? 10) / Math.max((e.ball_speed_kmh ?? 40) / 3.6, 5),
  carry: (e) => (e.distance_m ?? 6) / Math.max((e.speed_kmh ?? 20) / 3.6, 3),
  shot: (e) => 0.5 + (e.distance_m ?? 15) / 40,
  clearance: () => 1.4,
};

export function ballKeys(events: MatchEvent[]): Key[] {
  const keys: Key[] = [];
  for (const e of events) {
    if (e.x === undefined || e.y === undefined) continue;
    if (e.type === "physical_snapshot" || e.type === "possession_change") continue;
    keys.push({ t: e.elapsed_seconds, x: e.x, y: e.y });
    if (e.end_x !== undefined && e.end_y !== undefined) {
      const dur = (TRAVEL[e.type] ?? (() => 1))(e);
      keys.push({ t: e.elapsed_seconds + Math.min(dur, 4), x: e.end_x, y: e.end_y });
    }
  }
  keys.sort((a, b) => a.t - b.t);
  return keys;
}

export function ballAt(keys: Key[], t: number): { x: number; y: number } {
  if (!keys.length) return { x: 52.5, y: 34 };
  let lo = 0, hi = keys.length - 1;
  if (t <= keys[0].t) return keys[0];
  if (t >= keys[hi].t) return keys[hi];
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (keys[mid].t <= t) lo = mid; else hi = mid;
  }
  const a = keys[lo], b = keys[hi];
  const f = b.t === a.t ? 1 : (t - a.t) / (b.t - a.t);
  const s = f * f * (3 - 2 * f); // ease so passes look struck, not slid
  return { x: a.x + (b.x - a.x) * s, y: a.y + (b.y - a.y) * s };
}

/** 4-3-3 base positions in the attacking frame (x: own goal 0 -> opponent goal 105). */
const BASE: Record<string, [number, number][]> = {
  GK: [[5, 34]], RB: [[33, 9]], LB: [[33, 59]], CB: [[24, 25], [24, 43]], DM: [[40, 34]],
  CM: [[52, 22], [52, 46]], RW: [[74, 10]], LW: [[74, 58]], ST: [[80, 34]],
};

export interface Slot { player_id: string; number: number; name: string; position: string; base: [number, number] }

export function lineupSlots(team: Team): Slot[] {
  const used: Record<string, number> = {};
  return team.starting_xi.map((p) => {
    const i = used[p.position] ?? 0;
    used[p.position] = i + 1;
    const opts = BASE[p.position] ?? [[50, 34]];
    return { player_id: p.player_id, number: p.number, name: p.name, position: p.position, base: opts[Math.min(i, opts.length - 1)] };
  });
}

/**
 * Where a player should be: the team shape slides with the ball, compresses toward it,
 * and pushes up in possession. Returns absolute pitch coordinates.
 */
export function shapePosition(slot: Slot, homeSide: boolean, ballAbsX: number, ballAbsY: number,
                              inPossession: boolean, t: number, idx: number): { x: number; y: number } {
  const bx = homeSide ? ballAbsX : 105 - ballAbsX;          // ball in this team's attacking frame
  const by = homeSide ? ballAbsY : 68 - ballAbsY;
  const [baseX, baseY] = slot.base;
  let x: number, y: number;
  if (slot.position === "GK") {
    x = 4 + Math.max(0, bx - 52.5) * 0.12;
    y = 34 + (by - 34) * 0.15;
  } else {
    const shift = (bx - 52.5) * 0.62 + (inPossession ? 7 : -7);
    x = baseX * 0.72 + 14 + shift;
    y = baseY + (by - baseY) * (inPossession ? 0.18 : 0.32);
    x = Math.max(3, Math.min(101, x));
    y = Math.max(2, Math.min(66, y));
  }
  // A little idle movement so the picture breathes.
  x += Math.sin(t * 0.7 + idx * 1.9) * 0.9;
  y += Math.cos(t * 0.6 + idx * 2.3) * 0.9;
  return homeSide ? { x, y } : { x: 105 - x, y: 68 - y };
}
