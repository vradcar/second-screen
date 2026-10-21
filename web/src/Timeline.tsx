import { useEffect, useRef, useState, type MutableRefObject } from "react";
import { matchTime, type ClockRef } from "./stream";
import type { Meta } from "./types";

/** Elapsed seconds -> match clock text ("37:12", "45+2'"). */
export function clockAt(meta: Meta, elapsed: number): string {
  const ps = meta.periods ?? [];
  const p = [...ps].reverse().find((x) => x.elapsed <= elapsed) ?? ps[0] ?? { period: 1, elapsed: 0, clock_seconds: 0 };
  const secs = p.clock_seconds + (elapsed - p.elapsed);
  const cap = p.period === 1 ? 45 : 90;
  const m = Math.floor(secs / 60), s = Math.floor(secs % 60);
  return m >= cap ? `${cap}+${m - cap + 1}'` : `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

interface Props { meta: Meta; clockRef: MutableRefObject<ClockRef>; onSeek: (elapsed: number) => void }

/**
 * A video-style scrubber for the match. Dragging previews the clock; releasing seeks.
 * Goal and red-card chapters sit on the track; clicking one jumps to just before it.
 */
export function Timeline({ meta, clockRef, onSeek }: Props) {
  const dur = meta.duration;
  const [drag, setDrag] = useState<number | null>(null);
  const [pos, setPos] = useState(meta.start_elapsed);
  const dragRef = useRef<number | null>(null); dragRef.current = drag;

  // Follow the live clock a few times a second without re-rendering the whole app.
  useEffect(() => {
    const id = window.setInterval(() => { if (dragRef.current === null) setPos(Math.min(matchTime(clockRef.current), dur)); }, 250);
    return () => window.clearInterval(id);
  }, [clockRef, dur]);

  const shown = drag ?? pos;
  const pct = (e: number) => `${(e / Math.max(dur, 1)) * 100}%`;
  const half = (meta.periods ?? []).find((p) => p.period === 2)?.elapsed;
  const commit = () => { if (dragRef.current !== null) { onSeek(dragRef.current); setPos(dragRef.current); setDrag(null); } };
  const jump = (delta: number) => onSeek(Math.min(Math.max(pos + delta, 0), dur - 1));

  return (
    <div className="timeline">
      <button className="tl-step" onClick={() => jump(-60)} aria-label="Back one minute">−1′</button>
      <div className="tl-track-wrap">
        <div className="tl-track">
          <span className="tl-fill" style={{ width: pct(shown) }} />
          {half !== undefined && <span className="tl-half" style={{ left: pct(half) }} title="Half-time" />}
          {meta.chapters.map((c) => {
            const team = c.team_id === meta.away.team_id ? meta.away : meta.home;
            return (
              <button key={`${c.kind}-${c.elapsed}`} className={`tl-chapter tl-${c.kind}`} style={{ left: pct(c.elapsed), ["--team" as string]: team.colors[0] }}
                      onClick={() => onSeek(Math.max(c.elapsed - 20, 0))}
                      aria-label={`Jump to ${c.clock}: ${c.kind === "goal" ? "goal" : "red card"}, ${c.label}`}
                      title={`${c.clock} ${c.kind === "goal" ? "Goal" : "Red card"}: ${c.label}`} />
            );
          })}
        </div>
        <input className="tl-range" type="range" min={0} max={Math.floor(dur)} step={5} value={Math.floor(shown)}
               aria-label="Match timeline" aria-valuetext={clockAt(meta, shown)}
               onChange={(e) => setDrag(Number(e.target.value))}
               onPointerUp={commit} onKeyUp={commit} onBlur={commit} />
        {drag !== null && <span className="tl-preview" style={{ left: pct(drag) }}>{clockAt(meta, drag)}</span>}
      </div>
      <button className="tl-step" onClick={() => jump(60)} aria-label="Forward one minute">+1′</button>
      <span className="tl-clock">{clockAt(meta, shown)}</span>
    </div>
  );
}
