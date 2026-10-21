import { useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { ballAt, ballKeys, lineupSlots, shapePosition, type Slot } from "./motion";
import { matchTime, type ClockRef } from "./stream";
import { usefulChips } from "./personas";
import type { Cue, MatchEvent, Meta, Moment, Persona, Snapshot } from "./types";

const ON_BALL = new Set(["pass", "carry", "shot", "dribble", "corner", "penalty_awarded", "interception", "tackle", "clearance", "save"]);
const POSSESSION = new Set(["pass", "carry", "shot", "dribble", "possession_start", "corner"]);

interface Props {
  meta: Meta; events: MatchEvent[]; clockRef: MutableRefObject<ClockRef>; snap?: Snapshot;
  cues: Cue[]; moments: Moment[]; persona: Persona;
}

interface Banner { key: string; kind: "goal" | "red"; title: string; sub: string; team: string; line?: string }

export function Broadcast({ meta, events, clockRef, snap, cues, moments, persona }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const keys = useMemo(() => ballKeys(events), [events]);
  const slots = useMemo(() => ({ home: lineupSlots(meta.home), away: lineupSlots(meta.away) }), [meta]);
  const posRef = useRef<Map<string, { x: number; y: number }>>(new Map());
  const [banner, setBanner] = useState<Banner | null>(null);
  const seenRef = useRef<Set<string>>(new Set());

  // Live state derived from events up to "now" (subs, red cards, who's on the ball).
  const liveRef = useRef({ idx: 0, off: new Set<string>(), on: new Map<string, string>(), possession: meta.home.team_id,
                           actor: "" as string, actorTeam: "" });
  useEffect(() => { liveRef.current = { idx: 0, off: new Set(), on: new Map(), possession: meta.home.team_id, actor: "", actorTeam: "" }; }, [meta]);

  const tagCues = useMemo(() => cues.filter((c) => c.persona_id === persona.id && (c.type === "player_tag" || c.type === "stat_pop") && c.player_id), [cues, persona.id]);
  const tagRef = useRef(tagCues); tagRef.current = tagCues;
  const eventsRef = useRef(events); eventsRef.current = events;
  const nameOf = useMemo(() => {
    const m = new Map<string, { name: string; number: number; team: string }>();
    for (const t of [meta.home, meta.away]) for (const p of [...t.starting_xi, ...t.bench]) m.set(p.player_id, { name: p.name, number: p.number, team: t.team_id });
    return m;
  }, [meta]);

  useEffect(() => {
    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const cv = canvasRef.current; if (!cv) return;
      const dpr = window.devicePixelRatio || 1;
      const W = cv.clientWidth, H = cv.clientHeight;
      if (cv.width !== Math.round(W * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
      const g = cv.getContext("2d")!; g.setTransform(dpr, 0, 0, dpr, 0, 0);
      const t = matchTime(clockRef.current);
      const live = liveRef.current, evs = eventsRef.current;
      while (live.idx < evs.length && evs[live.idx].elapsed_seconds <= t) {
        const e = evs[live.idx++];
        if (e.type === "substitution" && e.player_id && e.player_off_id) { live.off.add(e.player_off_id); live.on.set(e.player_off_id, e.player_id); }
        if (e.type === "card" && e.card === "second_yellow" && e.player_id) live.off.add(e.player_id);
        if (e.team_id && POSSESSION.has(e.type)) live.possession = e.team_id;
        if (e.player_id && ON_BALL.has(e.type)) { live.actor = e.recipient_id && e.outcome === "complete" ? e.recipient_id : e.player_id; live.actorTeam = e.team_id ?? ""; }
        if (!seenRef.current.has(e.event_id)) {
          seenRef.current.add(e.event_id);
          if (e.type === "goal" && t - e.elapsed_seconds < 20) {
            const sc = e.score ?? {};
            setBanner({ key: e.event_id, kind: "goal", title: "Goal", team: e.team_id ?? "", sub: e.player_name ?? "",
              line: `${meta.home.short_name} ${sc[meta.home.team_id] ?? 0}–${sc[meta.away.team_id] ?? 0} ${meta.away.short_name}` });
          }
          if (e.type === "card" && e.card === "second_yellow" && t - e.elapsed_seconds < 20) {
            setBanner({ key: e.event_id, kind: "red", title: "Red card", team: e.team_id ?? "", sub: `${e.player_name ?? ""} is sent off` });
          }
        }
      }

      // Pitch geometry
      g.clearRect(0, 0, W, H);
      const pw = Math.min(W * 0.92, (H * 0.86) * 105 / 68), ph = pw * 68 / 105;
      const ox = (W - pw) / 2, oy = (H - ph) / 2 + H * 0.03;
      const sx = (x: number) => ox + (x / 105) * pw, sy = (y: number) => oy + ((68 - y) / 68) * ph;
      const m = pw / 105;

      const sky = g.createLinearGradient(0, 0, 0, H);
      sky.addColorStop(0, "#1d2a24"); sky.addColorStop(1, "#24352b");
      g.fillStyle = sky; g.fillRect(0, 0, W, H);
      for (let i = 0; i < 12; i++) {
        g.fillStyle = i % 2 ? "#2f6b3b" : "#34763f";
        g.fillRect(ox + (pw / 12) * i, oy, pw / 12 + 1, ph);
      }
      const glow = g.createRadialGradient(W / 2, oy + ph / 2, ph * 0.1, W / 2, oy + ph / 2, pw * 0.75);
      glow.addColorStop(0, "rgba(255,255,240,0.06)"); glow.addColorStop(1, "rgba(0,0,0,0.25)");
      g.fillStyle = glow; g.fillRect(ox, oy, pw, ph);

      g.strokeStyle = "rgba(240,246,236,0.82)"; g.lineWidth = Math.max(1, m * 0.14);
      g.strokeRect(ox, oy, pw, ph);
      g.beginPath(); g.moveTo(sx(52.5), sy(0)); g.lineTo(sx(52.5), sy(68)); g.stroke();
      g.beginPath(); g.arc(sx(52.5), sy(34), 9.15 * m, 0, Math.PI * 2); g.stroke();
      for (const side of [0, 1]) {
        const x0 = side ? 105 - 16.5 : 0, x1 = side ? 105 - 5.5 : 0;
        g.strokeRect(sx(x0), sy(34 + 20.16), 16.5 * m, 40.32 * m);
        g.strokeRect(sx(x1), sy(34 + 9.16), 5.5 * m, 18.32 * m);
        g.fillStyle = "rgba(240,246,236,0.82)";
        g.beginPath(); g.arc(sx(side ? 94 : 11), sy(34), m * 0.35, 0, Math.PI * 2); g.fill();
        g.strokeStyle = "rgba(240,246,236,0.95)"; g.lineWidth = m * 0.5;
        g.beginPath(); g.moveTo(sx(side ? 105 : 0), sy(30.34)); g.lineTo(sx(side ? 105 : 0), sy(37.66)); g.stroke();
        g.strokeStyle = "rgba(240,246,236,0.82)"; g.lineWidth = Math.max(1, m * 0.14);
      }

      // Players
      const ball = ballAt(keys, t);
      const positions = posRef.current;
      const teams: [Slot[], boolean, string, [string, string]][] = [
        [slots.home, true, meta.home.team_id, meta.home.colors], [slots.away, false, meta.away.team_id, meta.away.colors]];
      const drawn: { id: string; x: number; y: number }[] = [];
      teams.forEach(([teamSlots, home, tid, colors]) => {
        teamSlots.forEach((slot, i) => {
          if (live.off.has(slot.player_id) && !live.on.has(slot.player_id)) return;
          const pid = live.on.get(slot.player_id) ?? slot.player_id;
          if (live.off.has(pid)) return;
          let target = shapePosition(slot, home, ball.x, ball.y, live.possession === tid, t, i + (home ? 0 : 11));
          if (pid === live.actor) target = { x: ball.x - (home ? 0.9 : -0.9), y: ball.y + 0.6 };
          const cur = positions.get(pid) ?? target;
          const k = pid === live.actor ? 0.35 : 0.08;
          const p = { x: cur.x + (target.x - cur.x) * k, y: cur.y + (target.y - cur.y) * k };
          positions.set(pid, p);
          drawn.push({ id: pid, x: p.x, y: p.y });
          const px = sx(p.x), py = sy(p.y), r = Math.max(5, m * 1.25);
          const focus = persona.focus && nameOf.get(pid)?.name === persona.focus;
          if (focus) { g.strokeStyle = "#F2C14E"; g.lineWidth = 2.5; g.beginPath(); g.arc(px, py, r + 4, 0, Math.PI * 2); g.stroke(); }
          g.fillStyle = "rgba(0,0,0,0.25)"; g.beginPath(); g.ellipse(px + 1.5, py + 2.5, r, r * 0.7, 0, 0, Math.PI * 2); g.fill();
          g.fillStyle = colors[0]; g.beginPath(); g.arc(px, py, r, 0, Math.PI * 2); g.fill();
          g.strokeStyle = colors[1]; g.lineWidth = 1.6; g.stroke();
          g.fillStyle = colors[1]; g.font = `700 ${Math.round(r * 1.05)}px 'Barlow Condensed', sans-serif`;
          g.textAlign = "center"; g.textBaseline = "middle";
          g.fillText(String(nameOf.get(pid)?.number ?? ""), px, py + 0.5);
        });
      });

      // Ball
      const bx = sx(ball.x), by = sy(ball.y);
      g.fillStyle = "rgba(0,0,0,0.3)"; g.beginPath(); g.ellipse(bx + 2, by + 3, m * 0.55, m * 0.38, 0, 0, Math.PI * 2); g.fill();
      g.fillStyle = "#fbfbf7"; g.beginPath(); g.arc(bx, by, Math.max(3, m * 0.55), 0, Math.PI * 2); g.fill();
      g.strokeStyle = "#1a1a1a"; g.lineWidth = 1; g.stroke();

      // Player tags (speed, cards, shot speed) anchored to the player
      const spd = clockRef.current.speed;
      for (const c of tagRef.current) {
        if (t < c.elapsed || t > c.elapsed + c.duration_s * spd) continue;
        const pos = drawn.find((d) => d.id === c.player_id); if (!pos) continue;
        const px = sx(pos.x), py = sy(pos.y) - Math.max(5, m * 1.25) - 10;
        const stat = c.stats[0];
        const label = c.text.strap.split(" ").slice(-1)[0];
        const value = stat ? stat.value : "";
        g.font = "700 13px 'Barlow Condensed', sans-serif";
        const w1 = g.measureText(label).width + 12;
        g.font = "600 13px 'Barlow Condensed', sans-serif";
        const w2 = value ? g.measureText(value).width + 12 : 0;
        const x0 = px - (w1 + w2) / 2, h = 20;
        const team = nameOf.get(c.player_id!)?.team === meta.home.team_id ? meta.home.colors : meta.away.colors;
        g.fillStyle = team[0]; g.fillRect(x0, py - h, w1, h);
        if (value) { g.fillStyle = "#F7F7F2"; g.fillRect(x0 + w1, py - h, w2, h); }
        g.fillStyle = team[1] === "#F5F5F5" ? "#fff" : team[1]; g.font = "700 13px 'Barlow Condensed', sans-serif"; g.textAlign = "left";
        g.fillText(label, x0 + 6, py - h / 2 + 1);
        if (value) { g.fillStyle = "#16202E"; g.font = "600 13px 'Barlow Condensed', sans-serif"; g.fillText(value, x0 + w1 + 6, py - h / 2 + 1); }
        g.fillStyle = team[0]; g.beginPath(); g.moveTo(px - 4, py); g.lineTo(px + 4, py); g.lineTo(px, py + 5); g.fill();
      }
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [keys, slots, meta, clockRef, nameOf, persona.focus]);

  useEffect(() => {
    if (!banner) return;
    const id = window.setTimeout(() => setBanner(null), 4500);
    return () => window.clearTimeout(id);
  }, [banner]);

  // Lower third: newest moment for this persona, for its duration after it lands.
  const arrivals = useRef<Map<string, number>>(new Map());
  const [, force] = useState(0);
  useEffect(() => {
    for (const m of moments) if (!arrivals.current.has(m.moment_id)) arrivals.current.set(m.moment_id, performance.now());
    const id = window.setInterval(() => force((n) => n + 1), 500);
    return () => window.clearInterval(id);
  }, [moments]);
  const now = performance.now();
  // Only moments that land live go on air; the backlog from before a mid-match start stays on the phones.
  const strap = [...moments].reverse().filter((m) => m.elapsed >= meta.start_elapsed)
    .map((m) => ({ m, cue: m.cues.find((c) => c.persona_id === persona.id) }))
    .find(({ m, cue }) => cue && now - (arrivals.current.get(m.moment_id) ?? 0) < cue.duration_s * 1000);

  const score = snap?.score ?? {};
  const regime = snap?.regime ?? "balanced";
  const regimeText = regime === "chaos" ? "Open, chaotic phase"
    : regime.startsWith("control:") ? `${regime.endsWith(meta.home.team_id) ? meta.home.short_name : meta.away.short_name} in control`
    : "Even contest";
  const strapTeam = strap?.m.team_id === meta.away.team_id ? meta.away : meta.home;

  return (
    <div className="tv">
      <div className="tv-screen">
        <canvas ref={canvasRef} className="pitch" aria-label="Animated match view" />
        <div className="scorebug" aria-live="polite">
          <span className="sb-team" style={{ background: meta.home.colors[0], color: meta.home.colors[1] }}>{meta.home.short_name}</span>
          <span className="sb-score">{score[meta.home.team_id] ?? 0}<i>–</i>{score[meta.away.team_id] ?? 0}</span>
          <span className="sb-team" style={{ background: meta.away.colors[0], color: meta.away.colors[1] }}>{meta.away.short_name}</span>
          <span className="sb-clock">{clockRef.current.clock}</span>
        </div>
        <div className={`regime regime-${regime.split(":")[0]}`}>{regimeText}</div>
        {banner && (
          <div key={banner.key} className={`banner banner-${banner.kind}`}
               style={{ ["--team" as string]: (banner.team === meta.away.team_id ? meta.away : meta.home).colors[0] }}>
            <span className="banner-title">{banner.title}</span>
            <span className="banner-sub">{banner.sub}</span>
            {banner.line && <span className="banner-line">{banner.line}</span>}
          </div>
        )}
        {strap?.cue && (
          <div key={strap.m.moment_id} className="lower-third" style={{ ["--team" as string]: strapTeam.colors[0], ["--team2" as string]: strapTeam.colors[1] }}>
            <div className="lt-clock">{strap.m.clock}</div>
            <div className="lt-body">
              <div className="lt-strap">{strap.cue.text.strap}</div>
              {usefulChips(strap.cue.stats).length > 0 && (
                <div className="lt-stats">{usefulChips(strap.cue.stats).map((s) => <span key={s.label}><b>{s.value}</b> {s.label}</span>)}</div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
