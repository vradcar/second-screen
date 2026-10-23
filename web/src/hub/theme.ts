/**
 * Team colours for data marks. A club's kit colour can be too dark or too light to read as a
 * chart mark, so each is moved into a validated lightness band (OKLCH L 0.52-0.62) keeping its hue;
 * if the two teams' hues are too close to tell apart, the away side switches to amber.
 * Checked with the dataviz palette validator: Halcyon #2F6BC4 / Redmarsh #C4352B pass every check on
 * light and dark surfaces.
 */
import type { Meta } from "../types";

type Lch = [number, number, number];

function toLinear(c: number) { return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; }
function toSrgb(c: number) { return c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055; }

function hexToOklch(hex: string): Lch {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => toLinear(v / 255));
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  return [L, Math.hypot(A, B), (Math.atan2(B, A) * 180) / Math.PI];
}

function oklchToHex([L, C, H]: Lch): string {
  const a = C * Math.cos((H * Math.PI) / 180), b = C * Math.sin((H * Math.PI) / 180);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const rgb = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
               -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
               -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
  return "#" + rgb.map((v) => Math.round(Math.min(1, Math.max(0, toSrgb(v))) * 255).toString(16).padStart(2, "0")).join("");
}

export function dataColor(hex: string): string {
  const [L, C, H] = hexToOklch(hex);
  return oklchToHex([Math.min(0.62, Math.max(0.52, L)), Math.max(C, 0.13), H]);
}

export interface TeamInk { home: string; away: string; of: (teamId: string | null | undefined) => string }

export function teamInk(meta: Meta): TeamInk {
  const home = dataColor(meta.home.colors[0]);
  let away = dataColor(meta.away.colors[0]);
  const dh = Math.abs(hexToOklch(home)[2] - hexToOklch(away)[2]) % 360;
  if (Math.min(dh, 360 - dh) < 50) away = "#C98A1B";
  return { home, away, of: (id) => (id === meta.away.team_id ? away : home) };
}

/** Text on top of a coloured fill: white or near-black by the fill's lightness. */
export function inkOn(hex: string): string {
  return hexToOklch(hex)[0] > 0.66 ? "#141b24" : "#ffffff";
}
