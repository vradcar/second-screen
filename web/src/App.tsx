import { useCallback, useEffect, useState } from "react";
import { Broadcast } from "./Broadcast";
import { Explain } from "./Explain";
import { PERSONAS } from "./personas";
import { Phone } from "./Phone";
import { DuelBars, MomentumRiver } from "./Stats";
import { useMatchStream } from "./stream";
import type { Moment } from "./types";

const SPEEDS = [5, 10, 20, 40];
const STARTS: [number, string][] = [[0, "Kick-off"], [45, "Second half"], [75, "Last 15"]];
const MODES: [string, string][] = [["recorded", "Recorded agents"], ["mock", "Offline model"], ["live", "Live Foundry"]];

function readParams() {
  const q = new URLSearchParams(location.search);
  return {
    match: q.get("match") ?? "SS00076", mode: q.get("mode") ?? "recorded",
    speed: Number(q.get("speed") ?? 10), start: Number(q.get("start") ?? 0), run: 0,
    tv: q.get("tv") ?? "halcyon_fan", left: q.get("left") ?? "studio_analyst", right: q.get("right") ?? "halcyon_fan",
  };
}

export default function App() {
  const init = readParams();
  const [params, setParams] = useState({ match: init.match, mode: init.mode, speed: init.speed, start: init.start, run: 0 });
  const [tv, setTv] = useState(init.tv);
  const [left, setLeft] = useState(init.left);
  const [right, setRight] = useState(init.right);
  const [explain, setExplain] = useState<Moment | null>(null);
  const [paused, setPaused] = useState(false);
  const [liveOk, setLiveOk] = useState(false);
  const { state, clockRef, send } = useMatchStream(params);

  useEffect(() => { fetch("/api/matches").then((r) => r.json()).then((d) => setLiveOk(!!d.live_available)).catch(() => {}); }, []);
  const persona = (id: string) => PERSONAS.find((p) => p.id === id) ?? PERSONAS[0];
  const setSpeed = (v: number) => { setParams((p) => ({ ...p, speed: v })); send({ cmd: "speed", value: v }); };
  const restart = (patch: Partial<typeof params>) => { setPaused(false); setParams((p) => ({ ...p, ...patch, run: p.run + 1 })); };
  const togglePause = () => { send({ cmd: paused ? "play" : "pause" }); setPaused(!paused); };
  const closeExplain = useCallback(() => setExplain(null), []);

  const { meta, snap } = state;
  const score = snap?.score ?? {};

  return (
    <div className="app">
      <header className="bar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><i /><i /></span>
          <span className="brand-name">Second Screen</span>
        </div>
        {meta && <h1 className="fixture">{meta.home.name} <span>v</span> {meta.away.name}</h1>}
        <nav className="controls" aria-label="Playback">
          <div className="seg" role="group" aria-label="Agent source">
            {MODES.map(([m, label]) => (
              <button key={m} aria-pressed={params.mode === m} disabled={m === "live" && !liveOk}
                      title={m === "live" && !liveOk ? "Add Foundry credentials to .env to enable" : undefined}
                      onClick={() => restart({ mode: m })}>{label}</button>
            ))}
          </div>
          <div className="seg" role="group" aria-label="Start from">
            {STARTS.map(([s, label]) => <button key={s} aria-pressed={params.start === s} onClick={() => restart({ start: s })}>{label}</button>)}
          </div>
          <div className="seg" role="group" aria-label="Speed">
            {SPEEDS.map((s) => <button key={s} aria-pressed={params.speed === s} onClick={() => setSpeed(s)}>{s}×</button>)}
          </div>
          <button className="play" onClick={togglePause} aria-label={paused ? "Resume" : "Pause"}>{paused ? "Resume" : "Pause"}</button>
        </nav>
      </header>

      {state.status === "error" && <p className="notice">{state.error}</p>}
      {!meta && state.status !== "error" && <p className="notice">Connecting to the match feed…</p>}

      {meta && (
        <main className="stage">
          <div className="tv-col">
            <Broadcast meta={meta} events={state.events} clockRef={clockRef} snap={snap}
                       cues={state.cues} moments={state.moments} persona={persona(tv)} />
            <div className="tv-caption">
              <label>On-air graphics for
                <select value={tv} onChange={(e) => setTv(e.target.value)}>
                  {PERSONAS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                </select>
              </label>
              <span className="pipeline">
                {state.events.length.toLocaleString()} events streamed, {state.moments.length} moments published
                {state.status === "ended" ? ", full time" : ""}
              </span>
            </div>
            <MomentumRiver snap={snap} meta={meta} events={state.events} duration={meta.duration} />
            <DuelBars snap={snap} meta={meta} />
          </div>
          <div className="phones">
            <Phone persona={persona(left)} onPersona={setLeft} moments={state.moments} cues={state.cues} meta={meta}
                   score={score} clock={state.clock} onExplain={setExplain} />
            <Phone persona={persona(right)} onPersona={setRight} moments={state.moments} cues={state.cues} meta={meta}
                   score={score} clock={state.clock} onExplain={setExplain} />
          </div>
          {state.recap && (
            <section className="recap" aria-label="Full-time report">
              <h2>{state.recap.recap.title}</h2>
              <p className="recap-stand">{state.recap.recap.standfirst}</p>
              {state.recap.recap.paragraphs.map((p, i) => <p key={i}>{p.text}</p>)}
              <p className="recap-potm"><b>Player of the match: {state.recap.recap.player_of_the_match}.</b> {state.recap.recap.player_of_the_match_reason}</p>
            </section>
          )}
        </main>
      )}
      {explain && <Explain m={explain} onClose={closeExplain} />}
    </div>
  );
}
