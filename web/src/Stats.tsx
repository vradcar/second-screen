import type { MatchEvent, Meta, Snapshot } from "./types";

/** Momentum over the match as a river: above the line favours the home side, below the away side. */
export function MomentumRiver({ snap, meta, events, duration }: { snap?: Snapshot; meta: Meta; events: MatchEvent[]; duration: number }) {
  const W = 1000, H = 120, mid = H / 2;
  const series = snap?.series ?? [];
  const X = (e: number) => (e / Math.max(duration, 1)) * W;
  const Y = (m: number) => mid - (m / 100) * (mid - 6);
  const pts = series.map((p) => `${X(p.elapsed).toFixed(1)},${Y(p.momentum).toFixed(1)}`);
  const area = pts.length ? `M${X(series[0].elapsed)},${mid} L${pts.join(" L")} L${X(series[series.length - 1].elapsed)},${mid} Z` : "";
  const markers = snap?.markers ?? [];
  const now = series.length ? series[series.length - 1].elapsed : 0;
  // Half-time from the stats series (complete history), not the streamed events (which start mid-match).
  const half = series.find((p) => p.period === 2)?.elapsed ?? events.find((e) => e.period === 2)?.elapsed_seconds ?? duration / 2;
  return (
    <figure className="river">
      <figcaption>
        <span>Momentum</span>
        <span className="legend"><i style={{ background: meta.home.colors[0] }} />{meta.home.short_name}<i style={{ background: meta.away.colors[0] }} />{meta.away.short_name}</span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
           aria-label={`Momentum chart. Currently ${(snap?.momentum ?? 0) > 0 ? meta.home.name : meta.away.name} have the edge.`}>
        <defs>
          <clipPath id="above"><rect x="0" y="0" width={W} height={mid} /></clipPath>
          <clipPath id="below"><rect x="0" y={mid} width={W} height={mid} /></clipPath>
        </defs>
        <line x1={X(half)} x2={X(half)} y1="0" y2={H} className="river-half" />
        <path d={area} fill={meta.home.colors[0]} clipPath="url(#above)" opacity="0.85" />
        <path d={area} fill={meta.away.colors[0]} clipPath="url(#below)" opacity="0.85" />
        <line x1="0" x2={W} y1={mid} y2={mid} className="river-axis" />
        <line x1={X(now)} x2={X(now)} y1="0" y2={H} className="river-now" />
        {markers.map((mk) => {
          const home = mk.team_id === meta.home.team_id;
          const color = home ? meta.home.colors[0] : meta.away.colors[0];
          const y = home ? 10 : H - 10;
          return (
            <g key={`${mk.kind}-${mk.elapsed}`} transform={`translate(${X(mk.elapsed)},${y})`} className="river-marker">
              <title>{`${mk.clock} ${mk.kind === "goal" ? "Goal" : "Red card"}: ${mk.label}`}</title>
              {mk.kind === "goal"
                ? <circle r="7" fill="#fff" stroke={color} strokeWidth="2.5" />
                : <rect x="-4" y="-6" width="8" height="12" rx="1.5" fill="#d1271c" stroke="#fff" strokeWidth="1.5" />}
            </g>
          );
        })}
      </svg>
      <div className="river-scale"><span>Kick-off</span><span style={{ left: `${(half / Math.max(duration, 1)) * 100}%` }}>Half-time</span><span>Full time</span></div>
    </figure>
  );
}

const ROWS: { label: string; get: (t: Snapshot["teams"][string]) => number | null; fmt: (v: number) => string; lowerBetter?: boolean }[] = [
  { label: "Possession", get: (t) => t.possession_pct, fmt: (v) => `${Math.round(v)}%` },
  { label: "Expected goals", get: (t) => t.xg, fmt: (v) => v.toFixed(2) },
  { label: "Shots", get: (t) => t.shots, fmt: (v) => String(v) },
  { label: "Field tilt", get: (t) => t.field_tilt_pct, fmt: (v) => `${Math.round(v)}%` },
  { label: "Pass completion", get: (t) => (t.pass_completion ?? 0) * 100, fmt: (v) => `${Math.round(v)}%` },
  { label: "High turnovers", get: (t) => t.high_turnovers, fmt: (v) => String(v) },
  { label: "Passes per defensive action", get: (t) => t.ppda, fmt: (v) => v.toFixed(1), lowerBetter: true },
];

export function DuelBars({ snap, meta }: { snap?: Snapshot; meta: Meta }) {
  if (!snap) return <div className="duel duel-empty">Stats start with the first touch.</div>;
  const h = snap.teams[meta.home.team_id], a = snap.teams[meta.away.team_id];
  return (
    <div className="duel">
      {ROWS.map((r) => {
        const hv = r.get(h) ?? 0, av = r.get(a) ?? 0;
        const tot = hv + av || 1;
        let hs = hv / tot;
        if (r.lowerBetter) hs = 1 - hs;
        return (
          <div className="duel-row" key={r.label}>
            <b>{r.fmt(hv)}</b>
            <div className="duel-bar">
              <span style={{ width: `${hs * 100}%`, background: meta.home.colors[0] }} />
              <span style={{ width: `${(1 - hs) * 100}%`, background: meta.away.colors[0] }} />
              <em>{r.label}{r.lowerBetter ? " (lower = more pressing)" : ""}</em>
            </div>
            <b>{r.fmt(av)}</b>
          </div>
        );
      })}
    </div>
  );
}
