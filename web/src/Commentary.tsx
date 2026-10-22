import { useEffect, useRef, type MutableRefObject } from "react";
import { matchTime, type ClockRef } from "./stream";
import type { Call, CommentaryLine, MatchEvent, Moment, Persona } from "./types";

const SPOKEN = new Set(["goal", "red_card", "penalty_awarded", "big_save", "big_chance_missed", "late_surge",
                        "hot_streak", "fatigue_fade", "pressing_spell"]);

const BIG = new Set(["goal", "red_card", "penalty_awarded"]);

export type Seg = { text: string; lang: string; role: "commentator" | "pundit"; tone: "build" | "peak" | "after" | "calm"; gap: number };

/** The commentary script for a moment in this viewer's language: build, peak, after, pundit. */
export function segments(m: { commentary?: Record<string, CommentaryLine>; headline?: string } & Partial<Moment>,
                         persona: Persona): Seg[] {
  const c = m.commentary?.[persona.lang] ?? m.commentary?.en;
  if (!c) {
    const r = m.renderings?.find((x) => x.persona_id === persona.id) ?? m.renderings?.[0];
    if (r) return [{ text: r.lower_third, lang: r.lang, role: "commentator", tone: "after", gap: 0 }];
    return m.headline ? [{ text: m.headline, lang: "en", role: "commentator", tone: "after", gap: 0 }] : [];
  }
  const out: Seg[] = [];
  if (c.build) out.push({ text: c.build, lang: c.lang, role: "commentator", tone: "build", gap: 0 });
  if (c.peak) out.push({ text: c.peak, lang: c.lang, role: "commentator", tone: "peak", gap: 60 });
  if (c.after) out.push({ text: c.after, lang: c.lang, role: "commentator", tone: "after", gap: 120 });
  if (c.pundit) out.push({ text: c.pundit, lang: c.lang, role: "pundit", tone: "calm", gap: 650 });
  return out;
}

const url = (s: Seg) =>
  `/api/speak?lang=${encodeURIComponent(s.lang)}&role=${s.role}&tone=${s.tone}&text=${encodeURIComponent(s.text)}`;

/**
 * The commentary box: plays a moment's segments back to back, two voices, with natural
 * gaps. One moment at a time; a goal or red card cuts in.
 */
export class Booth {
  private audios: HTMLAudioElement[] = [];
  private pending: Seg[] = [];
  private queue: Seg[][] = [];
  private timer = 0;
  private token = 0;
  busy = false;
  onLine: (s: Seg | null) => void = () => {};

  /** Preload a script; resolves with the build segment's length in seconds (0 if none). */
  prepare(segs: Seg[]): Promise<number> {
    this.halt();
    this.audios = segs.map((s) => { const a = new Audio(url(s)); a.preload = "auto"; return a; });
    this.pending = segs;
    const build = segs[0]?.tone === "build" ? this.audios[0] : null;
    if (!build) return Promise.resolve(0);
    return new Promise((res) => {
      const done = () => res(Number.isFinite(build.duration) ? build.duration : 2);
      build.addEventListener("loadedmetadata", done, { once: true });
      build.addEventListener("error", () => res(0), { once: true });
      setTimeout(() => res(2), 2500);
    });
  }

  /** Play what was prepared, or a new script (cutting in on whatever is playing). */
  play(segs?: Seg[]) {
    if (segs) { this.halt(); this.audios = segs.map((s) => new Audio(url(s))); this.pending = segs; }
    const my = ++this.token, list = this.pending, audios = this.audios;
    this.busy = true;
    const step = (k: number) => {
      if (my !== this.token) return;
      if (k >= audios.length) {
        this.busy = false; this.onLine(null);
        const next = this.queue.shift();
        if (next) this.timer = window.setTimeout(() => this.play(next), 500);
        return;
      }
      this.timer = window.setTimeout(() => {
        if (my !== this.token) return;
        const a = audios[k];
        this.onLine(list[k]);
        a.onended = () => step(k + 1);
        a.onerror = () => step(k + 1);
        a.play().catch(() => step(k + 1));
      }, k === 0 ? 0 : list[k].gap);
    };
    step(0);
  }

  /** Play after whatever is on now (the pundit waits for the call to finish). */
  enqueue(segs: Seg[]) {
    if (!segs.length) return;
    if (this.busy) this.queue.push(segs); else this.play(segs);
  }

  private halt() {
    this.token++;
    clearTimeout(this.timer);
    this.audios.forEach((a) => { a.onended = a.onerror = null; a.pause(); });
    this.busy = false;
    this.onLine(null);
  }

  stop() { this.queue = []; this.halt(); }
}

/**
 * Live commentary. Calls from the spotter arrive a few seconds before the action reaches the
 * screen; the build-up is timed so the call lands as it happens. When the agents' moment for the
 * same signal arrives, only the co-commentator speaks. Other big moments (pressing, a late surge)
 * are read out in full as they arrive. Suppressed while the highlights reel drives the booth.
 */
export function useCommentary(on: boolean, suppress: boolean, moments: Moment[], calls: Call[], persona: Persona,
                              booth: Booth, clockRef: MutableRefObject<ClockRef>) {
  const seen = useRef<Set<string>>(new Set());
  const seenCalls = useRef<Set<string>>(new Set());
  const called = useRef<Set<string>>(new Set());
  const pending = useRef<{ c: Call; build: number; started: boolean } | null>(null);

  useEffect(() => {
    seen.current = new Set(moments.map((m) => m.moment_id));
    seenCalls.current = new Set(calls.map((c) => c.signal_id));
    pending.current = null;
    if (!on) booth.stop();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [on, persona.id, suppress]);

  // New calls: preload, and let the clock decide when to start.
  useEffect(() => {
    const fresh = calls.filter((c) => !seenCalls.current.has(c.signal_id));
    fresh.forEach((c) => seenCalls.current.add(c.signal_id));
    if (!on || suppress) return;
    for (const c of fresh) {
      const cur = pending.current;
      if (cur && !cur.started && !BIG.has(c.kind) && BIG.has(cur.c.kind)) continue;   // don't bump a goal
      const p = { c, build: -1, started: false };
      pending.current = p;
      booth.prepare(segments(c, persona)).then((d) => { p.build = d; });
    }
  }, [on, suppress, calls, persona, booth]);

  useEffect(() => {
    if (!on || suppress) return;
    const id = setInterval(() => {
      const p = pending.current;
      if (!p || p.started) return;
      const t = matchTime(clockRef.current), speed = clockRef.current.speed || 1;
      if ((p.build >= 0 && t >= p.c.at - p.build * speed - 0.3) || t >= p.c.at) {
        p.started = true;
        called.current.add(p.c.signal_id);
        booth.play();
      }
      if (t > p.c.at + 30) pending.current = null;     // stale (a seek, say)
    }, 100);
    return () => clearInterval(id);
  }, [on, suppress, booth, clockRef]);

  // Agent moments: the pundit follows a call; other big moments are read in full.
  useEffect(() => {
    const fresh = moments.filter((m) => !seen.current.has(m.moment_id));
    fresh.forEach((m) => seen.current.add(m.moment_id));
    if (!on || suppress) return;
    for (const m of fresh.filter((x) => SPOKEN.has(x.kind)).sort((a, b) => a.elapsed - b.elapsed)) {
      if (called.current.has(m.signal_id) || pending.current?.c.signal_id === m.signal_id) {
        booth.enqueue(segments(m, persona).filter((s) => s.role === "pundit"));
      } else if (!booth.busy || BIG.has(m.kind)) {
        booth.play(segments(m, persona));
      }
    }
  }, [on, suppress, moments, persona, booth]);

  useEffect(() => () => booth.stop(), [booth]);
}

/**
 * A stadium crowd made in the browser (filtered noise, no recordings): a murmur that
 * rises with attacks, swells on shots and roars on goals.
 */
export class Crowd {
  private ctx: AudioContext | null = null;
  private gain!: GainNode;
  private tone!: BiquadFilterNode;
  private base = 0.05;

  start() {
    if (this.ctx) return;
    const ctx = new AudioContext();
    const len = ctx.sampleRate * 4, buf = ctx.createBuffer(2, len, ctx.sampleRate);
    for (let ch = 0; ch < 2; ch++) {           // pink-ish noise, a different take per channel
      const d = buf.getChannelData(ch);
      let b0 = 0, b1 = 0, b2 = 0;
      for (let i = 0; i < len; i++) {
        const w = Math.random() * 2 - 1;
        b0 = 0.997 * b0 + w * 0.029591; b1 = 0.985 * b1 + w * 0.032534; b2 = 0.95 * b2 + w * 0.048056;
        d[i] = (b0 + b1 + b2 + w * 0.05) * 0.9;
      }
    }
    const src = ctx.createBufferSource(); src.buffer = buf; src.loop = true;
    this.tone = ctx.createBiquadFilter(); this.tone.type = "bandpass"; this.tone.frequency.value = 650; this.tone.Q.value = 0.7;
    const lfo = ctx.createOscillator(), lfoGain = ctx.createGain();      // the murmur breathes
    lfo.frequency.value = 0.18; lfoGain.gain.value = 0.015; lfo.connect(lfoGain);
    this.gain = ctx.createGain(); this.gain.gain.value = 0;
    lfoGain.connect(this.gain.gain);
    src.connect(this.tone).connect(this.gain).connect(ctx.destination);
    src.start(); lfo.start();
    this.gain.gain.setTargetAtTime(this.base, ctx.currentTime, 1.2);
    this.ctx = ctx;
  }

  private swell(level: number, freq: number, attack: number, hold: number, release: number) {
    if (!this.ctx) return;
    const t = this.ctx.currentTime, g = this.gain.gain, f = this.tone.frequency;
    g.cancelScheduledValues(t); f.cancelScheduledValues(t);
    g.setTargetAtTime(level, t, attack); f.setTargetAtTime(freq, t, attack);
    g.setTargetAtTime(this.base, t + attack * 3 + hold, release); f.setTargetAtTime(650, t + attack * 3 + hold, release);
  }

  react(e: MatchEvent) {
    if (e.type === "goal") this.swell(0.42, 1500, 0.12, 2.6, 2.2);
    else if (e.type === "shot") this.swell(0.16, 1050, 0.08, 0.5, 0.9);
    else if (e.type === "save" || e.type === "block") this.swell(0.2, 900, 0.05, 0.4, 0.8);   // the "ooh"
    else if (e.type === "card" && e.card !== "yellow") this.swell(0.22, 500, 0.1, 1.2, 1.5); // the boos
    else if (e.type === "corner") this.swell(0.1, 900, 0.3, 0.8, 1.2);
  }

  duck(on: boolean) {      // drop the crowd a little while the commentators talk
    if (!this.ctx) return;
    this.base = on ? 0.035 : 0.05;
  }

  stop() { this.ctx?.close(); this.ctx = null; }
}

export function useCrowd(on: boolean, events: MatchEvent[], crowd: Crowd) {
  const last = useRef(0);
  useEffect(() => { if (on) crowd.start(); else crowd.stop(); last.current = events.length; },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [on, crowd]);
  useEffect(() => {
    if (!on) return;
    if (events.length < last.current) last.current = 0;          // a seek reset the feed
    for (const e of events.slice(last.current)) crowd.react(e);
    last.current = events.length;
  }, [on, events, crowd]);
  useEffect(() => () => crowd.stop(), [crowd]);
}
