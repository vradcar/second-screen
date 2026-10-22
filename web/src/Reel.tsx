import { useEffect, useRef, useState, type MutableRefObject } from "react";
import { localize, PEAK_TAIL, segments, type Booth } from "./Commentary";
import { kindLabel } from "./personas";
import { useLiveTranslate } from "./translate";
import { matchTime, type ClockRef } from "./stream";
import type { Clip, Meta } from "./types";

const REEL_SPEED = 3;

export interface ReelState { playing: boolean; i: number; clips: Clip[]; play: () => void; next: () => void; stop: () => void }

/**
 * Auto-play the match's key moments: seek to just before each one, let it play with
 * its graphics, move on. Recorded mode only (every moment already exists).
 */
export function useReel(meta: Meta | null | undefined, clockRef: MutableRefObject<ClockRef>, speed: number,
                        restart: (p: { at?: number; speed?: number }) => void, auto: boolean,
                        voice: { on: boolean; booth: Booth; lang: string }): ReelState {
  const [i, setI] = useState(-1);
  const saved = useRef(speed);
  const autoDone = useRef(false);
  const clips = meta?.mode === "recorded" ? meta.highlights ?? [] : [];

  // Commentary sync: the build-up is timed so the call lands as the moment happens.
  const cue = useRef({ build: -1, started: false });
  const go = (k: number) => {
    voice.booth.stop();
    if (k >= clips.length) { stop(); return; }
    cue.current = { build: -1, started: false };
    if (voice.on) {
      const q = cue.current;
      localize(segments(clips[k], voice.lang), voice.lang)
        .then((segs) => (cue.current === q ? voice.booth.prepare(segs) : -1))
        .then((d) => { if (cue.current === q && d >= 0) q.build = d; });
    }
    setI(k);
    restart({ at: clips[k].start, speed: REEL_SPEED });
  };
  const play = () => { saved.current = speed; go(0); };
  const stop = () => {
    setI(-1);
    voice.booth.stop();
    restart({ at: Math.floor(matchTime(clockRef.current)), speed: saved.current });
  };

  useEffect(() => {
    if (i < 0 || !clips[i]) return;
    const c = clips[i];
    const id = setInterval(() => {
      const t = matchTime(clockRef.current), q = cue.current;
      if (voice.on && !q.started && t >= c.start && (
          (q.build >= 0 && t >= c.elapsed - Math.max(q.build - PEAK_TAIL, 0) * REEL_SPEED) || t >= c.elapsed)) {
        q.started = true;
        voice.booth.play();
      }
      const talking = voice.on && (!q.started || voice.booth.busy);
      if ((t >= c.end && !talking) || t >= c.end + 40) go(i + 1);
    }, 100);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [i, clips.length]);

  useEffect(() => {
    if (auto && !autoDone.current && clips.length) { autoDone.current = true; play(); }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, clips.length]);

  return { playing: i >= 0, i, clips, play, next: () => go(i + 1), stop };
}

export function Reel({ reel, meta, lang, canTranslate }: { reel: ReelState; meta: Meta; lang: string; canTranslate: boolean }) {
  const tr = useLiveTranslate(canTranslate ? lang : null);
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
      <span className="reel-now"><b>{c.clock}</b> {kindLabel(c.kind, lang)} · {tr(c.headline, "en").text}</span>
      <span className="reel-dots" aria-hidden="true">{reel.clips.map((x, k) => <i key={x.moment_id} className={k < reel.i ? "done" : k === reel.i ? "now" : ""} />)}</span>
      <button className="linkish" onClick={reel.next}>{reel.i + 1 < reel.clips.length ? "Next" : "Finish"}</button>
      <button className="linkish" onClick={reel.stop}>Stop</button>
    </div>
  );
}
