import { useEffect, useMemo, useState, type MutableRefObject, type ReactNode } from "react";
import { MatchCentre } from "./MatchCentre";
import { lineupSlots } from "./motion";
import { matchTime, type ClockRef } from "./stream";
import type { KeyEvent, Meta, Snapshot, Team } from "./types";

type Ui = (t: string, vars?: Record<string, string | number>) => string;

interface PlayerRow {
  player_id: string; name: string; number: number; position: string; team_id: string; starter: boolean;
  on_pitch: boolean; minutes: number; touches: number; passes: number; passes_completed: number;
  pass_completion: number | null; progressive_passes: number; key_passes: number; shots: number;
  shots_on_target: number; xg: number; goals: number; assists: number; dribbles: number; tackles_won: number;
  interceptions: number; pressures: number; fouls: number; yellow_cards: number; red_card: boolean;
  distance_km: number; top_speed_kmh: number;
}
interface Shot { team_id: string; player: string; clock: string; minute: number; x: number; y: number; xg: number;
  outcome: string; body_part: string; situation: string; speed_kmh?: number }
interface Network { nodes: { player_id: string; name: string; number: number; x: number; y: number; passes: number }[];
  edges: { a: string; b: string; count: number }[] }
interface Analysis {
  ready: boolean; clock: string; elapsed: number; home: string; away: string; formations: Record<string, string>;
  teams: Record<string, Record<string, number | null>>; players: PlayerRow[]; shots: Shot[];
  xg_flow: Record<string, [number, number][]>; pass_networks: Record<string, Network>;
  heatmaps: Record<string, [number, number, number][]>; key_events: KeyEvent[];
}

const TABS = ["Overview", "Line-ups", "Players", "Shots", "Passing", "Heatmaps", "Physical"] as const;
type Tab = typeof TABS[number];
const sur = (n: string) => n.split(" ").slice(-1)[0];
const pct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v * 100)}%`);

/** The analyst hub: the live data a club's analysts work from, in tabs under the broadcast. */
export function AnalystHub({ meta, snap, clockRef, ui }: { meta: Meta; snap?: Snapshot; clockRef: MutableRefObject<ClockRef>; ui: Ui }) {
  const [tab, setTab] = useState<Tab>("Overview");
  const [data, setData] = useState<Analysis | null>(null);

  // Recomputed on the server from the events up to the viewer's clock, every few seconds.
  useEffect(() => {
    let alive = true;
    const load = () => {
      const upto = Math.max(0, matchTime(clockRef.current));
      fetch(`/api/analysis?match=${encodeURIComponent(meta.match_id)}&upto=${upto.toFixed(0)}`)
        .then((r) => (r.ok ? r.json() : null)).then((d) => { if (alive && d?.ready) setData(d); }).catch(() => {});
    };
    load();
    const id = window.setInterval(load, 4000);
    return () => { alive = false; window.clearInterval(id); };
  }, [meta.match_id, clockRef]);

  return (
    <section className="hub" aria-label={ui("Analyst hub")}>
      <div className="hub-head">
        <h2 className="hub-title">{ui("Analyst hub")}</h2>
        {data && <span className="hub-clock">{ui("Data to")} {data.clock}</span>}
      </div>
      <div className="hub-tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{ui(t)}</button>
        ))}
      </div>
      <div className="hub-body" role="tabpanel">
        {!data ? <p className="hub-wait">{ui("Waiting for kick-off…")}</p>
          : tab === "Overview" ? <Overview d={data} meta={meta} ui={ui} />
          : tab === "Line-ups" ? <Lineups d={data} meta={meta} snap={snap} ui={ui} />
          : tab === "Players" ? <Players d={data} meta={meta} ui={ui} />
          : tab === "Shots" ? <Shots d={data} meta={meta} ui={ui} />
          : tab === "Passing" ? <Passing d={data} meta={meta} ui={ui} />
          : tab === "Heatmaps" ? <Heatmaps d={data} meta={meta} ui={ui} />
          : <Physical d={data} meta={meta} ui={ui} />}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ shared pieces
function Pitch({ children, half }: { children?: ReactNode; half?: boolean }) {
  const line = { fill: "none", stroke: "rgba(255,255,255,.75)", strokeWidth: 0.35 };
  return (
    <svg className="hub-pitch" viewBox={half ? "50 -2 57 72" : "-2 -2 109 72"} role="img" aria-label="Pitch">
      <rect x={-2} y={-2} width={109} height={72} fill="#2E7D4F" />
      {Array.from({ length: 7 }, (_, i) => <rect key={i} x={i * 15} y={0} width={7.5} height={68} fill="rgba(255,255,255,.035)" />)}
      <rect x={0} y={0} width={105} height={68} {...line} />
      <line x1={52.5} y1={0} x2={52.5} y2={68} {...line} />
      <circle cx={52.5} cy={34} r={9.15} {...line} />
      {[0, 105].map((x) => (
        <g key={x}>
          <rect x={x === 0 ? 0 : 88.5} y={13.85} width={16.5} height={40.3} {...line} />
          <rect x={x === 0 ? 0 : 99.5} y={24.85} width={5.5} height={18.3} {...line} />
          <circle cx={x === 0 ? 11 : 94} cy={34} r={0.4} fill="#fff" />
        </g>
      ))}
      {children}
    </svg>
  );
}

function TeamSwitch({ meta, value, onChange }: { meta: Meta; value: string; onChange: (t: string) => void }) {
  return (
    <div className="hub-seg">
      {[meta.home, meta.away].map((t) => (
        <button key={t.team_id} className={value === t.team_id ? "on" : ""} style={{ ["--team" as string]: t.colors[0] }}
                onClick={() => onChange(t.team_id)}>{t.short_name}</button>
      ))}
    </div>
  );
}

const teamOf = (meta: Meta, id: string): Team => (id === meta.away.team_id ? meta.away : meta.home);

// ------------------------------------------------------------------ Overview
const COMPARE: [string, string, (v: number | null) => string][] = [
  ["possession_pct", "Possession", (v) => `${Math.round(v ?? 0)}%`],
  ["xg", "Expected goals (xG)", (v) => (v ?? 0).toFixed(2)],
  ["shots", "Shots", (v) => String(v ?? 0)],
  ["shots_on_target", "On target", (v) => String(v ?? 0)],
  ["big_chances", "Big chances", (v) => String(v ?? 0)],
  ["passes", "Passes", (v) => String(v ?? 0)],
  ["pass_completion", "Pass accuracy", (v) => pct(v)],
  ["progressive_passes", "Progressive passes", (v) => String(v ?? 0)],
  ["box_entries", "Box entries", (v) => String(v ?? 0)],
  ["field_tilt_pct", "Field tilt", (v) => `${Math.round(v ?? 0)}%`],
  ["ppda", "PPDA (lower = more pressing)", (v) => (v == null ? "–" : v.toFixed(1))],
  ["high_turnovers", "High turnovers", (v) => String(v ?? 0)],
  ["pressures", "Pressures", (v) => String(v ?? 0)],
  ["tackles_won", "Tackles won", (v) => String(v ?? 0)],
  ["interceptions", "Interceptions", (v) => String(v ?? 0)],
  ["corners", "Corners", (v) => String(v ?? 0)],
  ["fouls", "Fouls", (v) => String(v ?? 0)],
  ["yellow_cards", "Yellow cards", (v) => String(v ?? 0)],
  ["red_cards", "Red cards", (v) => String(v ?? 0)],
];

function Overview({ d, meta, ui }: { d: Analysis; meta: Meta; ui: Ui }) {
  const h = d.teams[d.home], a = d.teams[d.away];
  return (
    <div className="hub-grid">
      <div className="hub-card">
        <h3>{ui("Team comparison")}</h3>
        <div className="cmp-head"><b style={{ color: meta.home.colors[0] }}>{meta.home.short_name}</b><b style={{ color: meta.away.colors[0] }}>{meta.away.short_name}</b></div>
        {COMPARE.map(([k, label, fmt]) => {
          const hv = Number(h[k] ?? 0), av = Number(a[k] ?? 0);
          const lowBetter = k === "ppda" || k === "fouls" || k.endsWith("cards");
          const share = hv + av > 0 ? hv / (hv + av) : 0.5;
          const hiH = lowBetter ? hv < av : hv > av, hiA = lowBetter ? av < hv : av > hv;
          return (
            <div key={k} className="cmp-row">
              <span className={hiH ? "cmp-v cmp-win" : "cmp-v"}>{fmt(h[k] as number | null)}</span>
              <span className="cmp-mid">
                <span className="cmp-label">{ui(label)}</span>
                <span className="cmp-bar"><i style={{ width: `${share * 100}%`, background: meta.home.colors[0] }} /><i style={{ width: `${(1 - share) * 100}%`, background: meta.away.colors[0] }} /></span>
              </span>
              <span className={hiA ? "cmp-v cmp-win" : "cmp-v"}>{fmt(a[k] as number | null)}</span>
            </div>
          );
        })}
      </div>
      <div className="hub-card">
        <h3>{ui("xG race")}</h3>
        <XgRace d={d} meta={meta} />
        <p className="hub-note">{ui("Cumulative expected goals: the quality of chances each side has created. Dots are goals.")}</p>
        <h3 className="hub-sub">{ui("Key events")}</h3>
        <MatchCentre.Events events={d.key_events} meta={meta} ui={ui} />
      </div>
    </div>
  );
}

function XgRace({ d, meta }: { d: Analysis; meta: Meta }) {
  const W = 520, H = 220, P = 30;
  const maxT = Math.max(5760, d.elapsed), maxY = Math.max(1, ...Object.values(d.xg_flow).flat().map((p) => p[1])) * 1.1;
  const X = (t: number) => P + (t / maxT) * (W - P - 10), Y = (v: number) => H - P - (v / maxY) * (H - P - 10);
  const path = (pts: [number, number][]) => pts.map((p, i) => (i === 0 ? `M${X(p[0])},${Y(p[1])}` : `H${X(p[0])}V${Y(p[1])}`)).join("");
  const goals = d.key_events.filter((e) => e.kind === "goal");
  const at = (team: string, t: number) => { let v = 0; for (const p of d.xg_flow[team] ?? []) if (p[0] <= t) v = p[1]; return v; };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="hub-chart" role="img" aria-label="xG race chart">
      {[0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4].filter((v) => v <= maxY).map((v) => (
        <g key={v}><line x1={P} x2={W - 10} y1={Y(v)} y2={Y(v)} stroke="var(--line, #e5e8ec)" /><text x={P - 6} y={Y(v) + 4} textAnchor="end" fontSize="10" fill="var(--ink-2)">{v}</text></g>
      ))}
      {[0, 2700, maxT].map((t, i) => <text key={t} x={X(t)} y={H - 10} fontSize="10" textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"} fill="var(--ink-2)">{["KO", "HT", "FT"][i]}</text>)}
      <line x1={X(d.elapsed)} x2={X(d.elapsed)} y1={10} y2={H - P} stroke="var(--ink-2)" strokeDasharray="3 3" />
      {[meta.home, meta.away].map((t) => <path key={t.team_id} d={path(d.xg_flow[t.team_id] ?? [])} fill="none" stroke={t.colors[0]} strokeWidth="2.5" />)}
      {goals.map((g, i) => {
        const team = teamOf(meta, g.team_id);
        return <circle key={i} cx={X(g.elapsed)} cy={Y(at(g.team_id, g.elapsed))} r="5" fill={team.colors[0]} stroke="#fff" strokeWidth="1.5"><title>{g.clock} {g.player}</title></circle>;
      })}
    </svg>
  );
}

// ------------------------------------------------------------------ Line-ups
function Lineups({ d, meta, snap, ui }: { d: Analysis; meta: Meta; snap?: Snapshot; ui: Ui }) {
  const onPitch = new Set(d.players.filter((p) => p.on_pitch).map((p) => p.player_id));
  const cards = (pid: string) => d.key_events.filter((e) => (e.kind === "yellow" || e.kind === "red") && e.player_id === pid);
  const scored = (pid: string) => d.key_events.filter((e) => e.kind === "goal" && e.player_id === pid).length;
  // Who's on now: starters still on, plus substitutes, placed in the slot of the man they replaced.
  const shape = (t: Team, home: boolean) => {
    const subs = d.key_events.filter((e) => e.kind === "sub" && e.team_id === t.team_id);
    return lineupSlots(t).map((s) => {
      let pid = s.player_id, name = s.name, number = s.number;
      for (const e of subs) if (e.off_id === pid) {
        const p = d.players.find((x) => x.player_id === e.player_id);
        if (p) { pid = p.player_id; name = p.name; number = p.number; }
      }
      const [bx, by] = s.base;
      const x = home ? bx * 0.5 : 105 - bx * 0.5, y = home ? by : 68 - by;
      return { pid, name, number, x, y, gone: !onPitch.has(pid) };
    });
  };
  return (
    <div className="hub-grid">
      <div className="hub-card hub-wide">
        <h3>{meta.home.short_name} {d.formations[meta.home.team_id]} · {meta.away.short_name} {d.formations[meta.away.team_id]}</h3>
        <Pitch>
          {([[meta.home, true], [meta.away, false]] as [Team, boolean][]).map(([t, home]) => shape(t, home).map((s) => (
            <g key={s.pid} opacity={s.gone ? 0.35 : 1}>
              <circle cx={s.x} cy={s.y} r={2.6} fill={t.colors[0]} stroke={t.colors[1]} strokeWidth={0.5} />
              <text x={s.x} y={s.y + 1} textAnchor="middle" fontSize="2.6" fontWeight="700" fill={t.colors[1]}>{s.number}</text>
              <text x={s.x} y={s.y + 5.6} textAnchor="middle" fontSize="2.3" fill="#fff">{sur(s.name)}{scored(s.pid) ? " ⚽".repeat(scored(s.pid)) : ""}</text>
              {cards(s.pid).map((c, i) => <rect key={i} x={s.x + 2 + i * 1.6} y={s.y - 3.6} width={1.3} height={1.8} fill={c.kind === "red" ? "#D93025" : "#F2C230"} />)}
            </g>
          )))}
        </Pitch>
      </div>
      <div className="hub-card hub-wide"><MatchCentre snap={snap} meta={meta} ui={ui} sheetsOnly /></div>
    </div>
  );
}

// ------------------------------------------------------------------ Players
const COLS: [keyof PlayerRow, string, (p: PlayerRow) => string][] = [
  ["minutes", "Min", (p) => String(p.minutes)], ["touches", "Touches", (p) => String(p.touches)],
  ["passes", "Passes", (p) => `${p.passes_completed}/${p.passes}`], ["pass_completion", "Acc.", (p) => pct(p.pass_completion)],
  ["progressive_passes", "Prog.", (p) => String(p.progressive_passes)], ["key_passes", "Key P.", (p) => String(p.key_passes)],
  ["shots", "Shots", (p) => `${p.shots_on_target}/${p.shots}`], ["xg", "xG", (p) => p.xg.toFixed(2)],
  ["goals", "G", (p) => String(p.goals)], ["assists", "A", (p) => String(p.assists)],
  ["dribbles", "Drib.", (p) => String(p.dribbles)], ["tackles_won", "Tkl", (p) => String(p.tackles_won)],
  ["interceptions", "Int.", (p) => String(p.interceptions)], ["pressures", "Press.", (p) => String(p.pressures)],
  ["fouls", "Fouls", (p) => String(p.fouls)], ["distance_km", "km", (p) => p.distance_km.toFixed(1)],
  ["top_speed_kmh", "Top km/h", (p) => p.top_speed_kmh.toFixed(1)],
];

function Players({ d, meta, ui }: { d: Analysis; meta: Meta; ui: Ui }) {
  const [team, setTeam] = useState<string>("all");
  const [sort, setSort] = useState<keyof PlayerRow>("touches");
  const rows = useMemo(() => d.players.filter((p) => (team === "all" || p.team_id === team) && (p.minutes > 0 || p.touches > 0))
    .sort((a, b) => Number(b[sort] ?? 0) - Number(a[sort] ?? 0)), [d, team, sort]);
  return (
    <div className="hub-card">
      <div className="hub-tools">
        <div className="hub-seg">
          <button className={team === "all" ? "on" : ""} onClick={() => setTeam("all")}>{ui("Both teams")}</button>
          {[meta.home, meta.away].map((t) => <button key={t.team_id} className={team === t.team_id ? "on" : ""} style={{ ["--team" as string]: t.colors[0] }} onClick={() => setTeam(t.team_id)}>{t.short_name}</button>)}
        </div>
        <span className="hub-note">{ui("Click a column to sort.")}</span>
      </div>
      <div className="hub-table-wrap">
        <table className="hub-table">
          <thead><tr><th className="sticky">{ui("Player")}</th>{COLS.map(([k, label]) => <th key={k} className={sort === k ? "sorted" : ""} onClick={() => setSort(k)}>{ui(label)}</th>)}</tr></thead>
          <tbody>
            {rows.map((p) => {
              const t = teamOf(meta, p.team_id);
              return (
                <tr key={p.player_id} className={p.on_pitch ? "" : "off"}>
                  <td className="sticky"><span className="hub-num" style={{ background: t.colors[0], color: t.colors[1] }}>{p.number}</span>{p.name}<small> {p.position}</small>
                    {p.yellow_cards > 0 && <i className="mc-card mc-yellow" />}{p.red_card && <i className="mc-card mc-red" />}</td>
                  {COLS.map(([k, , fmt]) => <td key={k} className={sort === k ? "sorted" : ""}>{fmt(p)}</td>)}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Shots
const OUTCOME: Record<string, [string, string]> = {
  goal: ["#F2C230", "Goal"], saved: ["#4FA3F7", "Saved"], blocked: ["#9AA3AE", "Blocked"], off_target: ["#E8836F", "Off target"],
  post: ["#B07CF5", "Woodwork"],
};

function Shots({ d, meta, ui }: { d: Analysis; meta: Meta; ui: Ui }) {
  return (
    <div className="hub-grid">
      <div className="hub-card hub-wide">
        <h3>{ui("Shot map")} <small className="hub-note">← {meta.away.short_name} · {meta.home.short_name} → · {ui("bigger = better chance")}</small></h3>
        <Pitch>
          {d.shots.map((s, i) => {
            const home = s.team_id === meta.home.team_id;
            const x = home ? s.x : 105 - s.x, y = home ? s.y : 68 - s.y;          // home shoots right, away left
            const [col] = OUTCOME[s.outcome] ?? OUTCOME.off_target;
            return <circle key={i} cx={x} cy={y} r={1 + Math.sqrt(s.xg) * 4} fill={col} fillOpacity={0.85}
                           stroke={teamOf(meta, s.team_id).colors[0]} strokeWidth={0.6}><title>{`${s.clock} ${s.player} · xG ${s.xg} · ${s.outcome}`}</title></circle>;
          })}
        </Pitch>
        <div className="hub-legend">{Object.entries(OUTCOME).map(([k, [c, l]]) => <span key={k}><i style={{ background: c }} />{ui(l)}</span>)}</div>
      </div>
      <div className="hub-card hub-wide">
        <div className="hub-table-wrap">
          <table className="hub-table">
            <thead><tr><th>{ui("Min")}</th><th className="sticky">{ui("Player")}</th><th>xG</th><th>{ui("Outcome")}</th><th>{ui("Body part")}</th><th>{ui("Situation")}</th><th>km/h</th></tr></thead>
            <tbody>{[...d.shots].reverse().map((s, i) => (
              <tr key={i}><td>{s.clock}</td><td className="sticky">{s.player} <small>{teamOf(meta, s.team_id).short_name}</small></td><td>{s.xg.toFixed(2)}</td>
                <td><i className="dot" style={{ background: (OUTCOME[s.outcome] ?? OUTCOME.off_target)[0] }} />{ui((OUTCOME[s.outcome] ?? [, s.outcome])[1])}</td>
                <td>{s.body_part}</td><td>{s.situation?.replace("_", " ")}</td><td>{s.speed_kmh ? Math.round(s.speed_kmh) : "–"}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Passing
function Passing({ d, meta, ui }: { d: Analysis; meta: Meta; ui: Ui }) {
  const [team, setTeam] = useState(meta.home.team_id);
  const net = d.pass_networks[team] ?? { nodes: [], edges: [] };
  const t = teamOf(meta, team);
  // Laid out on the formation (a substitute takes the slot of the man he replaced); line weight is
  // the real number of passes between each pair.
  const slots = new Map(lineupSlots(t).map((s) => [s.player_id, s.base]));
  for (const e of d.key_events) if (e.kind === "sub" && e.team_id === team && e.off_id && slots.has(e.off_id)) slots.set(e.player_id, slots.get(e.off_id)!);
  const nodes = net.nodes.filter((n) => slots.has(n.player_id)).map((n) => {
    const [bx, by] = slots.get(n.player_id)!;
    return { ...n, x: 6 + bx * 0.95, y: by };
  });
  const pos = new Map(nodes.map((n) => [n.player_id, n]));
  const maxE = Math.max(1, ...net.edges.map((e) => e.count)), maxN = Math.max(1, ...nodes.map((n) => n.passes));
  return (
    <div className="hub-card">
      <div className="hub-tools"><TeamSwitch meta={meta} value={team} onChange={setTeam} />
        <span className="hub-note">{ui("Passing links on the team's shape: thicker lines = more passes between the pair, bigger circles = more passes played. Attacking left to right.")}</span></div>
      <Pitch>
        {net.edges.map((e, i) => {
          const a = pos.get(e.a), b = pos.get(e.b);
          return a && b ? <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#fff" strokeOpacity={0.25 + 0.6 * (e.count / maxE)}
                                strokeWidth={0.3 + 1.6 * (e.count / maxE)} strokeLinecap="round"><title>{`${e.count} passes`}</title></line> : null;
        })}
        {nodes.map((n) => (
          <g key={n.player_id}>
            <circle cx={n.x} cy={n.y} r={1.6 + 2.2 * Math.sqrt(n.passes / maxN)} fill={t.colors[0]} stroke={t.colors[1]} strokeWidth={0.5} />
            <text x={n.x} y={n.y + 0.9} textAnchor="middle" fontSize="2.4" fontWeight="700" fill={t.colors[1]}>{n.number}</text>
            <text x={n.x} y={n.y + 5.4} textAnchor="middle" fontSize="2.1" fill="#fff">{sur(n.name)}</text>
          </g>
        ))}
      </Pitch>
    </div>
  );
}

// ------------------------------------------------------------------ Heatmaps
function Heatmaps({ d, meta, ui }: { d: Analysis; meta: Meta; ui: Ui }) {
  const [team, setTeam] = useState(meta.home.team_id);
  const [player, setPlayer] = useState<string>("team");
  const squad = d.players.filter((p) => p.team_id === team && p.touches > 0).sort((a, b) => b.touches - a.touches);
  const grid = useMemo(() => {
    const g = new Map<string, number>();
    for (const p of player === "team" ? squad : squad.filter((s) => s.player_id === player))
      for (const [i, j, n] of d.heatmaps[p.player_id] ?? []) g.set(`${i},${j}`, (g.get(`${i},${j}`) ?? 0) + n);
    return g;
  }, [d, team, player]); // eslint-disable-line react-hooks/exhaustive-deps
  const max = Math.max(1, ...grid.values());
  return (
    <div className="hub-card">
      <div className="hub-tools">
        <TeamSwitch meta={meta} value={team} onChange={(v) => { setTeam(v); setPlayer("team"); }} />
        <select className="hub-select" value={player} onChange={(e) => setPlayer(e.target.value)}>
          <option value="team">{ui("Whole team")}</option>
          {squad.map((p) => <option key={p.player_id} value={p.player_id}>{p.number} · {p.name} ({p.touches})</option>)}
        </select>
        <span className="hub-note">{ui("Where they had the ball. Attacking left to right.")}</span>
      </div>
      <Pitch>
        <defs><filter id="heat-blur" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="2.2" /></filter></defs>
        <g filter="url(#heat-blur)">
          {[...grid].map(([k, n]) => {
            const [i, j] = k.split(",").map(Number);
            const v = n / max;
            const floor = player === "team" ? 0.22 : 0;    // a whole team: only where they really had it
            if (v < floor) return null;
            const w = Math.sqrt((v - floor) / (1 - floor));
            return <rect key={k} x={i * 5} y={j * 5} width={5} height={5} fill={heatColor(w)} fillOpacity={0.4 + 0.55 * w} />;
          })}
        </g>
      </Pitch>
    </div>
  );
}

/** Yellow (a little) to deep red (a lot). */
function heatColor(v: number) {
  const stops = [[255, 236, 140], [255, 170, 60], [232, 67, 46], [160, 20, 40]];
  const x = Math.min(0.999, Math.max(0, v)) * (stops.length - 1), i = Math.floor(x), f = x - i;
  const c = stops[i].map((a, k) => Math.round(a + (stops[i + 1][k] - a) * f));
  return `rgb(${c.join(",")})`;
}

// ------------------------------------------------------------------ Physical
function Physical({ d, meta, ui }: { d: Analysis; meta: Meta; ui: Ui }) {
  return (
    <div className="hub-grid">
      {[meta.home, meta.away].map((t) => {
        const rows = d.players.filter((p) => p.team_id === t.team_id && p.distance_km > 0).sort((a, b) => b.distance_km - a.distance_km);
        const max = Math.max(1, ...rows.map((r) => r.distance_km));
        return (
          <div key={t.team_id} className="hub-card">
            <h3 style={{ borderBottom: `3px solid ${t.colors[0]}`, paddingBottom: 6 }}>{t.name}</h3>
            <div className="phys">
              {rows.map((p) => (
                <div key={p.player_id} className="phys-row">
                  <span className="phys-name">{p.number} · {sur(p.name)}</span>
                  <span className="phys-bar"><i style={{ width: `${(p.distance_km / max) * 100}%`, background: t.colors[0] }} /></span>
                  <span className="phys-v">{p.distance_km.toFixed(1)} km</span>
                  <span className="phys-v phys-speed">{p.top_speed_kmh.toFixed(1)} km/h</span>
                </div>
              ))}
            </div>
            <p className="hub-note">{ui("Distance covered and top speed, from the tracking snapshots.")}</p>
          </div>
        );
      })}
    </div>
  );
}
