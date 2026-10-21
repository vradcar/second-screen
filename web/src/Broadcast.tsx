import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { drawBall, drawPitch, drawPlayer, drawTag, drawTrace, layout, sx, sy, type Trace, type View } from "./draw";
import { ballAt, ballKeys, lineupSlots, shapePosition, travelTime, type Slot } from "./motion";
import { usefulChips } from "./personas";
import { matchTime, type ClockRef } from "./stream";
import type { Cue, MatchEvent, Meta, Moment, Persona, Snapshot } from "./types";

const POSSESSION = new Set(["pass", "carry", "shot", "dribble", "possession_start", "corner"]);
const TRACED = new Set(["pass", "shot"]);
const ACTION: Record<string, string> = {
  pass: "Pass", carry: "Carry", shot: "Shot", dribble: "Beats his man", interception: "Interception",
  tackle: "Tackle", clearance: "Clearance", save: "Save", block: "Block", corner: "Corner", penalty_awarded: "Penalty",
};

interface Props {
  meta: Meta; events: MatchEvent[]; clockRef: MutableRefObject<ClockRef>; snap?: Snapshot;
  cues: Cue[]; moments: Moment[]; persona: Persona;
}
interface Banner { key: string; kind: "goal" | "red"; title: string; sub: string; team: string; line?: string }
interface Holder { pid: string; team: string; action: string; detail: string[] }
interface Pending { pid: string; team: string; at: number; x: number; y: number; action: string; detail: string[] }

function freshLive(home: string) {
  return { idx: 0, off: new Set<string>(), on: new Map<string, string>(), possession: home,
           holder: null as Holder | null, pending: null as Pending | null, looseAt: Infinity,
           chain: 0, chainTeam: "", traces: [] as Trace[] };
}

export function Broadcast({ meta, events, clockRef, snap, cues, moments, persona }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const keys = useMemo(() => ballKeys(events), [events]);
  const slots = useMemo(() => ({ home: lineupSlots(meta.home), away: lineupSlots(meta.away) }), [meta]);
  const posRef = useRef<Map<string, { x: number; y: number }>>(new Map());
  const drawnRef = useRef<{ id: string; px: number; py: number }[]>([]);
  const [banner, setBanner] = useState<Banner | null>(null);
  const [carrier, setCarrier] = useState<(Holder & { chain: number }) | null>(null);
  const [follow, setFollow] = useState<string | null>(null);
  const followRef = useRef<string | null>(null); followRef.current = follow;
  const hoverRef = useRef<string | null>(null);
  const seenRef = useRef<Set<string>>(new Set());
  const liveRef = useRef(freshLive(meta.home.team_id));
  useEffect(() => { liveRef.current = freshLive(meta.home.team_id); seenRef.current = new Set(); setFollow(null); }, [meta]);

  const tagCues = useMemo(() => cues.filter((c) => c.persona_id === persona.id && (c.type === "player_tag" || c.type === "stat_pop") && c.player_id), [cues, persona.id]);
  const tagRef = useRef(tagCues); tagRef.current = tagCues;
  const eventsRef = useRef(events); eventsRef.current = events;
  const people = useMemo(() => {
    const m = new Map<string, { name: string; number: number; team: string; colors: [string, string] }>();
    for (const t of [meta.home, meta.away]) for (const p of [...t.starting_xi, ...t.bench]) m.set(p.player_id, { name: p.name, number: p.number, team: t.team_id, colors: t.colors });
    return m;
  }, [meta]);
  const surname = (pid: string) => people.get(pid)?.name.split(" ").slice(-1)[0] ?? "";

  useEffect(() => {
    let raf = 0;
    let lastKey = "";
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const cv = canvasRef.current; if (!cv) return;
      const dpr = window.devicePixelRatio || 1;
      const W = cv.clientWidth, H = cv.clientHeight;
      if (cv.width !== Math.round(W * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
      const g = cv.getContext("2d")!; g.setTransform(dpr, 0, 0, dpr, 0, 0);
      const clock = clockRef.current, t = matchTime(clock), spd = clock.speed;
      const live = liveRef.current, evs = eventsRef.current;

      // Advance the live state to "now".
      while (live.idx < evs.length && evs[live.idx].elapsed_seconds <= t) {
        const e = evs[live.idx++];
        if (e.type === "substitution" && e.player_id && e.player_off_id) { live.off.add(e.player_off_id); live.on.set(e.player_off_id, e.player_id); }
        if (e.type === "card" && e.card === "second_yellow" && e.player_id) live.off.add(e.player_id);
        if (e.team_id && POSSESSION.has(e.type)) live.possession = e.team_id;
        if (e.type === "possession_change") { live.chain = 0; live.chainTeam = e.team_id ?? ""; }
        if (TRACED.has(e.type) && e.end_x !== undefined) {
          live.traces.push({ e, dur: travelTime(e) });
          if (live.traces.length > 14) live.traces.shift();
        }
        // A defender winning a ball that's still travelling runs to it and takes over when it arrives.
        const BALL_WINNERS = ["interception", "save", "block", "clearance"];
        if (e.player_id && BALL_WINNERS.includes(e.type) && t < live.looseAt && Number.isFinite(live.looseAt) && e.x !== undefined && e.y !== undefined) {
          live.pending = { pid: e.player_id, team: e.team_id ?? "", at: live.looseAt, x: e.x, y: e.y,
                           action: ACTION[e.type] ?? "On the ball", detail: [] };
          live.looseAt = Infinity;
          continue;
        }
        if (e.player_id && ACTION[e.type] && !(e.type === "tackle" && e.outcome !== "won")) {
          const detail: string[] = [];
          if (e.type === "pass" && e.distance_m) detail.push(`${Math.round(e.distance_m)} m`);
          if (e.type === "pass" && e.ball_speed_kmh) detail.push(`${Math.round(e.ball_speed_kmh)} km/h`);
          if (e.type === "carry" && e.speed_kmh) detail.push(`${e.speed_kmh.toFixed(1)} km/h`);
          if (e.type === "shot" && e.shot_speed_kmh) detail.push(`${Math.round(e.shot_speed_kmh)} km/h`);
          if (e.type === "pass" && e.outcome !== "complete") detail.push(e.outcome === "out" ? "out of play" : "intercepted");
          live.holder = { pid: e.player_id, team: e.team_id ?? "", action: ACTION[e.type], detail };
          live.pending = null; live.looseAt = Infinity;
          if (e.type === "pass" && e.end_x !== undefined && e.end_y !== undefined) {
            if (e.outcome === "complete" && e.recipient_id) {
              live.pending = { pid: e.recipient_id, team: e.team_id ?? "", at: e.elapsed_seconds + travelTime(e), x: e.end_x, y: e.end_y,
                               action: "On the ball", detail: [] };
              if (live.chainTeam === e.team_id) live.chain += 1; else { live.chain = 1; live.chainTeam = e.team_id ?? ""; }
            } else live.looseAt = e.elapsed_seconds + travelTime(e);
          }
          if (e.type === "shot") live.looseAt = e.elapsed_seconds + travelTime(e);
        }
        if (e.type === "goal" && e.player_id) live.holder = { pid: e.player_id, team: e.team_id ?? "", action: "Goal", detail: [] };
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
      if (live.pending && t >= live.pending.at) {
        live.holder = { pid: live.pending.pid, team: live.pending.team, action: live.pending.action, detail: live.pending.detail };
        live.pending = null;
      }
      if (t >= live.looseAt) { live.holder = null; live.looseAt = Infinity; }
      const h = live.holder;
      const key = h ? `${h.pid}|${h.action}|${h.detail.join()}|${live.chain}` : "none";
      if (key !== lastKey) { lastKey = key; setCarrier(h ? { ...h, chain: live.chainTeam === h.team ? live.chain : 0 } : null); }

      // Draw
      g.clearRect(0, 0, W, H);
      const v: View = layout(W, H);
      drawPitch(g, v, W, H);
      const fade = 2.2 * spd;   // traces linger ~2 s of wall time at any speed
      live.traces = live.traces.filter((tr) => t - tr.e.elapsed_seconds - tr.dur < fade);
      for (const tr of live.traces) drawTrace(g, v, tr, t, fade);

      const ball = ballAt(keys, t);
      const inFlight = !!live.pending || t < live.looseAt;
      const positions = posRef.current;
      const teams: [Slot[], boolean, string, [string, string]][] = [
        [slots.home, true, meta.home.team_id, meta.home.colors], [slots.away, false, meta.away.team_id, meta.away.colors]];
      const drawn: { id: string; x: number; y: number }[] = [];
      for (const [teamSlots, home, tid, colors] of teams) {
        teamSlots.forEach((slot, i) => {
          const pid = live.on.get(slot.player_id) ?? slot.player_id;
          if (live.off.has(pid)) return;
          let target = shapePosition(slot, home, ball.x, ball.y, live.possession === tid, t, i + (home ? 0 : 11));
          let k = 0.08;
          if (live.pending && pid === live.pending.pid) { target = { x: live.pending.x, y: live.pending.y }; k = 0.18; }
          else if (h && pid === h.pid && !inFlight) { target = { x: ball.x - (home ? 0.9 : -0.9), y: ball.y + 0.6 }; k = 0.35; }
          const cur = positions.get(pid) ?? target;
          const p = { x: cur.x + (target.x - cur.x) * k, y: cur.y + (target.y - cur.y) * k };
          positions.set(pid, p);
          drawn.push({ id: pid, x: p.x, y: p.y });
          const focusName = persona.focus && people.get(pid)?.name === persona.focus;
          const ring = followRef.current === pid ? "#FFFFFF" : focusName ? "#F2C14E" : null;
          drawPlayer(g, v, p.x, p.y, colors, people.get(pid)?.number ?? 0, ring, !!h && h.pid === pid);
        });
      }
      drawnRef.current = drawn.map((d) => ({ id: d.id, px: sx(v, d.x), py: sy(v, d.y) }));

      const trail = [ball];
      for (let i = 1; i <= 6; i++) trail.push(ballAt(keys, t - i * 0.06 * spd));
      drawBall(g, v, trail, inFlight);

      // Tags: speed / card pops from the pipeline, plus hovered and followed players.
      const tagged = new Set<string>();
      for (const c of tagRef.current) {
        if (t < c.elapsed || t > c.elapsed + c.duration_s * spd) continue;
        const pos = drawn.find((d) => d.id === c.player_id); if (!pos || tagged.has(pos.id)) continue;
        tagged.add(pos.id);
        drawTag(g, v, pos.x, pos.y, c.text.strap.split(" ").slice(-1)[0], c.stats[0]?.value ?? "", people.get(c.player_id!)?.colors ?? meta.home.colors);
      }
      for (const id of [hoverRef.current, followRef.current]) {
        if (!id || tagged.has(id)) continue;
        const pos = drawn.find((d) => d.id === id); if (!pos) continue;
        tagged.add(id);
        drawTag(g, v, pos.x, pos.y, surname(id), "", people.get(id)?.colors ?? meta.home.colors);
      }
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [keys, slots, meta, clockRef, people, persona.focus]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!banner) return;
    const id = window.setTimeout(() => setBanner(null), 4500);
    return () => window.clearTimeout(id);
  }, [banner]);

  // Pointer: hover shows a name, click follows a player, click on grass stops following.
  const hit = useCallback((ev: React.MouseEvent<HTMLCanvasElement>) => {
    const r = ev.currentTarget.getBoundingClientRect();
    const x = ev.clientX - r.left, y = ev.clientY - r.top;
    let best: string | null = null, bd = 18 * 18;
    for (const d of drawnRef.current) {
      const dd = (d.px - x) ** 2 + (d.py - y) ** 2;
      if (dd < bd) { bd = dd; best = d.id; }
    }
    return best;
  }, []);
  const onMove = (ev: React.MouseEvent<HTMLCanvasElement>) => {
    hoverRef.current = hit(ev);
    ev.currentTarget.style.cursor = hoverRef.current ? "pointer" : "default";
  };

  // Lower third: newest live moment for this persona, for its duration after it lands.
  const arrivals = useRef<Map<string, number>>(new Map());
  const [, force] = useState(0);
  useEffect(() => {
    for (const m of moments) if (!arrivals.current.has(m.moment_id)) arrivals.current.set(m.moment_id, performance.now());
    const id = window.setInterval(() => force((n) => n + 1), 500);
    return () => window.clearInterval(id);
  }, [moments]);
  const now = performance.now();
  const strap = [...moments].reverse().filter((m) => m.elapsed >= meta.start_elapsed)
    .map((m) => ({ m, cue: m.cues.find((c) => c.persona_id === persona.id) }))
    .find(({ m, cue }) => cue && now - (arrivals.current.get(m.moment_id) ?? 0) < cue.duration_s * 1000);

  const score = snap?.score ?? {};
  const regime = snap?.regime ?? "balanced";
  const regimeText = regime === "chaos" ? "Open, chaotic phase"
    : regime.startsWith("control:") ? `${regime.endsWith(meta.home.team_id) ? meta.home.short_name : meta.away.short_name} in control`
    : "Even contest";
  const strapTeam = strap?.m.team_id === meta.away.team_id ? meta.away : meta.home;
  const followed = follow ? snap?.players.find((p) => p.player_id === follow) : undefined;
  const boxId = follow ?? carrier?.pid;
  const boxPerson = boxId ? people.get(boxId) : undefined;

  return (
    <div className="tv">
      <div className="tv-screen">
        <canvas ref={canvasRef} className="pitch" aria-label="Animated match view. Click a player to follow him."
                onMouseMove={onMove} onMouseLeave={() => { hoverRef.current = null; }}
                onClick={(ev) => setFollow(hit(ev))} />
        <div className="scorebug" aria-live="polite">
          <span className="sb-team" style={{ background: meta.home.colors[0], color: meta.home.colors[1] }}>{meta.home.short_name}</span>
          <span className="sb-score">{score[meta.home.team_id] ?? 0}<i>–</i>{score[meta.away.team_id] ?? 0}</span>
          <span className="sb-team" style={{ background: meta.away.colors[0], color: meta.away.colors[1] }}>{meta.away.short_name}</span>
          <span className="sb-clock">{clockRef.current.clock}</span>
        </div>
        <div className={`regime regime-${regime.split(":")[0]}`}>{regimeText}</div>

        {boxPerson && (
          <div className={`carrier ${follow ? "carrier-follow" : ""}`} style={{ ["--team" as string]: boxPerson.colors[0], ["--team2" as string]: boxPerson.colors[1] }}>
            <span className="carrier-num">{boxPerson.number}</span>
            <span className="carrier-main">
              <span className="carrier-label">{follow ? "Following" : carrier?.action}</span>
              <b className="carrier-name">{boxPerson.name}</b>
              <span className="carrier-detail">
                {follow && followed ? (
                  <>
                    <span>{followed.touches} touches</span>
                    <span>{(followed.distance_m / 1000).toFixed(1)} km</span>
                    {followed.top_speed_kmh > 0 && <span>top {followed.top_speed_kmh.toFixed(1)} km/h</span>}
                  </>
                ) : (
                  <>
                    {carrier?.detail.map((d) => <span key={d}>{d}</span>)}
                    {carrier && carrier.chain >= 3 && <span className="carrier-chain">{carrier.chain}-pass move</span>}
                  </>
                )}
              </span>
            </span>
            {follow && <button className="carrier-x" onClick={() => setFollow(null)} aria-label="Stop following">×</button>}
          </div>
        )}

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
