import { useCallback, useRef, useState, type ReactNode } from "react";

/** The tactics board: a pitch drawn in chalk on dark green. Coordinates in metres, 105 x 68. */
export function Board({ children, half, label, className }: { children?: ReactNode; half?: boolean; label: string; className?: string }) {
  const chalk = { fill: "none", stroke: "var(--chalk)", strokeWidth: 0.32 };
  return (
    // The half-pitch view stands the pitch up (goal at the top) so it fits a card without scrolling.
    <svg className={`board ${half ? "board-half" : ""} ${className ?? ""}`} viewBox={half ? "-3 -3 74 57" : "-3 -3 111 74"} role="img" aria-label={label}>
      <g transform={half ? "matrix(0 -1 1 0 0 105)" : undefined}>
      <rect x={-3} y={-3} width={111} height={74} fill="var(--board)" />
      {Array.from({ length: 6 }, (_, i) => <rect key={i} x={i * 17.5} y={0} width={8.75} height={68} fill="var(--board-band)" />)}
      <rect x={0} y={0} width={105} height={68} {...chalk} />
      <line x1={52.5} y1={0} x2={52.5} y2={68} {...chalk} />
      <circle cx={52.5} cy={34} r={9.15} {...chalk} />
      <circle cx={52.5} cy={34} r={0.45} fill="var(--chalk)" />
      {[false, true].map((right) => (
        <g key={String(right)}>
          <rect x={right ? 88.5 : 0} y={13.84} width={16.5} height={40.32} {...chalk} />
          <rect x={right ? 99.5 : 0} y={24.84} width={5.5} height={18.32} {...chalk} />
          <circle cx={right ? 94 : 11} cy={34} r={0.45} fill="var(--chalk)" />
          <path d={right ? "M 88.5 26.7 A 9.15 9.15 0 0 0 88.5 41.3" : "M 16.5 26.7 A 9.15 9.15 0 0 1 16.5 41.3"} {...chalk} />
          <rect x={right ? 105 : -1.6} y={30.34} width={1.6} height={7.32} fill="none" stroke="var(--chalk)" strokeWidth={0.32} />
        </g>
      ))}
      {children}
      </g>
    </svg>
  );
}

export interface TipRow { key?: string; value: string; label: string }
export interface TipState { x: number; y: number; title?: string; rows: TipRow[] }

/** One tooltip per hub: values lead, labels follow, a short line key carries identity. */
export function useTip() {
  const [tip, setTip] = useState<TipState | null>(null);
  const host = useRef<HTMLElement>(null);
  const show = useCallback((e: { clientX: number; clientY: number }, title: string | undefined, rows: TipRow[]) => {
    const r = host.current?.getBoundingClientRect();
    if (!r) return;
    setTip({ x: e.clientX - r.left, y: e.clientY - r.top, title, rows });
  }, []);
  const hide = useCallback(() => setTip(null), []);
  return { tip, show, hide, host };
}

export function Tip({ tip }: { tip: TipState | null }) {
  if (!tip) return null;
  return (
    <div className="tip" style={{ left: tip.x, top: tip.y }} role="status">
      {tip.title && <div className="tip-title">{tip.title}</div>}
      {tip.rows.map((r, i) => (
        <div key={i} className="tip-row">
          {r.key && <i className="tip-key" style={{ background: r.key }} />}
          <b>{r.value}</b><span>{r.label}</span>
        </div>
      ))}
    </div>
  );
}

/** Legend: a swatch (or line key) per series, never colour alone. */
export function Legend({ items, line }: { items: { color: string; label: string }[]; line?: boolean }) {
  return (
    <div className="legend">
      {items.map((it) => <span key={it.label}><i className={line ? "legend-line" : "legend-swatch"} style={{ background: it.color }} />{it.label}</span>)}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }:
  { value: T; options: { value: T; label: string; color?: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}>
          {o.color && <i style={{ background: o.color }} />}{o.label}
        </button>
      ))}
    </div>
  );
}

export function Card({ title, note, children, wide, actions }: { title: string; note?: string; children: ReactNode; wide?: boolean; actions?: ReactNode }) {
  return (
    <section className={`hcard ${wide ? "hcard-wide" : ""}`}>
      <header className="hcard-head">
        <div><h3>{title}</h3>{note && <p>{note}</p>}</div>
        {actions}
      </header>
      {children}
    </section>
  );
}

export const fmt = {
  n: (v: number | null | undefined) => (v == null ? "–" : String(Math.round(v))),
  d1: (v: number | null | undefined) => (v == null ? "–" : v.toFixed(1)),
  d2: (v: number | null | undefined) => (v == null ? "–" : v.toFixed(2)),
  pct: (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v)}%`),
  frac: (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v * 100)}%`),
};
