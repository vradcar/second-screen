import { useEffect, useRef, type MutableRefObject } from "react";
import { matchTime, type ClockRef } from "./stream";
import { translateNow } from "./translate";
import type { Call, CommentaryLine, MatchEvent, Moment, PbpLine } from "./types";

const SPOKEN = new Set(["goal", "red_card", "penalty_awarded", "big_save", "big_chance_missed", "late_surge",
                        "hot_streak", "fatigue_fade", "pressing_spell"]);

const BIG = new Set(["goal", "red_card", "penalty_awarded"]);

export type Seg = { text: string; lang: string; role: "commentator" | "pundit"; tone: "call" | "after" | "calm" | "pbp"; gap: number };

/** The call's last ~second is the shout: line that up with the action. */
export const PEAK_TAIL = 0.9;

/** The commentary script for a moment in the viewer's language: native if it was written in it
 * (en/es/fr), else English (translated by localize() before it is voiced). */
export function segments(m: { commentary?: Record<string, CommentaryLine>; headline?: string } & Partial<Moment>,
                         lang: string): Seg[] {
  const c = m.commentary?.[lang] ?? m.commentary?.en;
  if (!c) {
    const r = m.renderings?.find((x) => x.lang === lang) ?? m.renderings?.[0];
    if (r) return [{ text: r.lower_third, lang: r.lang, role: "commentator", tone: "after", gap: 0 }];
    return m.headline ? [{ text: m.headline, lang: "en", role: "commentator", tone: "after", gap: 0 }] : [];
  }
  // The build-up and the call are one take, so they flow like one breath.
  const out: Seg[] = [];
  const call = [c.build, c.peak].filter(Boolean).join(" ");
  if (call) out.push({ text: call, lang: c.lang, role: "commentator", tone: "call", gap: 0 });
  if (c.after) out.push({ text: c.after, lang: c.lang, role: "commentator", tone: "after", gap: 120 });
  if (c.pundit) out.push({ text: c.pundit, lang: c.lang, role: "pundit", tone: "calm", gap: 650 });
  return out;
}

/** Put a script into the viewer's language (Azure AI Translator, number-checked). A line that
 * can't be translated is spoken in its own language rather than mispronounced. */
export async function localize(segs: Seg[], to: string): Promise<Seg[]> {
  const todo = segs.filter((s) => s.lang !== to);
  if (!todo.length) return segs;
  const out = await translateNow(todo.map((s) => s.text), todo[0].lang, to);
  let k = 0;
  return segs.map((s) => {
    if (s.lang === to) return s;
    const r = out[k++];
    return r.ok ? { ...s, text: r.text, lang: to } : s;
  });
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
  private side: HTMLAudioElement | null = null;   // running play-by-play: never interrupts anything
  busy = false;
  /** The browser refused to play audio until the viewer interacts with the page. */
  blocked = false;
  private retry: Seg[] | null = null;
  onLine: (s: Seg | null) => void = () => {};
  onBlocked: (blocked: boolean) => void = () => {};

  get talking() { return this.busy || this.side !== null; }

  private refused(e: unknown, segs: Seg[]) {
    if ((e as DOMException)?.name !== "NotAllowedError") return false;
    this.retry = segs;
    if (!this.blocked) { this.blocked = true; this.onBlocked(true); }
    return true;
  }

  /** Call from a click: the browser now allows sound. Replays the line that was refused. */
  unlock() {
    const silent = new Audio("data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=");
    silent.play().catch(() => {});
    this.blocked = false;
    this.onBlocked(false);
    const r = this.retry; this.retry = null;
    if (r?.length) this.play(r);
  }

  /** A running line, only if the box is free. */
  say(s: Seg): boolean {
    if (this.talking) return false;
    const a = new Audio(url(s));
    this.side = a;
    this.onLine(s);
    const done = () => { if (this.side === a) { this.side = null; this.onLine(null); } };
    a.onended = done; a.onerror = done;
    a.play().catch((e) => { this.refused(e, [s]); done(); });
    return true;
  }

  private quiet() { if (this.side) { this.side.onended = this.side.onerror = null; this.side.pause(); this.side = null; } }

  /** Preload a script; resolves with the build segment's length in seconds (0 if none). */
  prepare(segs: Seg[]): Promise<number> {
    this.halt();
    this.audios = segs.map((s) => { const a = new Audio(url(s)); a.preload = "auto"; return a; });
    this.pending = segs;
    const build = segs[0]?.tone === "call" ? this.audios[0] : null;
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
    this.quiet();
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
        a.play().catch((e) => {
          if (this.refused(e, list.slice(k))) { this.busy = false; this.onLine(null); this.token++; return; }
          step(k + 1);
        });
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

  stop() { this.queue = []; this.quiet(); this.halt(); }
}

/**
 * Live commentary. Calls from the spotter arrive a few seconds before the action reaches the
 * screen; the build-up is timed so the call lands as it happens. When the agents' moment for the
 * same signal arrives, only the co-commentator speaks. Other big moments (pressing, a late surge)
 * are read out in full as they arrive. Suppressed while the highlights reel drives the booth.
 */
export function useCommentary(on: boolean, suppress: boolean, moments: Moment[], calls: Call[], lines: PbpLine[],
                              lang: string, booth: Booth, clockRef: MutableRefObject<ClockRef>,
                              hold?: (on: boolean) => void) {
  const holding = useRef(false);
  const running = useRef<PbpLine[]>([]);
  const intro = useRef<PbpLine[]>([]);
  const seenLines = useRef<WeakSet<PbpLine>>(new WeakSet());
  const seen = useRef<Set<string>>(new Set());
  const seenCalls = useRef<Set<string>>(new Set());
  const called = useRef<Set<string>>(new Set());
  const pending = useRef<{ c: Call; build: number; started: boolean } | null>(null);

  useEffect(() => {
    seen.current = new Set(moments.map((m) => m.moment_id));
    seenCalls.current = new Set(calls.map((c) => c.signal_id));
    pending.current = null;
    // Turning commentary on mid-stream: keep what's still worth saying (the build-up, the last moment).
    const t = matchTime(clockRef.current), speed = clockRef.current.speed || 1;
    seenLines.current = new WeakSet(lines);
    intro.current = on && t < 1 ? lines.filter((l) => l.kind === "intro") : [];
    running.current = on ? lines.filter((l) => l.kind !== "intro" && l.at >= t - 2.5 * speed).slice(-3) : [];
    if (!on) booth.stop();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [on, lang, suppress]);

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
      localize(segments(c, lang), lang).then((segs) => {
        if (pending.current === p) booth.prepare(segs).then((d) => { p.build = d; });
      });
    }
  }, [on, suppress, calls, lang, booth]);

  // Running play-by-play: queue new lines (the stream keeps only the last 30).
  useEffect(() => {
    const fresh = lines.filter((l) => !seenLines.current.has(l));
    fresh.forEach((l) => seenLines.current.add(l));
    if (!on || suppress) return;
    intro.current = [...intro.current, ...fresh.filter((l) => l.kind === "intro")];
    running.current = [...running.current, ...fresh.filter((l) => l.kind !== "intro")].slice(-8);
    // Lines arrive a few seconds early: translate them now if this language isn't native.
    for (const l of fresh) {
      if (!l.text[lang]) translateNow([l.text.en], "en", lang).then(([r]) => { if (r.ok) l.text[lang] = r.text; });
    }
  }, [on, suppress, lines, lang]);

  useEffect(() => {
    if (!on || suppress) return;
    const id = setInterval(() => {
      const t = matchTime(clockRef.current), speed = clockRef.current.speed || 1;
      if (booth.blocked) return;                       // wait for the viewer's first click
      const voiceOf = (l: PbpLine) => {
        const say = l.text[lang] ? lang : "en";
        return { text: l.text[say], lang: say, role: l.role, tone: (l.role === "pundit" ? "calm" : "pbp") as Seg["tone"], gap: 0 };
      };
      // The pre-match build-up, in order, before anything else. If kick-off comes before the
      // commentators have finished (a private stream), the match waits for them.
      if (intro.current.length || (holding.current && booth.talking)) {
        if (hold && t > 0.5 && !holding.current) { holding.current = true; hold(true); }
        if (intro.current.length && !booth.talking) booth.say(voiceOf(intro.current.shift()!));
        return;
      }
      if (holding.current) { holding.current = false; hold?.(false); }
      // The latest running line that's due, if the box is free and no call is about to start.
      const due = running.current.filter((l) => l.at <= t);
      if (due.length) {
        running.current = running.current.filter((l) => l.at > t);
        const l = due[due.length - 1];
        const callSoon = pending.current && !pending.current.started && pending.current.c.at - t < 3 * speed;
        if (t - l.at <= 2.5 * speed && !booth.talking && !callSoon) {
          booth.say(voiceOf(l));
        }
      }
      const p = pending.current;
      if (!p || p.started) return;
      if ((p.build >= 0 && t >= p.c.at - Math.max(p.build - PEAK_TAIL, 0) * speed) || t >= p.c.at) {
        p.started = true;
        called.current.add(p.c.signal_id);
        booth.play();
      }
      if (t > p.c.at + 30) pending.current = null;     // stale (a seek, say)
    }, 100);
    return () => clearInterval(id);
  }, [on, suppress, booth, clockRef, lang]);

  // Agent moments: the pundit follows a call; other big moments are read in full.
  useEffect(() => {
    const fresh = moments.filter((m) => !seen.current.has(m.moment_id));
    fresh.forEach((m) => seen.current.add(m.moment_id));
    if (!on || suppress) return;
    for (const m of fresh.filter((x) => SPOKEN.has(x.kind)).sort((a, b) => a.elapsed - b.elapsed)) {
      if (called.current.has(m.signal_id) || pending.current?.c.signal_id === m.signal_id) {
        localize(segments(m, lang).filter((s) => s.role === "pundit"), lang).then((segs) => booth.enqueue(segs));
      } else if (!booth.busy || BIG.has(m.kind)) {
        localize(segments(m, lang), lang).then((segs) => booth.play(segs));
      }
    }
  }, [on, suppress, moments, lang, booth]);

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

  resume() { this.ctx?.resume().catch(() => {}); }

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
