import { useEffect, useReducer, useRef } from "react";
import type { Cue, MatchEvent, Meta, Moment, RecapDoc, Snapshot } from "./types";

export interface StreamParams { match: string; mode: string; speed: number; start: number; at: number; run: number }

export interface ClockRef { elapsed: number; at: number; speed: number; paused: boolean; clock: string; period: number }

export interface StreamState {
  status: "connecting" | "live" | "ended" | "error" | "idle";
  error?: string;
  meta?: Meta;
  events: MatchEvent[];
  snap?: Snapshot;
  moments: Moment[];
  cues: Cue[];
  recap?: RecapDoc;
  clock: string;
  period: number;
}

type Msg =
  | { t: "reset" }
  | { t: "meta"; m: Meta }
  | { t: "evs"; e: MatchEvent[] }
  | { t: "snap"; s: Snapshot }
  | { t: "moment"; m: Moment }
  | { t: "cue"; c: Cue }
  | { t: "recap"; r: RecapDoc }
  | { t: "clock"; clock: string; period: number }
  | { t: "status"; status: StreamState["status"]; error?: string };

const initial: StreamState = { status: "connecting", events: [], moments: [], cues: [], clock: "00:00", period: 1 };

function reducer(s: StreamState, a: Msg): StreamState {
  switch (a.t) {
    case "reset": return { ...initial, meta: s.meta, snap: s.snap, clock: s.clock, period: s.period };
    case "meta": return { ...s, meta: a.m, status: "live" };
    case "evs": return { ...s, events: s.events.concat(a.e) };
    case "snap": return { ...s, snap: a.s };
    case "moment":
      if (s.moments.some((m) => m.moment_id === a.m.moment_id)) return s;
      return { ...s, moments: [...s.moments, a.m], cues: s.cues.concat(a.m.cues) };
    case "cue": return { ...s, cues: [...s.cues, a.c] };
    case "recap": return { ...s, recap: a.r };
    case "clock": return s.clock === a.clock ? s : { ...s, clock: a.clock, period: a.period };
    case "status": return { ...s, status: a.status, error: a.error };
  }
}

/** Connects to the match server and keeps a smooth match clock in a ref for animation. */
export function useMatchStream(p: StreamParams) {
  const [state, dispatch] = useReducer(reducer, initial);
  const clockRef = useRef<ClockRef>({ elapsed: 0, at: performance.now(), speed: p.speed, paused: false, clock: "00:00", period: 1 });
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    dispatch({ t: "reset" });
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const qs = new URLSearchParams({ match: p.match, mode: p.mode, speed: String(p.speed), start: String(p.start), at: String(p.at) });
    // "On air" joins the one shared broadcast; the other modes get a private replay.
    const url = p.mode === "onair" ? `${proto}://${location.host}/ws/broadcast` : `${proto}://${location.host}/ws?${qs}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;
    clockRef.current = { elapsed: Math.max(p.at, 0), at: performance.now(), speed: p.speed, paused: false, clock: clockRef.current.clock, period: clockRef.current.period };
    let evBuf: MatchEvent[] = [];
    const flush = window.setInterval(() => {
      if (evBuf.length) { dispatch({ t: "evs", e: evBuf }); evBuf = []; }
    }, 250);
    ws.onmessage = (raw) => {
      const msg = JSON.parse(raw.data);
      switch (msg.t) {
        case "meta":
          clockRef.current.elapsed = msg.start_elapsed; clockRef.current.at = performance.now();
          dispatch({ t: "meta", m: msg }); break;
        case "ev": evBuf.push(msg.e); break;
        case "clock":
          clockRef.current.elapsed = msg.elapsed; clockRef.current.at = performance.now();
          clockRef.current.clock = msg.clock; clockRef.current.period = msg.period;
          dispatch({ t: "clock", clock: msg.clock, period: msg.period }); break;
        case "snap": dispatch({ t: "snap", s: msg.s }); break;
        case "moment": dispatch({ t: "moment", m: msg.m }); break;
        case "cue": dispatch({ t: "cue", c: msg.c }); break;
        case "recap": dispatch({ t: "recap", r: msg.r }); break;
        case "state": clockRef.current.speed = msg.speed; clockRef.current.paused = msg.paused; break;
        case "end": dispatch({ t: "status", status: "ended" }); break;
        case "idle": dispatch({ t: "status", status: "idle" }); break;
        case "error": dispatch({ t: "status", status: "error", error: msg.message }); break;
      }
    };
    ws.onerror = () => dispatch({ t: "status", status: "error", error: "Can't reach the match server. Is it running?" });
    return () => { window.clearInterval(flush); ws.close(); };
  }, [p.match, p.mode, p.start, p.at, p.run]); // eslint-disable-line react-hooks/exhaustive-deps

  const send = (cmd: Record<string, unknown>) => wsRef.current?.readyState === 1 && wsRef.current.send(JSON.stringify(cmd));
  return { state, clockRef, send };
}

/** Current match time, extrapolated between server clock ticks. */
export function matchTime(c: ClockRef): number {
  if (c.paused) return c.elapsed;
  const dt = Math.min((performance.now() - c.at) / 1000, 0.5);
  return c.elapsed + dt * c.speed;
}
