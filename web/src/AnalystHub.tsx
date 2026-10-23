import { useEffect, useMemo, useRef, useState, type MutableRefObject, type PointerEvent as RPE, type KeyboardEvent as RKE } from "react";
import { MatchCentre } from "./MatchCentre";
import { lineupSlots } from "./motion";
import { matchTime, type ClockRef } from "./stream";
import type { KeyEvent, Meta, Snapshot, Team } from "./types";
import { Board, Card, Legend, Segmented, Tip, fmt, useTip, type TipRow } from "./hub/parts";
import { inkOn, teamInk, type TeamInk } from "./hub/theme";

type Ui = (t: string, vars?: Record<string, string | number>) => string;
type Show = (e: { clientX: number; clientY: number }, title: string | undefined, rows: TipRow[]) => void;

interface PlayerRow {
  player_id: string; name: string; number: number; position: string; team_id: string; starter: boolean;
  on_pitch: boolean; minutes: number; touches: number; passes: number; passes_completed: number;
  pass_completion: number | null; progressive_passes: number; key_passes: number; shots: number;
  shots_on_target: number; xg: number; goals: number; assists: number; dribbles: number; tackles_won: number;
  interceptions: number; pressures: number; fouls: number; yellow_cards: number; red_card: boolean;
  distance_km: number; top_speed_kmh: number;
}
interface Shot { team_id: string; player: string; player_id: string; clock: string; minute: number; elapsed: number;
  x: number; y: number; xg: number; outcome: string; body_part: string; situation: string; speed_kmh?: number }
interface Network { nodes: { player_id: string; name: string; number: number; x: number; y: number; passes: number }[];
  edges: { a: string; b: string; count: number }[] }
interface FlowSide { passes: number; final_third: number; box_entries: number; shots: number; xg: number; threat: number }
type FlowBin = { t0: number; t1: number } & { [team: string]: FlowSide | number };
type PpdaRow = { window: number; label: string } & { [team: string]: number | string | null };
type Zone = { i: number; j: number; share: number | null } & { [team: string]: number | null };
interface Analysis {
  ready: boolean; clock: string; elapsed: number; home: string; away: string; formations: Record<string, string>;
  teams: Record<string, Record<string, number | null>>; players: PlayerRow[]; shots: Shot[];
  xg_flow: Record<string, [number, number][]>; pass_networks: Record<string, Network>;
  heatmaps: Record<string, [number, number, number][]>; key_events: KeyEvent[];
  flow: FlowBin[]; second_half: number | null; ppda: PpdaRow[]; zones: Zone[];
  defence: Record<string, [number, number, string, string, string][]>;
}
interface PlayerDetail { name: string; passes: { x0: number; y0: number; x1: number; y1: number; ok: boolean; progressive: boolean; clock: string; to?: string }[];
  touches: [number, number][]; actions: { clock: string; type: string; outcome?: string }[] }

const TABS = ["Overview", "Attack", "Possession", "Defence", "Line-ups", "Players", "Physical"] as const;
type Tab = typeof TABS[number];
const sur = (n: string) => n.split(" ").slice(-1)[0];
const teamOf = (meta: Meta, id: string): Team => (id === meta.away.team_id ? meta.away : meta.home);
const minuteOf = (elapsed: number, ht: number | null) => (ht && elapsed >= ht ? 45 + (elapsed - ht) / 60 : elapsed / 60);
const side = (b: FlowBin, tm: string) => b[tm] as FlowSide | undefined;
const num = (v: unknown) => (typeof v === "number" ? v : null);
const OUTCOME: Record<string, string> = { goal: "Goal", saved: "Saved", blocked: "Blocked", off_target: "Off target", post: "Hit the woodwork" };
const plain = (s?: string | null) => (s ?? "").replace(/_/g, " ");
const YELLOW = "#E8B417", RED = "#D93025";

interface Ctx { d: Analysis; meta: Meta; ui: Ui; ink: TeamInk; show: Show; hide: () => void }

/** The analysis desk: the live data a club's analysts work from, below the broadcast. */
export function AnalystHub({ meta, snap, clockRef, ui }: { meta: Meta; snap?: Snapshot; clockRef: MutableRefObject<ClockRef>; ui: Ui }) {
  const [tab, setTab] = useState<Tab>(() => { try { return (localStorage.getItem("ss.hubTab") as Tab) || "Overview"; } catch { return "Overview"; } });
  const [data, setData] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
  const { tip, show, hide, host } = useTip();
  const ink = useMemo(() => teamInk(meta), [meta]);
  const pick = (t: Tab) => { setTab(t); hide(); try { localStorage.setItem("ss.hubTab", t); } catch { /* private window */ } };

  // Recomputed on the server from the events up to the viewer's clock, every few seconds.
  // The previous numbers stay on screen while the next set loads, so nothing flickers.
  useEffect(() => {
    let alive = true;
    const load = () => {
      setLoading(true);
      const upto = Math.max(0, matchTime(clockRef.current));
      fetch(`/api/analysis?match=${encodeURIComponent(meta.match_id)}&upto=${upto.toFixed(0)}`)
        .then((r) => (r.ok ? r.json() : null)).then((d) => { if (alive && d?.ready) setData(d); })
        .catch(() => {}).finally(() => alive && setLoading(false));
    };
    load();
    const id = window.setInterval(load, 4000);
    return () => { alive = false; window.clearInterval(id); };
  }, [meta.match_id, clockRef]);

  const onKey = (e: RKE) => {
    const i = TABS.indexOf(tab);
    if (e.key === "ArrowRight") pick(TABS[(i + 1) % TABS.length]);
    if (e.key === "ArrowLeft") pick(TABS[(i + TABS.length - 1) % TABS.length]);
  };

  const c: Ctx | null = data ? { d: data, meta, ui, ink, show, hide } : null;
  const hg = data?.teams[data.home]?.goals ?? 0, ag = data?.teams[data.away]?.goals ?? 0;
  return (
    <section className="desk" aria-label={ui("Match analysis")} ref={host}
             style={{ ["--home" as string]: ink.home, ["--away" as string]: ink.away }}>
      <header className="desk-head">
        <div className="desk-title">
          <h2>{ui("Match analysis")}</h2>
          {data && (
            <p className="desk-score">
              <span><i className="team-dot" style={{ background: ink.home }} />{meta.home.name}</span>
              <b>{hg}–{ag}</b>
              <span>{meta.away.name}<i className="team-dot r" style={{ background: ink.away }} /></span>
              <span className={`desk-live ${loading ? "is-loading" : ""}`}>{ui("Data to")} {data.clock}</span>
            </p>
          )}
        </div>
        <nav className="desk-tabs" role="tablist" aria-label={ui("Analysis views")} onKeyDown={onKey}>
          {TABS.map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} tabIndex={tab === t ? 0 : -1} onClick={() => pick(t)}>{ui(t)}</button>
          ))}
        </nav>
      </header>
      {!c ? <p className="desk-empty">{ui("The numbers start with the kick-off.")}</p> : (
        <div className="desk-body" role="tabpanel" aria-label={ui(tab)}>
          {tab === "Overview" ? <Overview {...c} />
            : tab === "Attack" ? <Attack {...c} />
            : tab === "Possession" ? <Possession {...c} />
            : tab === "Defence" ? <Defence {...c} />
            : tab === "Line-ups" ? <Lineups {...c} snap={snap} />
            : tab === "Players" ? <Players {...c} clockRef={clockRef} />
            : <Physical {...c} />}
        </div>
      )}
      <Tip tip={tip} />
    </section>
  );
}

// ================================================================== shared chart bits
/** A bar growing from a baseline, with a 4px rounded data end and a square base. */
function bar(x: number, base: number, w: number, h: number, up: boolean) {
  const r = Math.min(4, h, w / 2);
  if (up) return `M${x},${base} V${base - h + r} Q${x},${base - h} ${x + r},${base - h} H${x + w - r} Q${x + w},${base - h} ${x + w},${base - h + r} V${base} Z`;
  return `M${x},${base} V${base + h - r} Q${x},${base + h} ${x + r},${base + h} H${x + w - r} Q${x + w},${base + h} ${x + w},${base + h - r} V${base} Z`;
}

function niceTicks(max: number) {
  const step = max > 12 ? 5 : max > 6 ? 2 : max > 3 ? 1 : max > 1.5 ? 0.5 : 0.25;
  const out: number[] = [];
  for (let v = 0; v <= max + 1e-9; v += step) out.push(+v.toFixed(2));
  return out;
}

/** The match clock axis: real time on the x-axis, minute labels that restart at 45 after the break. */
function timeAxis(d: Analysis) {
  const ht = d.second_half;
  const end = Math.max(d.elapsed, (ht ?? 2880) + 2880);
  const ticks: [number, string][] = [[0, "0'"], [900, "15'"], [1800, "30'"]];
  if (ht) ticks.push([ht + 900, "60'"], [ht + 1800, "75'"]);
  else ticks.push([3600, "60'"], [4500, "75'"]);
  return { end, ticks, ht };
}

// ================================================================== Overview
const HEADLINE: [string, string, (v: number | null) => string, boolean?][] = [
  ["xg", "Expected goals", fmt.d2], ["shots", "Shots", fmt.n], ["shots_on_target", "On target", fmt.n],
  ["possession_pct", "Possession", fmt.pct], ["field_tilt_pct", "Field tilt", fmt.pct], ["ppda", "PPDA", fmt.d1, true],
];
const HEADLINE_NOTE: Record<string, string> = {
  xg: "Quality of chances: how many goals the shots were worth",
  field_tilt_pct: "Share of the touches in the final third",
  ppda: "Opponent passes allowed per defensive action. Lower means pressing harder",
};

function Overview(c: Ctx) {
  const { d, meta, ui, ink } = c;
  const teams = [{ color: ink.home, label: meta.home.short_name }, { color: ink.away, label: meta.away.short_name }];
  return (
    <div className="desk-grid">
      <div className="kpis hcard-wide">
        {HEADLINE.map(([k, label, f, low]) => {
          const h = Number(d.teams[d.home][k] ?? 0), a = Number(d.teams[d.away][k] ?? 0);
          const share = h + a > 0 ? h / (h + a) : 0.5;
          const lead = h === a ? "" : low ? (h < a ? "h" : "a") : h > a ? "h" : "a";
          return (
            <div key={k} className="kpi" title={HEADLINE_NOTE[k] ? ui(HEADLINE_NOTE[k]) : undefined}>
              <span className="kpi-label">{ui(label)}</span>
              <span className="kpi-vals">
                <b className={lead === "h" ? "lead" : ""}>{f(d.teams[d.home][k] as number | null)}</b>
                <b className={lead === "a" ? "lead" : ""}>{f(d.teams[d.away][k] as number | null)}</b>
              </span>
              <span className="kpi-split" aria-hidden="true">
                <i style={{ flexGrow: low ? 1 - share : share, background: ink.home }} />
                <i style={{ flexGrow: low ? share : 1 - share, background: ink.away }} />
              </span>
              <span className="kpi-teams"><span>{meta.home.short_name}</span>{low ? <small>{ui("lower is better")}</small> : null}<span>{meta.away.short_name}</span></span>
            </div>
          );
        })}
      </div>
      <Card wide title={ui("Match flow")}
            note={ui("Attacking threat in 3-minute spells, from final-third touches, passes into the box and chance quality. {home} above the line, {away} below.", { home: meta.home.short_name, away: meta.away.short_name })}
            actions={<Legend items={teams} />}>
        <div className="chart-scroll"><MatchFlow {...c} /></div>
      </Card>
      <Card title={ui("xG race")} note={ui("How chance quality has built up. Each dot is a shot; ringed dots are goals.")} actions={<Legend line items={teams} />}>
        <div className="chart-scroll"><XgRace {...c} /></div>
      </Card>
      <Card title={ui("Key events")}>
        <Timeline {...c} />
      </Card>
      <Card wide title={ui("Team comparison")} note={ui("Bars compare the two sides on each measure. The leader's figure is in bold.")} actions={<Legend items={teams} />}>
        <Compare {...c} />
      </Card>
    </div>
  );
}

function MatchFlow({ d, meta, ink, show, hide, ui }: Ctx) {
  const W = 1000, H = 236, ev = 14, top = 34, mid = 124, bot = 214, L = 40, R = 8;
  const { end, ticks, ht } = timeAxis(d);
  const X = (t: number) => L + (t / end) * (W - L - R);
  const max = Math.max(8, ...d.flow.flatMap((r) => [side(r, d.home)?.threat ?? 0, side(r, d.away)?.threat ?? 0]));
  const hgt = (v: number) => (v / max) * (mid - top - 2);
  const bw = Math.max(4, X(180) - X(0) - 2);
  const label = (t: number) => `${Math.floor(minuteOf(t, ht))}'`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={ui("Match flow")} onPointerLeave={hide}>
      <text x={L - 8} y={top + 10} className="tick" textAnchor="end">{meta.home.short_name.slice(0, 3).toUpperCase()}</text>
      <text x={L - 8} y={bot - 2} className="tick" textAnchor="end">{meta.away.short_name.slice(0, 3).toUpperCase()}</text>
      {ticks.map(([t, l]) => t <= end && (
        <g key={l}><line x1={X(t)} x2={X(t)} y1={top} y2={bot} className="grid" /><text x={X(t)} y={H - 6} className="tick" textAnchor="middle">{l}</text></g>))}
      {ht && <g><line x1={X(ht)} x2={X(ht)} y1={ev - 6} y2={bot} className="axis" /><text x={X(ht)} y={H - 6} className="tick strong" textAnchor="middle">HT</text></g>}
      {d.flow.map((r) => {
        const h = side(r, d.home), a = side(r, d.away);
        if (!h || !a) return null;
        const x = X(r.t0) + 1, hh = hgt(h.threat), ah = hgt(a.threat);
        const rows: TipRow[] = [
          { key: ink.home, value: `${h.shots} ${ui("shots")} · xG ${h.xg.toFixed(2)}`, label: meta.home.short_name },
          { key: ink.home, value: String(h.box_entries), label: ui("passes into the box") },
          { key: ink.away, value: `${a.shots} ${ui("shots")} · xG ${a.xg.toFixed(2)}`, label: meta.away.short_name },
          { key: ink.away, value: String(a.box_entries), label: ui("passes into the box") },
        ];
        return (
          <g key={r.t0} className="flow-bin" onPointerMove={(e) => show(e, `${label(r.t0)}–${label(Math.min(r.t1, d.elapsed))}`, rows)}>
            <rect x={x - 1} y={top} width={bw + 2} height={bot - top} className="hit" />
            {hh > 0.5 && <path d={bar(x, mid - 1, bw, hh, true)} fill={ink.home} />}
            {ah > 0.5 && <path d={bar(x, mid + 1, bw, ah, false)} fill={ink.away} />}
          </g>
        );
      })}
      <line x1={L} x2={W - R} y1={mid} y2={mid} className="axis" />
      <line x1={X(d.elapsed)} x2={X(d.elapsed)} y1={ev - 6} y2={bot} className="now" />
      {d.key_events.filter((e) => e.kind !== "sub").map((e, i) => {
        const x = X(e.elapsed), col = ink.of(e.team_id);
        const tipRows: TipRow[] = [{ key: col, value: ui(e.kind === "goal" ? "Goal" : e.kind === "red" ? "Red card" : "Yellow card"), label: `${e.player}, ${teamOf(meta, e.team_id).short_name}` }];
        return (
          <g key={i} onPointerMove={(p) => show(p, e.clock, tipRows)}>
            {e.kind === "goal"
              ? <><circle cx={x} cy={ev} r={7} fill={col} stroke="var(--surface)" strokeWidth={2} /><circle cx={x} cy={ev} r={2.4} fill="#fff" /></>
              : <rect x={x - 3.5} y={ev - 6} width={7} height={11} rx={1.4} fill={e.kind === "red" ? RED : YELLOW} stroke="var(--surface)" strokeWidth={1.5} />}
          </g>
        );
      })}
    </svg>
  );
}

function XgRace({ d, meta, ink, show, hide, ui }: Ctx) {
  const W = 640, H = 280, L = 36, R = 108, T = 14, B = 26;
  const { end, ticks: tt, ht } = timeAxis(d);
  const maxY = Math.max(1, ...Object.values(d.xg_flow).flat().map((p) => p[1])) * 1.12;
  const X = (t: number) => L + (t / end) * (W - L - R), Y = (v: number) => H - B - (v / maxY) * (H - B - T);
  const ref = useRef<SVGSVGElement>(null);
  const [hx, setHx] = useState<number | null>(null);
  const at = (team: string, t: number) => { let v = 0; for (const p of d.xg_flow[team] ?? []) if (p[0] <= t) v = p[1]; return v; };
  const path = (pts: [number, number][]) => `M${X(0)},${Y(0)}` + pts.map((p) => `H${X(p[0])}V${Y(p[1])}`).join("") + `H${X(d.elapsed)}`;
  const move = (e: RPE<SVGSVGElement>) => {
    const r = ref.current!.getBoundingClientRect();
    const t = Math.min(d.elapsed, Math.max(0, (((e.clientX - r.left) / r.width) * W - L) / (W - L - R) * end));
    setHx(t);
    show(e, `${Math.floor(minuteOf(t, ht))}'`, [
      { key: ink.home, value: at(d.home, t).toFixed(2), label: `${meta.home.short_name} xG` },
      { key: ink.away, value: at(d.away, t).toFixed(2), label: `${meta.away.short_name} xG` }]);
  };
  const endH = at(d.home, d.elapsed), endA = at(d.away, d.elapsed);
  let yh = Y(endH), ya = Y(endA);
  if (Math.abs(yh - ya) < 18) { const m = (yh + ya) / 2, up = endH >= endA; yh = up ? m - 9 : m + 9; ya = up ? m + 9 : m - 9; }
  return (
    <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={ui("xG race")}
         onPointerMove={move} onPointerLeave={() => { setHx(null); hide(); }}>
      {niceTicks(maxY).map((v) => <g key={v}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} className="grid" /><text x={L - 8} y={Y(v) + 4} className="tick" textAnchor="end">{v}</text></g>)}
      {tt.filter(([t]) => t <= end).map(([t, l]) => <text key={l} x={X(t)} y={H - 6} className="tick" textAnchor="middle">{l}</text>)}
      {ht && <g><line x1={X(ht)} x2={X(ht)} y1={T} y2={H - B} className="axis" /><text x={X(ht)} y={H - 6} className="tick strong" textAnchor="middle">HT</text></g>}
      {[d.away, d.home].map((tm) => <path key={tm} d={path(d.xg_flow[tm] ?? [])} fill="none" stroke={ink.of(tm)} strokeWidth={2} strokeLinejoin="round" />)}
      {d.shots.map((s, i) => {
        const goal = s.outcome === "goal", col = ink.of(s.team_id);
        return <circle key={i} cx={X(s.elapsed)} cy={Y(at(s.team_id, s.elapsed))} r={goal ? 6 : 4}
                       fill={goal ? "var(--surface)" : col} stroke={goal ? col : "var(--surface)"} strokeWidth={2} />;
      })}
      {hx != null && <line x1={X(hx)} x2={X(hx)} y1={T} y2={H - B} className="crosshair" />}
      <g className="endlabel">
        <circle cx={W - R + 10} cy={yh} r={4} fill={ink.home} /><text x={W - R + 18} y={yh + 4}><tspan className="strong">{endH.toFixed(2)}</tspan> {meta.home.short_name}</text>
        <circle cx={W - R + 10} cy={ya} r={4} fill={ink.away} /><text x={W - R + 18} y={ya + 4}><tspan className="strong">{endA.toFixed(2)}</tspan> {meta.away.short_name}</text>
      </g>
    </svg>
  );
}

function Timeline({ d, meta, ink, ui }: Ctx) {
  if (!d.key_events.length) return <p className="muted">{ui("No goals, bookings or substitutions yet.")}</p>;
  const ht = d.second_half;
  let hg = 0, ag = 0;
  return (
    <ol className="tl">
      {d.key_events.map((e, i) => {
        const prev = d.key_events[i - 1];
        const breakHere = !!ht && e.elapsed >= ht && (!prev || prev.elapsed < ht);
        if (e.kind === "goal") { if (e.team_id === d.home) hg++; else ag++; }
        const away = e.team_id === d.away;
        return (
          <li key={i} className={`tl-row tl-${e.kind} ${away ? "tl-away" : ""}`}>
            {breakHere && <span className="tl-ht">{ui("Second half")}</span>}
            <span className="tl-min">{e.clock.replace(/:\d\d$/, "'")}</span>
            <span className="tl-mark" aria-hidden="true">
              {e.kind === "goal" ? <svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.5" fill={ink.of(e.team_id)} /><circle cx="8" cy="8" r="2.2" fill="#fff" /></svg>
                : e.kind === "sub" ? <svg viewBox="0 0 16 16"><path d="M2.5 5.5h10l-3-3M13.5 10.5h-10l3 3" fill="none" stroke={ink.of(e.team_id)} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
                : <svg viewBox="0 0 16 16"><rect x="4.5" y="2" width="7" height="12" rx="1.3" fill={e.kind === "red" ? RED : YELLOW} /></svg>}
            </span>
            <span className="tl-text">
              <b>{e.kind === "sub" ? `${e.player} ${ui("on")}` : e.player}{e.kind === "goal" && <span className="tl-score">{hg}–{ag}</span>}</b>
              <span className="muted">
                {teamOf(meta, e.team_id).short_name}{" · "}
                {e.kind === "goal" ? (e.assist ? `${ui("assist")} ${e.assist}` : ui("Goal"))
                  : e.kind === "sub" ? `${ui("for")} ${e.off ?? ""}` : ui(e.kind === "red" ? "Sent off" : "Booked")}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

const GROUPS: [string, [string, string, (v: number | null) => string, boolean?][]][] = [
  ["Attack", [["goals", "Goals", fmt.n], ["xg", "Expected goals", fmt.d2], ["shots", "Shots", fmt.n],
              ["shots_on_target", "On target", fmt.n], ["big_chances", "Big chances", fmt.n], ["box_entries", "Passes into the box", fmt.n]]],
  ["Possession", [["possession_pct", "Possession", fmt.pct], ["passes", "Passes", fmt.n], ["pass_completion", "Pass accuracy", fmt.frac],
                  ["progressive_passes", "Progressive passes", fmt.n], ["field_tilt_pct", "Field tilt", fmt.pct], ["corners", "Corners", fmt.n]]],
  ["Defence", [["ppda", "PPDA, lower is better", fmt.d1, true], ["high_turnovers", "High turnovers", fmt.n],
               ["pressures", "Pressures", fmt.n], ["tackles_won", "Tackles won", fmt.n], ["interceptions", "Interceptions", fmt.n]]],
  ["Discipline", [["fouls", "Fouls", fmt.n, true], ["yellow_cards", "Yellow cards", fmt.n, true], ["red_cards", "Red cards", fmt.n, true]]],
];

function Compare({ d, ui, ink }: Ctx) {
  return (
    <div className="cmp">
      {GROUPS.map(([g, rows]) => (
        <div key={g} className="cmp-group">
          <h4>{ui(g)}</h4>
          {rows.filter(([k]) => k in d.teams[d.home]).map(([k, label, f, low]) => {
            const h = Number(d.teams[d.home][k] ?? 0), a = Number(d.teams[d.away][k] ?? 0), m = Math.max(h, a) || 1;
            const lead = h === a ? "" : low ? (h < a ? "h" : "a") : h > a ? "h" : "a";
            return (
              <div key={k} className="cmp-row">
                <span className={`cmp-v ${lead === "h" ? "lead" : ""}`}>{f(d.teams[d.home][k] as number | null)}</span>
                <span className="cmp-bar cmp-left">{h > 0 && <i style={{ width: `${(h / m) * 100}%`, background: ink.home }} />}</span>
                <span className="cmp-label">{ui(label)}</span>
                <span className="cmp-bar">{a > 0 && <i style={{ width: `${(a / m) * 100}%`, background: ink.away }} />}</span>
                <span className={`cmp-v ${lead === "a" ? "lead" : ""}`}>{f(d.teams[d.away][k] as number | null)}</span>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

// ================================================================== Attack
function ShotMark({ s, color, hi }: { s: Shot; color: string; hi?: boolean }) {
  const r = 0.7 + Math.sqrt(s.xg) * 2.5 + (hi ? 0.4 : 0);
  if (s.outcome === "goal") return <g><circle cx={s.x} cy={s.y} r={r + 0.6} fill="#fff" /><circle cx={s.x} cy={s.y} r={r} fill={color} /></g>;
  if (s.outcome === "saved" || s.outcome === "post") return <circle cx={s.x} cy={s.y} r={r} fill={color} fillOpacity={0.55} stroke={color} strokeWidth={0.45} />;
  return <circle cx={s.x} cy={s.y} r={r} fill="var(--board)" fillOpacity={0.4} stroke={color} strokeWidth={hi ? 0.9 : 0.6} />;
}

function ShotKey({ color, ui }: { color: string; ui: Ui }) {
  const items: [string, Shot["outcome"]][] = [["Goal", "goal"], ["Saved", "saved"], ["Off target or blocked", "off_target"]];
  return (
    <div className="legend">
      {items.map(([l, o]) => (
        <span key={o}><svg viewBox="-3 -3 6 6" width="14" height="14" className="key-board">
          <rect x={-3} y={-3} width={6} height={6} fill="var(--board)" rx={1} />
          <ShotMark s={{ outcome: o, xg: 0.2, x: 0, y: 0 } as Shot} color={color} />
        </svg>{ui(l)}</span>
      ))}
    </div>
  );
}

function Attack(c: Ctx) {
  const { d, meta, ui, ink, show } = c;
  const [hi, setHi] = useState<number | null>(null);
  return (
    <div className="desk-grid">
      {[d.home, d.away].map((tm) => {
        const t = teamOf(meta, tm), shots = d.shots.filter((s) => s.team_id === tm), color = ink.of(tm);
        const xg = shots.reduce((a, s) => a + s.xg, 0), on = shots.filter((s) => s.outcome === "saved" || s.outcome === "goal").length;
        const top = d.players.filter((p) => p.team_id === tm && p.shots > 0).sort((a, b) => b.xg - a.xg).slice(0, 6);
        const topMax = Math.max(0.01, ...top.map((p) => p.xg));
        return (
          <Card key={tm} title={`${t.name}: ${ui("shots")}`} note={ui("Attacking the goal at the top. The bigger the circle, the better the chance.")} actions={<ShotKey color={color} ui={ui} />}>
            <div className="mini-kpis">
              <span><b>{shots.filter((s) => s.outcome === "goal").length}</b>{ui("goals")}</span>
              <span><b>{shots.length}</b>{ui("shots")}</span>
              <span><b>{on}</b>{ui("on target")}</span>
              <span><b>{xg.toFixed(2)}</b>xG</span>
              <span><b>{shots.length ? (xg / shots.length).toFixed(2) : "–"}</b>{ui("xG per shot")}</span>
            </div>
            <Board half label={`${t.name} shot map`}>
              {[...shots].sort((a, b) => b.xg - a.xg).map((s) => {
                const i = d.shots.indexOf(s);
                return (
                  <g key={i} onPointerMove={(e) => { setHi(i); show(e, `${s.clock} · ${s.player}`, [
                      { key: color, value: s.xg.toFixed(2), label: "xG" }, { value: ui(OUTCOME[s.outcome] ?? plain(s.outcome)), label: "" },
                      { value: ui(cap(plain(s.body_part))), label: ui(plain(s.situation)) }]); }} onPointerLeave={() => setHi(null)}>
                    <circle cx={s.x} cy={s.y} r={3.4} fill="transparent" />
                    <ShotMark s={s} color={color} hi={hi === i} />
                  </g>
                );
              })}
            </Board>
            <h4 className="sub-h">{ui("Chance quality by player")}</h4>
            {top.length ? (
              <div className="hbars">
                {top.map((p) => (
                  <div key={p.player_id} className="hbar">
                    <span className="hbar-name">{p.number} · {sur(p.name)}</span>
                    <span className="hbar-track"><i style={{ width: `${(p.xg / topMax) * 100}%`, background: color }} /></span>
                    <span className="hbar-v">{p.xg.toFixed(2)} <small>{p.shots} {ui(p.shots === 1 ? "shot" : "shots")}{p.goals ? `, ${p.goals} ${ui(p.goals === 1 ? "goal" : "goals")}` : ""}</small></span>
                  </div>
                ))}
              </div>
            ) : <p className="muted">{ui("No shots yet.")}</p>}
          </Card>
        );
      })}
      <Card wide title={ui("Every shot")} note={ui("Newest first. Point at a row to find the shot on its map.")}>
        <div className="table-wrap">
          <table className="dtable">
            <thead><tr><th>{ui("Time")}</th><th className="l">{ui("Player")}</th><th>xG</th><th className="l">{ui("Outcome")}</th><th className="l">{ui("Body part")}</th><th className="l">{ui("Situation")}</th><th>km/h</th></tr></thead>
            <tbody>{d.shots.map((s, i) => [s, i] as const).reverse().map(([s, i]) => (
              <tr key={i} className={`${hi === i ? "hi" : ""} ${s.outcome === "goal" ? "goal" : ""}`} onPointerEnter={() => setHi(i)} onPointerLeave={() => setHi(null)}>
                <td>{s.clock}</td><td className="l"><i className="team-dot" style={{ background: ink.of(s.team_id) }} />{s.player}</td>
                <td>{s.xg.toFixed(2)}</td><td className="l">{ui(OUTCOME[s.outcome] ?? plain(s.outcome))}</td>
                <td className="l">{ui(cap(plain(s.body_part)))}</td><td className="l">{ui(cap(plain(s.situation)))}</td><td>{s.speed_kmh ? Math.round(s.speed_kmh) : "–"}</td>
              </tr>
            ))}</tbody>
          </table>
          {!d.shots.length && <p className="muted">{ui("No shots yet.")}</p>}
        </div>
      </Card>
    </div>
  );
}

// ================================================================== Possession
function TeamSwitch({ d, meta, ink, ui, value, onChange, both }: Ctx & { value: string; onChange: (v: string) => void; both?: boolean }) {
  const opts = [d.home, d.away].map((tm) => ({ value: tm, label: teamOf(meta, tm).short_name, color: ink.of(tm) }));
  return <Segmented label={ui("Team")} value={value} onChange={onChange} options={both ? [{ value: "all", label: ui("Both teams") }, ...opts] : opts} />;
}

function Possession(c: Ctx) {
  const { d, meta, ui, ink, show } = c;
  const [team, setTeam] = useState(d.home);
  const [who, setWho] = useState<string>("team");
  const t = teamOf(meta, team), color = ink.of(team);
  // network drawn on the team's shape, so it reads like the line-up board
  const net = d.pass_networks[team] ?? { nodes: [], edges: [] };
  const slots = new Map(lineupSlots(t).map((s) => [s.player_id, s.base]));
  for (const e of d.key_events) if (e.kind === "sub" && e.team_id === team && e.off_id && slots.has(e.off_id)) slots.set(e.player_id, slots.get(e.off_id)!);
  const nodes = net.nodes.filter((n) => slots.has(n.player_id)).map((n) => { const [bx, by] = slots.get(n.player_id)!; return { ...n, x: 6 + bx * 1.08, y: by }; });
  const pos = new Map(nodes.map((n) => [n.player_id, n]));
  const maxE = Math.max(1, ...net.edges.map((e) => e.count)), maxN = Math.max(1, ...nodes.map((n) => n.passes));
  // touch density
  const squad = d.players.filter((p) => p.team_id === team && p.touches > 0).sort((a, b) => b.touches - a.touches);
  // a whole team reads better in 10 m squares; one player keeps 5 m detail
  const k = who === "team" ? 2 : 1, cell = 5 * k;
  const grid = new Map<string, number>();
  for (const p of who === "team" ? squad : squad.filter((s) => s.player_id === who))
    for (const [i0, j0, n] of d.heatmaps[p.player_id] ?? []) { const key = `${Math.floor(i0 / k)},${Math.floor(j0 / k)}`; grid.set(key, (grid.get(key) ?? 0) + n); }
  const gmax = Math.max(1, ...grid.values());
  const passers = d.players.filter((p) => p.team_id === team && p.passes > 0).sort((a, b) => b.passes_completed - a.passes_completed).slice(0, 8);
  return (
    <div className="desk-grid">
      <div className="toolbar hcard-wide"><TeamSwitch {...c} value={team} onChange={(v) => { setTeam(v); setWho("team"); }} /></div>
      <Card title={ui("Passing network")} note={ui("Drawn on the team's shape. Thicker lines: more passes between the pair. Bigger circles: more passes played.")}>
        <Board label={`${t.name} passing network`}>
          {[...net.edges].sort((a, b) => a.count - b.count).map((e, i) => {
            const a = pos.get(e.a), b = pos.get(e.b);
            return a && b ? <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#fff" strokeOpacity={0.15 + 0.65 * (e.count / maxE)}
                                  strokeWidth={0.2 + 1.6 * (e.count / maxE)} strokeLinecap="round" className="edge"
                                  onPointerMove={(p) => show(p, `${sur(a.name)} and ${sur(b.name)}`, [{ key: color, value: String(e.count), label: ui("passes between them") }])} /> : null;
          })}
          {nodes.map((n) => (
            <g key={n.player_id} onPointerMove={(p) => show(p, n.name, [{ key: color, value: String(n.passes), label: ui("passes played") }])}>
              <circle cx={n.x} cy={n.y} r={1.9 + 2.3 * Math.sqrt(n.passes / maxN)} fill={color} stroke="var(--board)" strokeWidth={0.6} />
              <text x={n.x} y={n.y + 0.9} textAnchor="middle" className="board-num" fill={inkOn(color)}>{n.number}</text>
              <text x={n.x} y={n.y + 6.4} textAnchor="middle" className="board-name">{sur(n.name)}</text>
            </g>
          ))}
        </Board>
      </Card>
      <Card title={ui("Where they had the ball")} note={ui("Touch density, attacking to the right.")}
            actions={<select className="select" value={who} onChange={(e) => setWho(e.target.value)} aria-label={ui("Player")}>
              <option value="team">{ui("Whole team")}</option>
              {squad.map((p) => <option key={p.player_id} value={p.player_id}>{p.number} · {p.name} ({p.touches})</option>)}
            </select>}>
        <Board label={`${t.name} touch map`}>
          <defs><filter id="soft" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur stdDeviation={k === 2 ? 2.6 : 1.3} /></filter></defs>
          <g filter="url(#soft)">
            {[...grid].map(([key, n]) => {
              const [i, j] = key.split(",").map(Number), v = n / gmax;
              return v < 0.12 ? null : <rect key={key} x={i * cell} y={j * cell} width={Math.min(cell, 105 - i * cell)} height={Math.min(cell, 68 - j * cell)} fill={color} fillOpacity={Math.min(0.95, 0.1 + 0.85 * v)} />;
            })}
          </g>
        </Board>
        <div className="seq-key"><span>{ui("Fewer touches")}</span><i style={{ background: `linear-gradient(90deg, transparent, ${color})` }} /><span>{ui("More")}</span></div>
      </Card>
      <Card title={ui("Territory")} note={ui("Who had more of the ball in each zone. {home} attack to the right.", { home: meta.home.short_name })}>
        <Board label={ui("Territory")}>
          {d.zones.map((z) => {
            const s = z.share; if (s == null) return null;
            const tm = s >= 0.55 ? d.home : s <= 0.45 ? d.away : null;
            const strength = Math.min(1, Math.abs(s - 0.5) / 0.3);
            const pct = tm === d.away ? 1 - s : s;
            const zw = 105 / 6, zh = 68 / 3;
            return (
              <g key={`${z.i}${z.j}`} onPointerMove={(p) => show(p, ui("Touches in this zone"), [
                  { key: ink.home, value: String(z[d.home] ?? 0), label: meta.home.short_name },
                  { key: ink.away, value: String(z[d.away] ?? 0), label: meta.away.short_name }])}>
                <rect x={z.i * zw + 0.5} y={z.j * zh + 0.5} width={zw - 1} height={zh - 1} rx={1}
                      fill={tm ? ink.of(tm) : "#8A949E"} fillOpacity={tm ? 0.5 + 0.45 * strength : 0.45} />
                <text x={z.i * zw + zw / 2} y={z.j * zh + zh / 2 + 1.3} textAnchor="middle" className="board-zone">{Math.round(pct * 100)}%</text>
              </g>
            );
          })}
        </Board>
        <Legend items={[{ color: ink.home, label: `${meta.home.short_name} ${ui("on top")}` }, { color: "#8A949E", label: ui("Even (45–55%)") }, { color: ink.away, label: `${meta.away.short_name} ${ui("on top")}` }]} />
      </Card>
      <Card title={ui("Most passes completed")} note={ui("With pass accuracy and passes that moved the ball forward.")}>
        <div className="hbars">
          {passers.map((p) => (
            <div key={p.player_id} className="hbar">
              <span className="hbar-name">{p.number} · {sur(p.name)}</span>
              <span className="hbar-track"><i style={{ width: `${(p.passes_completed / Math.max(1, passers[0].passes_completed)) * 100}%`, background: color }} /></span>
              <span className="hbar-v">{p.passes_completed} <small>{fmt.frac(p.pass_completion)} · {p.progressive_passes} {ui("forward")}</small></span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

// ================================================================== Defence
const DEF_LABEL: Record<string, string> = { tackle: "Tackle won", interception: "Interception", block: "Block", clearance: "Clearance" };

function DefMark({ type, x, y, color, s = 1 }: { type: string; x: number; y: number; color: string; s?: number }) {
  const p = { fill: color, stroke: "var(--board)", strokeWidth: 0.35 * s };
  if (type === "tackle") return <circle cx={x} cy={y} r={1.3 * s} {...p} />;
  if (type === "interception") return <path d={`M${x},${y - 1.6 * s} L${x + 1.6 * s},${y} L${x},${y + 1.6 * s} L${x - 1.6 * s},${y} Z`} {...p} />;
  if (type === "block") return <path d={`M${x},${y - 1.6 * s} L${x + 1.5 * s},${y + 1.2 * s} L${x - 1.5 * s},${y + 1.2 * s} Z`} {...p} />;
  return <rect x={x - 1.15 * s} y={y - 1.15 * s} width={2.3 * s} height={2.3 * s} {...p} />;
}

function Defence(c: Ctx) {
  const { d, meta, ui, ink, show } = c;
  const [team, setTeam] = useState(d.home);
  const t = teamOf(meta, team), color = ink.of(team);
  const acts = d.defence[team] ?? [];
  const high = acts.filter((a) => a[0] >= 52.5).length;
  const counts = Object.keys(DEF_LABEL).map((k) => [k, acts.filter((a) => a[2] === k).length] as const);
  const W = 560, H = 230, L = 32, B = 28, T = 12;
  const vals = d.ppda.flatMap((r) => [num(r[d.home]), num(r[d.away])]).filter((v): v is number => v != null);
  const maxP = Math.max(6, ...vals) * 1.1;
  const step = (W - L - 10) / Math.max(1, d.ppda.length), bw = Math.min(22, step / 2 - 3);
  const Y = (v: number) => H - B - (v / maxP) * (H - B - T);
  const leaders = d.players.filter((p) => p.team_id === team).map((p) => ({ ...p, won: p.tackles_won + p.interceptions }))
    .filter((p) => p.won + p.pressures > 0).sort((a, b) => b.won - a.won || b.pressures - a.pressures).slice(0, 8);
  return (
    <div className="desk-grid">
      <div className="toolbar hcard-wide"><TeamSwitch {...c} value={team} onChange={setTeam} /></div>
      <Card title={ui("Where they won the ball back")}
            note={ui("{n} regains, {h} of them in the opponent's half (shaded). Attacking to the right.", { n: acts.length, h: high })}>
        <Board label={`${t.name} ball regains`}>
          <rect x={52.5} y={0} width={52.5} height={68} fill="#fff" fillOpacity={0.05} />
          {acts.map((a, i) => (
            <g key={i} onPointerMove={(p) => show(p, `${a[3]} · ${a[4]}`, [{ key: color, value: ui(DEF_LABEL[a[2]]), label: a[0] >= 52.5 ? ui("in their half") : ui("in our half") }])}>
              <circle cx={a[0]} cy={a[1]} r={2.6} fill="transparent" />
              <DefMark type={a[2]} x={a[0]} y={a[1]} color={color} />
            </g>
          ))}
        </Board>
        <div className="legend">
          {counts.map(([k, n]) => <span key={k}><svg viewBox="-2.2 -2.2 4.4 4.4" width="13" height="13"><DefMark type={k} x={0} y={0} color={color} /></svg>{ui(DEF_LABEL[k])} <b>{n}</b></span>)}
        </div>
      </Card>
      <Card title={ui("Pressing intensity")} note={ui("PPDA in each 15-minute spell: opponent passes allowed per defensive action. Shorter bars mean harder pressing.")}
            actions={<Legend items={[{ color: ink.home, label: meta.home.short_name }, { color: ink.away, label: meta.away.short_name }]} />}>
        <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label={ui("Pressing intensity")} onPointerLeave={c.hide}>
          {niceTicks(maxP).map((v) => <g key={v}><line x1={L} x2={W - 10} y1={Y(v)} y2={Y(v)} className="grid" /><text x={L - 8} y={Y(v) + 4} className="tick" textAnchor="end">{v}</text></g>)}
          {d.ppda.map((r, i) => {
            const x0 = L + i * step + step / 2;
            return (
              <g key={r.window} onPointerMove={(p) => show(p, r.label, [
                  { key: ink.home, value: fmt.d1(num(r[d.home])), label: `${meta.home.short_name} PPDA` },
                  { key: ink.away, value: fmt.d1(num(r[d.away])), label: `${meta.away.short_name} PPDA` }])}>
                <rect x={x0 - step / 2} y={T} width={step} height={H - B - T} className="hit" />
                {[d.home, d.away].map((tm, k) => {
                  const v = num(r[tm]); if (v == null || v <= 0) return null;
                  return <path key={tm} d={bar(x0 + (k === 0 ? -bw - 1 : 1), H - B, bw, H - B - Y(v), true)} fill={ink.of(tm)} />;
                })}
                <text x={x0} y={H - 8} className="tick" textAnchor="middle">{r.label}</text>
              </g>
            );
          })}
          <line x1={L} x2={W - 10} y1={H - B} y2={H - B} className="axis" />
        </svg>
      </Card>
      <Card wide title={ui("Defensive leaders")} note={ui("Ball won is tackles won plus interceptions.")}>
        <div className="table-wrap">
          <table className="dtable">
            <thead><tr><th className="l">{ui("Player")}</th><th>{ui("Ball won")}</th><th>{ui("Tackles won")}</th><th>{ui("Interceptions")}</th><th>{ui("Pressures")}</th><th>{ui("Fouls")}</th><th>{ui("Cards")}</th></tr></thead>
            <tbody>{leaders.map((p) => (
              <tr key={p.player_id}><td className="l"><span className="num-badge" style={{ background: color, color: inkOn(color) }}>{p.number}</span>{p.name}<small> {p.position}</small></td>
                <td className="strong">{p.won}</td><td>{p.tackles_won}</td><td>{p.interceptions}</td><td>{p.pressures}</td><td>{p.fouls}</td>
                <td>{p.yellow_cards ? <i className="card-chip y" title={ui("Booked")} /> : null}{p.red_card ? <i className="card-chip r" title={ui("Sent off")} /> : null}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

// ================================================================== Line-ups
function Lineups(c: Ctx & { snap?: Snapshot }) {
  const { d, meta, ui, ink, snap, show } = c;
  const onPitch = new Set(d.players.filter((p) => p.on_pitch).map((p) => p.player_id));
  const cards = (pid: string) => d.key_events.filter((e) => (e.kind === "yellow" || e.kind === "red") && e.player_id === pid);
  const goals = (pid: string) => d.key_events.filter((e) => e.kind === "goal" && e.player_id === pid).length;
  const shape = (t: Team, home: boolean) => {
    const subs = d.key_events.filter((e) => e.kind === "sub" && e.team_id === t.team_id);
    return lineupSlots(t).map((s) => {
      let pid = s.player_id, name = s.name, number = s.number;
      for (const e of subs) if (e.off_id === pid) { const p = d.players.find((x) => x.player_id === e.player_id); if (p) { pid = p.player_id; name = p.name; number = p.number; } }
      const [bx, by] = s.base;
      return { pid, name, number, x: home ? 3 + bx * 0.56 : 102 - bx * 0.56, y: home ? by : 68 - by, gone: !onPitch.has(pid), subbed: pid !== s.player_id };
    });
  };
  return (
    <div className="desk-grid">
      <Card wide title={ui("On the pitch now")}
            note={ui("Substitutes stand where the man they replaced played. A player sent off is faded. Point at a player for his match so far.")}
            actions={<div className="formations">
              <span><i className="team-dot" style={{ background: ink.home }} />{meta.home.short_name} <b>{d.formations[meta.home.team_id]}</b></span>
              <span><i className="team-dot" style={{ background: ink.away }} />{meta.away.short_name} <b>{d.formations[meta.away.team_id]}</b></span>
            </div>}>
        <Board label={ui("Line-ups")} className="board-wide">
          {([[meta.home, true], [meta.away, false]] as [Team, boolean][]).map(([t, home]) => shape(t, home).map((s) => {
            const col = ink.of(t.team_id), row = d.players.find((p) => p.player_id === s.pid);
            return (
              <g key={s.pid} opacity={s.gone ? 0.35 : 1} onPointerMove={(p) => row && show(p, `${row.number} · ${row.name}`, [
                  { key: col, value: `${row.minutes}'`, label: ui("played") }, { value: String(row.touches), label: ui("touches") },
                  { value: `${row.passes_completed}/${row.passes}`, label: ui("passes completed") }, { value: `${row.distance_km.toFixed(1)} km`, label: ui("covered") }])}>
                <circle cx={s.x} cy={s.y} r={2.3} fill={col} stroke={s.subbed ? "#fff" : "var(--board)"} strokeWidth={s.subbed ? 0.45 : 0.6} strokeDasharray={s.subbed ? "0.8 0.6" : undefined} />
                <text x={s.x} y={s.y + 0.75} textAnchor="middle" className="board-num" fill={inkOn(col)}>{s.number}</text>
                <text x={s.x} y={s.y + 4.9} textAnchor="middle" className="board-name">{sur(s.name)}</text>
                {Array.from({ length: goals(s.pid) }, (_, i) => <circle key={i} cx={s.x - 2.7 - i * 1.4} cy={s.y - 2.1} r={0.7} fill="#fff" />)}
                {cards(s.pid).map((cd, i) => <rect key={i} x={s.x + 1.9 + i * 1.3} y={s.y - 3.2} width={1.1} height={1.5} rx={0.2} fill={cd.kind === "red" ? RED : YELLOW} />)}
              </g>
            );
          }))}
        </Board>
        <div className="legend">
          <span><svg viewBox="-2 -2 4 4" width="14" height="14" className="key-board"><rect x={-2} y={-2} width={4} height={4} rx={0.8} fill="var(--board)" /><circle r={0.9} fill="#fff" /></svg>{ui("Goal")}</span>
          <span><i className="card-chip y" />{ui("Booked")}</span>
          <span><svg viewBox="-3 -3 6 6" width="14" height="14"><circle r={2.4} fill="#8A949E" stroke="currentColor" strokeWidth={0.5} strokeDasharray="0.8 0.6" /></svg>{ui("Came off the bench")}</span>
        </div>
      </Card>
      <div className="hcard-wide"><MatchCentre snap={snap} meta={meta} ui={ui} sheetsOnly /></div>
    </div>
  );
}

// ================================================================== Players
const COLS: [keyof PlayerRow, string, (p: PlayerRow) => string, string?][] = [
  ["minutes", "Min", (p) => String(p.minutes), "Minutes played"], ["touches", "Touches", (p) => String(p.touches)],
  ["passes_completed", "Passes", (p) => `${p.passes_completed}/${p.passes}`, "Completed / attempted"],
  ["pass_completion", "Acc.", (p) => fmt.frac(p.pass_completion), "Pass accuracy"],
  ["progressive_passes", "Fwd", (p) => String(p.progressive_passes), "Passes that moved the ball well forward"],
  ["key_passes", "Key P.", (p) => String(p.key_passes), "Passes that set up a shot"],
  ["shots", "Shots", (p) => `${p.shots_on_target}/${p.shots}`, "On target / total"], ["xg", "xG", (p) => p.xg.toFixed(2), "Expected goals"],
  ["goals", "G", (p) => String(p.goals), "Goals"], ["assists", "A", (p) => String(p.assists), "Assists"],
  ["dribbles", "Drib.", (p) => String(p.dribbles), "Dribbles"], ["tackles_won", "Tkl", (p) => String(p.tackles_won), "Tackles won"],
  ["interceptions", "Int.", (p) => String(p.interceptions), "Interceptions"], ["pressures", "Press.", (p) => String(p.pressures), "Pressures"],
  ["fouls", "Fouls", (p) => String(p.fouls)], ["distance_km", "km", (p) => p.distance_km.toFixed(1), "Distance covered"],
  ["top_speed_kmh", "km/h", (p) => p.top_speed_kmh.toFixed(1), "Top speed"],
];

function Players(c: Ctx & { clockRef: MutableRefObject<ClockRef> }) {
  const { d, ui, ink } = c;
  const [team, setTeam] = useState<string>("all");
  const [sort, setSort] = useState<keyof PlayerRow>("touches");
  const [open, setOpen] = useState<string | null>(null);
  const rows = useMemo(() => d.players.filter((p) => (team === "all" || p.team_id === team) && (p.minutes > 0 || p.touches > 0))
    .sort((a, b) => Number(b[sort] ?? 0) - Number(a[sort] ?? 0)), [d, team, sort]);
  const colMax = useMemo(() => Object.fromEntries(COLS.map(([k]) => [k, Math.max(0.0001, ...d.players.map((p) => Number(p[k] ?? 0)))])), [d]);
  const sel = open ? d.players.find((p) => p.player_id === open) : null;
  return (
    <div className="desk-grid">
      <div className="toolbar hcard-wide">
        <TeamSwitch {...c} both value={team} onChange={setTeam} />
        <span className="muted">{ui("Sort by any column. Open a player to see his passes and touches.")}</span>
      </div>
      {sel && <PlayerProfile {...c} p={sel} onClose={() => setOpen(null)} />}
      <div className="hcard hcard-wide table-card">
        <div className="table-wrap tall">
          <table className="dtable sortable">
            <thead><tr><th className="l sticky">{ui("Player")}</th>{COLS.map(([k, label, , title]) => (
              <th key={k} aria-sort={sort === k ? "descending" : "none"} title={title ? ui(title) : undefined}>
                <button onClick={() => setSort(k)}>{ui(label)}{sort === k && <span aria-hidden="true"> ▾</span>}</button></th>))}</tr></thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.player_id} className={`${p.on_pitch ? "" : "off"} ${open === p.player_id ? "hi" : ""}`}>
                  <td className="l sticky"><button className="row-open" aria-expanded={open === p.player_id} onClick={() => setOpen(open === p.player_id ? null : p.player_id)}>
                    <span className="num-badge" style={{ background: ink.of(p.team_id), color: inkOn(ink.of(p.team_id)) }}>{p.number}</span>
                    <span className="row-name">{p.name}</span><small>{p.position}</small>
                    {p.yellow_cards > 0 && <i className="card-chip y" title={ui("Booked")} />}{p.red_card && <i className="card-chip r" title={ui("Sent off")} />}</button></td>
                  {COLS.map(([k, , f]) => (
                    <td key={k} className={sort === k ? "sorted" : ""}>
                      {sort === k && <i className="cell-bar" style={{ width: `${(Number(p[k] ?? 0) / colMax[k]) * 100}%`, background: ink.of(p.team_id) }} />}
                      <span>{f(p)}</span>
                    </td>))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function PlayerProfile({ d, meta, ui, ink, show, p, onClose, clockRef }: Ctx & { p: PlayerRow; onClose: () => void; clockRef: MutableRefObject<ClockRef> }) {
  const [det, setDet] = useState<PlayerDetail | null>(null);
  const box = useRef<HTMLElement>(null);
  useEffect(() => { box.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [p.player_id]);
  useEffect(() => {
    let alive = true;
    fetch(`/api/analysis/player?match=${encodeURIComponent(meta.match_id)}&player=${p.player_id}&upto=${Math.max(0, matchTime(clockRef.current)).toFixed(0)}`)
      .then((r) => r.json()).then((x) => alive && setDet(x)).catch(() => {});
    return () => { alive = false; };
  }, [p.player_id, d.elapsed, meta.match_id, clockRef]);
  const color = ink.of(p.team_id), team = teamOf(meta, p.team_id);
  const squad = d.players.filter((x) => x.team_id === p.team_id && x.minutes > 0);
  const best = (f: (x: PlayerRow) => number) => Math.max(0.0001, ...squad.map(f));
  const tiles: [string, string, number, number][] = [
    ["Touches", String(p.touches), p.touches, best((x) => x.touches)],
    ["Pass accuracy", fmt.frac(p.pass_completion), p.pass_completion ?? 0, best((x) => x.pass_completion ?? 0)],
    ["Forward passes", String(p.progressive_passes), p.progressive_passes, best((x) => x.progressive_passes)],
    ["Shots · xG", `${p.shots} · ${p.xg.toFixed(2)}`, p.xg, best((x) => x.xg)],
    ["Ball won", String(p.tackles_won + p.interceptions), p.tackles_won + p.interceptions, best((x) => x.tackles_won + x.interceptions)],
    ["Distance", `${p.distance_km.toFixed(1)} km`, p.distance_km, best((x) => x.distance_km)],
  ];
  const done = det?.passes.filter((q) => q.ok).length ?? 0;
  return (
    <section className="hcard hcard-wide profile" aria-label={p.name} ref={box}>
      <header className="profile-head">
        <span className="profile-num" style={{ background: color, color: inkOn(color) }}>{p.number}</span>
        <div><h3>{p.name}</h3><p className="muted">{p.position} · {team.name} · {p.minutes}' {ui("played")}{p.on_pitch ? "" : ` · ${ui("off the pitch")}`}</p></div>
        <button className="icon-btn" onClick={onClose} aria-label={ui("Close")}>×</button>
      </header>
      <div className="profile-tiles">
        {tiles.map(([label, v, n, m]) => (
          <div key={label} className="ptile">
            <span className="ptile-label">{ui(label)}</span><b>{v}</b>
            <span className="meter" title={ui("Against the best in his team today")}><i style={{ width: `${Math.min(100, (n / m) * 100)}%`, background: color }} /></span>
          </div>
        ))}
      </div>
      <p className="muted small">{ui("Meters compare him with the best in his team today.")}</p>
      <div className="profile-maps">
        <div>
          <h4 className="sub-h">{ui("Passes")} <small className="muted">{done}/{det?.passes.length ?? 0} · {ui("arrows completed, faint lines lost")}</small></h4>
          <Board label={`${p.name} passes`}>
            <defs><marker id={`arw-${p.player_id}`} viewBox="0 0 6 6" refX="5" refY="3" markerWidth="3.2" markerHeight="3.2" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill={color} /></marker></defs>
            {(det?.passes ?? []).map((q, i) => (
              <line key={i} x1={q.x0} y1={q.y0} x2={q.x1} y2={q.y1} stroke={q.ok ? color : "#fff"} strokeOpacity={q.ok ? 0.95 : 0.35}
                    strokeWidth={q.progressive ? 0.65 : 0.4} strokeDasharray={q.ok ? undefined : "1 0.8"} markerEnd={q.ok ? `url(#arw-${p.player_id})` : undefined}
                    onPointerMove={(e) => show(e, q.clock, [{ key: color, value: ui(q.ok ? "Completed" : "Lost"), label: q.to ? `${ui("to")} ${sur(q.to)}` : "" }])} />
            ))}
          </Board>
        </div>
        <div>
          <h4 className="sub-h">{ui("On the ball")} <small className="muted">{det?.touches.length ?? 0} {ui("actions")}</small></h4>
          <Board label={`${p.name} touches`}>
            {(det?.touches ?? []).map(([x, y], i) => <circle key={i} cx={x} cy={y} r={1} fill={color} fillOpacity={0.8} stroke="var(--board)" strokeWidth={0.25} />)}
          </Board>
        </div>
        <div>
          <h4 className="sub-h">{ui("His match")}</h4>
          <ol className="actions">
            {(det?.actions ?? []).slice().reverse().map((a, i) => (
              <li key={i}><span className="tl-min">{a.clock.replace(/:\d\d$/, "'")}</span><span>{ui(cap(plain(a.type)))}{a.outcome ? <small className="muted"> · {ui(plain(a.outcome))}</small> : null}</span></li>
            ))}
            {det && !det.actions.length && <li className="muted">{ui("Nothing notable yet.")}</li>}
          </ol>
        </div>
      </div>
    </section>
  );
}
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

// ================================================================== Physical
function Physical({ d, meta, ui, ink, show }: Ctx) {
  const squad = (tm: string) => d.players.filter((p) => p.team_id === tm && p.distance_km > 0);
  const tot = (tm: string) => squad(tm).reduce((a, p) => a + p.distance_km, 0);
  const kpis: [string, (tm: string) => number, (v: number) => string][] = [
    ["Distance covered", tot, (v) => `${v.toFixed(1)} km`],
    ["Average per player", (tm) => tot(tm) / Math.max(1, squad(tm).length), (v) => `${v.toFixed(1)} km`],
    ["Top speed", (tm) => Math.max(0, ...squad(tm).map((p) => p.top_speed_kmh)), (v) => `${v.toFixed(1)} km/h`],
  ];
  const max = Math.max(1, ...d.players.map((r) => r.distance_km));
  const fastest = [...d.players].filter((p) => p.top_speed_kmh > 0).sort((a, b) => b.top_speed_kmh - a.top_speed_kmh).slice(0, 8);
  const floor = 20, fmax = Math.max(floor + 1, fastest[0]?.top_speed_kmh ?? floor + 1);
  return (
    <div className="desk-grid">
      <div className="kpis hcard-wide kpis-3">
        {kpis.map(([label, f, show_]) => {
          const h = f(d.home), a = f(d.away), share = h + a > 0 ? h / (h + a) : 0.5;
          return (
            <div key={label} className="kpi">
              <span className="kpi-label">{ui(label)}</span>
              <span className="kpi-vals"><b className={h > a ? "lead" : ""}>{show_(h)}</b><b className={a > h ? "lead" : ""}>{show_(a)}</b></span>
              <span className="kpi-split" aria-hidden="true"><i style={{ flexGrow: share, background: ink.home }} /><i style={{ flexGrow: 1 - share, background: ink.away }} /></span>
              <span className="kpi-teams"><span>{meta.home.short_name}</span><span>{meta.away.short_name}</span></span>
            </div>
          );
        })}
      </div>
      {[d.home, d.away].map((tm) => (
        <Card key={tm} title={`${teamOf(meta, tm).name}: ${ui("distance covered")}`} note={ui("Substitutes cover less because they play less. The minutes are beside each bar.")}>
          <div className="hbars">
            {squad(tm).sort((a, b) => b.distance_km - a.distance_km).map((p) => (
              <div key={p.player_id} className="hbar" onPointerMove={(e) => show(e, p.name, [{ key: ink.of(tm), value: `${p.distance_km.toFixed(2)} km`, label: `${ui("in")} ${p.minutes}'` }, { value: `${p.top_speed_kmh.toFixed(1)} km/h`, label: ui("top speed") }])} onPointerLeave={undefined}>
                <span className="hbar-name">{p.number} · {sur(p.name)}</span>
                <span className="hbar-track"><i style={{ width: `${(p.distance_km / max) * 100}%`, background: ink.of(tm) }} /></span>
                <span className="hbar-v">{p.distance_km.toFixed(1)} <small>km · {p.minutes}'</small></span>
              </div>
            ))}
          </div>
        </Card>
      ))}
      <Card wide title={ui("Fastest players")} note={ui("Bars start at 20 km/h so the gaps at the top are easy to see.")}
            actions={<Legend items={[{ color: ink.home, label: meta.home.short_name }, { color: ink.away, label: meta.away.short_name }]} />}>
        <div className="hbars">
          {fastest.map((p) => (
            <div key={p.player_id} className="hbar">
              <span className="hbar-name">{p.number} · {p.name}</span>
              <span className="hbar-track"><i style={{ width: `${((p.top_speed_kmh - floor) / (fmax - floor)) * 100}%`, background: ink.of(p.team_id) }} /></span>
              <span className="hbar-v">{p.top_speed_kmh.toFixed(1)} <small>km/h</small></span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
