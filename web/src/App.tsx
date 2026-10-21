import { useCallback, useEffect, useState } from "react";
import { Broadcast } from "./Broadcast";
import { Explain } from "./Explain";
import { PERSONAS } from "./personas";
import { Phone } from "./Phone";
import type { Lang } from "./translate";
import { DuelBars, MomentumRiver } from "./Stats";
import { useMatchStream } from "./stream";
import { Timeline } from "./Timeline";
import type { Moment } from "./types";

const SPEEDS = [5, 10, 20, 40];
const STARTS: [number, string][] = [[0, "Kick-off"], [45, "Second half"], [75, "Last 15"]];
const MODES: [string, string][] = [["recorded", "Recorded agents"], ["mock", "Offline model"], ["live", "Live Foundry"], ["onair", "On air"]];

function readParams() {
  const q = new URLSearchParams(location.search);
  return {
    match: q.get("match") ?? "SS00076", mode: q.get("mode") ?? "recorded",
    speed: Number(q.get("speed") ?? 10), start: Number(q.get("start") ?? 0), at: Number(q.get("at") ?? -1), run: 0,
    tv: q.get("tv") ?? "halcyon_fan", left: q.get("left") ?? "studio_analyst", right: q.get("right") ?? "halcyon_fan",
  };
}

export default function App() {
  const init = readParams();
  const [params, setParams] = useState({ match: init.match, mode: init.mode, speed: init.speed, start: init.start, at: init.at, run: 0 });
  const [tv, setTv] = useState(init.tv);
  const [left, setLeft] = useState(init.left);
  const [right, setRight] = useState(init.right);
  const [explain, setExplain] = useState<Moment | null>(null);
  const [paused, setPaused] = useState(false);
  const [liveOk, setLiveOk] = useState(false);
  const [langs, setLangs] = useState<Lang[]>([]);
  const { state, clockRef, send } = useMatchStream(params);

  useEffect(() => { fetch("/api/matches").then((r) => r.json()).then((d) => { setLiveOk(!!d.live_available); setLangs(d.translate?.langs ?? []); }).catch(() => {}); }, []);
  const persona = (id: string) => PERSONAS.find((p) => p.id === id) ?? PERSONAS[0];
  const setSpeed = (v: number) => { setParams((p) => ({ ...p, speed: v })); send({ cmd: "speed", value: v }); };
  const restart = (patch: Partial<typeof params>) => { setPaused(false); setParams((p) => ({ ...p, ...patch, run: p.run + 1 })); };
  const togglePause = () => { send({ cmd: paused ? "play" : "pause" }); setPaused(!paused); };
  const closeExplain = useCallback(() => setExplain(null), []);

  const { meta, snap } = state;
  const onAir = params.mode === "onair";
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const startBroadcast = async () => {
    setStarting(true); setStartError(null);
    try {
      const r = await fetch(`/api/broadcast/start?match=${params.match}&speed=${params.speed}`, { method: "POST" });
      if (!r.ok) throw new Error((await r.json()).detail ?? r.statusText);
      if (state.status === "ended") restart({});
    } catch (e) { setStartError(String((e as Error).message)); }
    finally { setStarting(false); }
  };
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
                      onClick={() => restart({ mode: m, at: m === "recorded" ? params.at : -1 })}>{label}</button>
            ))}
          </div>
          {!onAir && (
            <div className="seg" role="group" aria-label="Start from">
              {STARTS.map(([s, label]) => <button key={s} aria-pressed={params.at < 0 && params.start === s} onClick={() => restart({ start: s, at: -1 })}>{label}</button>)}
            </div>
          )}
          <div className="seg" role="group" aria-label="Speed">
            {SPEEDS.map((s) => <button key={s} aria-pressed={params.speed === s} disabled={onAir && state.status === "live"}
                                       onClick={() => (onAir ? setParams((p) => ({ ...p, speed: s })) : setSpeed(s))}>{s}×</button>)}
          </div>
          {!onAir && <button className="play" onClick={togglePause} aria-label={paused ? "Resume" : "Pause"}>{paused ? "Resume" : "Pause"}</button>}
          {onAir && state.status === "live" && <span className="onair-chip">On air</span>}
        </nav>
      </header>

      {state.status === "error" && <p className="notice">{state.error}</p>}
      {onAir && (state.status === "idle" || (state.status === "ended" && !meta)) && (
        <section className="onair-idle">
          <h2>Nothing is on air</h2>
          <p>Start the broadcast and everyone who opens this page watches the same match, live. Events flow through the
             live feed into one shared pipeline, and moments are saved so late joiners catch up.</p>
          <button className="play" onClick={startBroadcast} disabled={starting}>{starting ? "Starting…" : `Start the broadcast at ${params.speed}×`}</button>
          {startError && <p className="notice">{startError}</p>}
        </section>
      )}
      {!meta && state.status !== "error" && state.status !== "idle" && <p className="notice">Connecting to the match feed…</p>}

      {meta && (
        <main className="stage">
          <div className="tv-col">
            <Broadcast meta={meta} events={state.events} clockRef={clockRef} snap={snap}
                       cues={state.cues} moments={state.moments} persona={persona(tv)} />
            {/* Seeking only makes sense when every moment already exists (a recorded run). */}
            {meta.mode === "recorded" && <Timeline meta={meta} clockRef={clockRef} onSeek={(at) => restart({ at })} />}
            <div className="tv-caption">
              <label>On-air graphics for
                <select value={tv} onChange={(e) => setTv(e.target.value)}>
                  {PERSONAS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                </select>
              </label>
              <span className="pass-key" aria-label="Pass colours">
                <span><i style={{ background: "#3FBF6E" }} />Completed pass</span>
                <span><i style={{ background: "#E0453A" }} />Lost pass</span>
                <span>Click a player to follow him</span>
              </span>
              <span className="pipeline">
                {state.events.length.toLocaleString()} events streamed, {state.moments.length} moments published
                {state.status === "ended" ? ", full time" : ""}
                {onAir && state.status === "ended" && <button className="linkish" onClick={startBroadcast}>Start a new broadcast</button>}
              </span>
            </div>
            <MomentumRiver snap={snap} meta={meta} events={state.events} duration={meta.duration} />
            <DuelBars snap={snap} meta={meta} />
          </div>
          <div className="phones">
            <Phone persona={persona(left)} onPersona={setLeft} moments={state.moments} cues={state.cues} meta={meta}
                   score={score} clock={state.clock} onExplain={setExplain} langs={langs} />
            <Phone persona={persona(right)} onPersona={setRight} moments={state.moments} cues={state.cues} meta={meta}
                   score={score} clock={state.clock} onExplain={setExplain} langs={langs} />
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
