/** Canvas drawing for the broadcast: pitch, action traces, players, ball, tags. */
import type { MatchEvent } from "./types";

export interface View { ox: number; oy: number; pw: number; ph: number; m: number }
export const sx = (v: View, x: number) => v.ox + (x / 105) * v.pw;
export const sy = (v: View, y: number) => v.oy + ((68 - y) / 68) * v.ph;

export function layout(W: number, H: number): View {
  const pw = Math.min(W * 0.92, (H * 0.86) * 105 / 68), ph = pw * 68 / 105;
  return { ox: (W - pw) / 2, oy: (H - ph) / 2 + H * 0.03, pw, ph, m: pw / 105 };
}

export function drawPitch(g: CanvasRenderingContext2D, v: View, W: number, H: number) {
  const sky = g.createLinearGradient(0, 0, 0, H);
  sky.addColorStop(0, "#1d2a24"); sky.addColorStop(1, "#24352b");
  g.fillStyle = sky; g.fillRect(0, 0, W, H);
  for (let i = 0; i < 12; i++) {
    g.fillStyle = i % 2 ? "#2f6b3b" : "#34763f";
    g.fillRect(v.ox + (v.pw / 12) * i, v.oy, v.pw / 12 + 1, v.ph);
  }
  const glow = g.createRadialGradient(W / 2, v.oy + v.ph / 2, v.ph * 0.1, W / 2, v.oy + v.ph / 2, v.pw * 0.75);
  glow.addColorStop(0, "rgba(255,255,240,0.06)"); glow.addColorStop(1, "rgba(0,0,0,0.25)");
  g.fillStyle = glow; g.fillRect(v.ox, v.oy, v.pw, v.ph);
  const line = "rgba(240,246,236,0.82)";
  g.strokeStyle = line; g.lineWidth = Math.max(1, v.m * 0.14);
  g.strokeRect(v.ox, v.oy, v.pw, v.ph);
  g.beginPath(); g.moveTo(sx(v, 52.5), sy(v, 0)); g.lineTo(sx(v, 52.5), sy(v, 68)); g.stroke();
  g.beginPath(); g.arc(sx(v, 52.5), sy(v, 34), 9.15 * v.m, 0, Math.PI * 2); g.stroke();
  for (const side of [0, 1]) {
    g.strokeRect(sx(v, side ? 88.5 : 0), sy(v, 54.16), 16.5 * v.m, 40.32 * v.m);
    g.strokeRect(sx(v, side ? 99.5 : 0), sy(v, 43.16), 5.5 * v.m, 18.32 * v.m);
    g.fillStyle = line; g.beginPath(); g.arc(sx(v, side ? 94 : 11), sy(v, 34), v.m * 0.35, 0, Math.PI * 2); g.fill();
    g.strokeStyle = "rgba(240,246,236,0.95)"; g.lineWidth = v.m * 0.5;
    g.beginPath(); g.moveTo(sx(v, side ? 105 : 0), sy(v, 30.34)); g.lineTo(sx(v, side ? 105 : 0), sy(v, 37.66)); g.stroke();
    g.strokeStyle = line; g.lineWidth = Math.max(1, v.m * 0.14);
  }
}

export const PASS_OK = "#6CF09A";
export const PASS_BAD = "#FF5A4E";
const SHOT_GOAL = "#F2C14E";

export interface Trace { e: MatchEvent; dur: number }

/** A pass/shot line that grows with the ball's flight, then fades. */
export function drawTrace(g: CanvasRenderingContext2D, v: View, tr: Trace, t: number, fade: number) {
  const e = tr.e;
  if (e.x === undefined || e.y === undefined || e.end_x === undefined || e.end_y === undefined) return;
  const since = t - e.elapsed_seconds;
  if (since < 0) return;
  const p = Math.min(since / Math.max(tr.dur, 0.05), 1);
  const after = since - tr.dur;
  const alpha = after <= 0 ? 1 : Math.max(0, 1 - after / fade);
  if (alpha <= 0) return;
  const x0 = sx(v, e.x), y0 = sy(v, e.y);
  const x1 = x0 + (sx(v, e.end_x) - x0) * p, y1 = y0 + (sy(v, e.end_y) - y0) * p;
  const shot = e.type === "shot";
  const ok = shot ? e.outcome === "goal" : e.outcome === "complete";
  const color = shot ? (ok ? SHOT_GOAL : "#F3F5EE") : ok ? PASS_OK : PASS_BAD;
  const width = Math.max(2.5, v.m * (shot ? 0.5 : 0.42));
  g.save();
  g.globalAlpha = alpha;
  g.lineCap = "round";
  g.setLineDash(e.height === "high" || e.outcome === "out" || (shot && !ok) ? [width * 2.2, width * 1.6] : []);
  g.strokeStyle = "rgba(10,20,14,0.55)"; g.lineWidth = width + 2.5;           // dark halo so it reads on turf
  g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke();
  g.strokeStyle = color; g.lineWidth = width;
  g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke();
  g.setLineDash([]);
  if (p >= 1) {
    const ang = Math.atan2(y1 - y0, x1 - x0), a = width * 3.2;
    if (ok || shot) {
      g.fillStyle = color; g.beginPath();
      g.moveTo(x1, y1); g.lineTo(x1 - a * Math.cos(ang - 0.45), y1 - a * Math.sin(ang - 0.45));
      g.lineTo(x1 - a * Math.cos(ang + 0.45), y1 - a * Math.sin(ang + 0.45)); g.closePath(); g.fill();
    } else {                                                                     // a cross where it was lost
      g.strokeStyle = color; g.lineWidth = width;
      g.beginPath(); g.moveTo(x1 - a / 1.6, y1 - a / 1.6); g.lineTo(x1 + a / 1.6, y1 + a / 1.6);
      g.moveTo(x1 + a / 1.6, y1 - a / 1.6); g.lineTo(x1 - a / 1.6, y1 + a / 1.6); g.stroke();
    }
  }
  g.restore();
}

export function drawBall(g: CanvasRenderingContext2D, v: View, pts: { x: number; y: number }[], moving: boolean) {
  const r = Math.max(4.5, v.m * 0.95);
  // Trail: where the ball just was.
  for (let i = pts.length - 1; i >= 1; i--) {
    const a = 0.35 * (1 - i / pts.length);
    g.fillStyle = `rgba(255,255,250,${a})`;
    g.beginPath(); g.arc(sx(v, pts[i].x), sy(v, pts[i].y), r * (1 - i / (pts.length + 2)), 0, Math.PI * 2); g.fill();
  }
  const bx = sx(v, pts[0].x), by = sy(v, pts[0].y);
  g.fillStyle = "rgba(0,0,0,0.35)"; g.beginPath(); g.ellipse(bx + 2.5, by + 3.5, r * 1.05, r * 0.7, 0, 0, Math.PI * 2); g.fill();
  if (moving) {
    g.strokeStyle = "rgba(255,255,240,0.55)"; g.lineWidth = 2;
    g.beginPath(); g.arc(bx, by, r + 4, 0, Math.PI * 2); g.stroke();
  }
  g.fillStyle = "#FFFFFF"; g.beginPath(); g.arc(bx, by, r, 0, Math.PI * 2); g.fill();
  g.strokeStyle = "#111"; g.lineWidth = 1.6; g.stroke();
  g.fillStyle = "#111"; g.beginPath(); g.arc(bx, by, r * 0.3, 0, Math.PI * 2); g.fill();   // panel, reads as a football
}

export function drawPlayer(g: CanvasRenderingContext2D, v: View, x: number, y: number, colors: [string, string],
                           num: number, ring: string | null, onBall: boolean) {
  const px = sx(v, x), py = sy(v, y), r = Math.max(5.5, v.m * 1.3);
  if (onBall) { g.fillStyle = "rgba(255,255,240,0.22)"; g.beginPath(); g.arc(px, py, r + 7, 0, Math.PI * 2); g.fill(); }
  if (ring) { g.strokeStyle = ring; g.lineWidth = 2.5; g.beginPath(); g.arc(px, py, r + 4.5, 0, Math.PI * 2); g.stroke(); }
  g.fillStyle = "rgba(0,0,0,0.25)"; g.beginPath(); g.ellipse(px + 1.5, py + 2.5, r, r * 0.7, 0, 0, Math.PI * 2); g.fill();
  g.fillStyle = colors[0]; g.beginPath(); g.arc(px, py, r, 0, Math.PI * 2); g.fill();
  g.strokeStyle = colors[1]; g.lineWidth = 1.6; g.stroke();
  g.fillStyle = colors[1]; g.font = `700 ${Math.round(r * 1.05)}px 'Barlow Condensed', sans-serif`;
  g.textAlign = "center"; g.textBaseline = "middle";
  g.fillText(String(num), px, py + 0.5);
}

/** A name tag above a player: team block with label, optional white value block. */
export function drawTag(g: CanvasRenderingContext2D, v: View, x: number, y: number, label: string, value: string,
                        colors: [string, string]) {
  const px = sx(v, x), py = sy(v, y) - Math.max(5.5, v.m * 1.3) - 10;
  g.font = "700 13px 'Barlow Condensed', sans-serif";
  const w1 = g.measureText(label).width + 12;
  g.font = "600 13px 'Barlow Condensed', sans-serif";
  const w2 = value ? g.measureText(value).width + 12 : 0;
  const x0 = px - (w1 + w2) / 2, h = 20;
  g.fillStyle = colors[0]; g.fillRect(x0, py - h, w1, h);
  if (value) { g.fillStyle = "#F7F7F2"; g.fillRect(x0 + w1, py - h, w2, h); }
  g.fillStyle = colors[1].toUpperCase() === "#F5F5F5" ? "#fff" : colors[1];
  g.font = "700 13px 'Barlow Condensed', sans-serif"; g.textAlign = "left"; g.textBaseline = "middle";
  g.fillText(label, x0 + 6, py - h / 2 + 1);
  if (value) { g.fillStyle = "#16202E"; g.font = "600 13px 'Barlow Condensed', sans-serif"; g.fillText(value, x0 + w1 + 6, py - h / 2 + 1); }
  g.fillStyle = colors[0]; g.beginPath(); g.moveTo(px - 4, py); g.lineTo(px + 4, py); g.lineTo(px, py + 5); g.fill();
}
