import { useEffect, useRef, useState, type MutableRefObject } from "react";
import { kindLabel } from "./personas";
import { matchTime, type ClockRef } from "./stream";
import type { Clip, Meta } from "./types";

const REEL_SPEED = 3;

export interface ReelState { playing: boolean; i: number; clips: Clip[]; play: () => void; next: () => void; stop: () => void }

/**
 * Auto-play the match's key moments: seek to just before each one, let it play with
 * its graphics, move on. Recorded mode only (every moment already exists).
 */
export function useReel(meta: Meta | null | undefined, clockRef: MutableRefObject<ClockRef>, speed: number,
                        restart: (p: { at?: number; speed?: number }) => void, auto: boolean): ReelState {
  const [i, setI] = useState(-1);
  const saved = useRef(speed);
  const autoDone = useRef(false);
  const clips = meta?.mode === "recorded" ? meta.highlights ?? [] : [];

  const go = (k: number) => {
    if (k >= clips.length) { stop(); return; }
    setI(k);
    restart({ at: clips[k].start, speed: REEL_SPEED });
  };
  const play = () => { saved.current = speed; go(0); };
  const stop = () => {
    setI(-1);
    restart({ at: Math.floor(matchTime(clockRef.current)), speed: saved.current });
  };

  useEffect(() => {
    if (i < 0 || !clips[i]) return;
    const id = setInterval(() => { if (matchTime(clockRef.current) >= clips[i].end) go(i + 1); }, 200);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [i, clips.length]);

  useEffect(() => {
    if (auto && !autoDone.current && clips.length) { autoDone.current = true; play(); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, clips.length]);

  return { playing: i >= 0, i, clips, play, next: () => go(i + 1), stop };
}

export function Reel({ reel, meta }: { reel: ReelState; meta: Meta }) {
  if (!reel.clips.length) return null;
  if (!reel.playing) {
    return (
      <div className="reel reel-idle">
        <button className="reel-play" onClick={reel.play}>
          <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M4 2.5v11l9-5.5z" fill="currentColor" /></svg>
          Highlights
        </button>
        <span className="reel-sub">{reel.clips.length} key moments picked from the agents' published moments</span>
      </div>
    );
  }
  const c = reel.clips[reel.i];
  return (
    <div className="reel" role="status" aria-live="polite">
      <span className="reel-tag">Highlights {reel.i + 1}/{reel.clips.length}</span>
      <span className="reel-now"><b>{c.clock}</b> {kindLabel(c.kind, "en")} · {c.headline}</span>
      <span className="reel-dots" aria-hidden="true">{reel.clips.map((x, k) => <i key={x.moment_id} className={k < reel.i ? "done" : k === reel.i ? "now" : ""} />)}</span>
      <button className="linkish" onClick={reel.next}>{reel.i + 1 < reel.clips.length ? "Next" : "Finish"}</button>
      <button className="linkish" onClick={reel.stop}>Stop</button>
    </div>
  );
}
