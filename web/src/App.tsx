import { useCallback, useEffect, useMemo, useState } from "react";
import { Broadcast } from "./Broadcast";
import { Explain } from "./Explain";
import { PERSONAS } from "./personas";
import { Phone } from "./Phone";
import { AnalystHub } from "./AnalystHub";
import { NATIVE, useLiveTranslate, type Lang } from "./translate";
import { isNative, uiText } from "./i18n";
import { Reel, useReel } from "./Reel";
import { Booth, Crowd, useCommentary, useCrowd, type Seg } from "./Commentary";
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
    reel: q.get("reel") === "1", lang: q.get("lang") ?? (() => { try { return localStorage.getItem("ss-lang"); } catch { return null; } })() ?? "en", tv: q.get("tv") ?? "halcyon_fan", left: q.get("left") ?? "studio_analyst", right: q.get("right") ?? "halcyon_fan",
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
  // One language for everything: TV graphics, phones, commentary and the report.
  const [lang, setLangState] = useState<string>(init.lang);
  const setLang = (l: string) => {
    setLangState(l);
    try { localStorage.setItem("ss-lang", l); } catch { /* private mode */ }
    const q = new URLSearchParams(location.search); q.set("lang", l); history.replaceState(null, "", `?${q}`);
  };
  const canTranslate = langs.length > 0;
  const allLangs: Lang[] = [...NATIVE, ...langs.filter((l) => !NATIVE.some((n) => n.code === l.code))];
  const rtl = !!allLangs.find((l) => l.code === lang)?.rtl;
  const tr = useLiveTranslate(canTranslate ? lang : null);
  const ui = (t: string, vars: Record<string, string | number> = {}) =>
    isNative(lang) ? uiText(t, lang, vars) : tr(uiText(t, "en", vars), "en").text;
  const [speechOk, setSpeechOk] = useState(false);
  const [matches, setMatches] = useState<string[]>([]);
  const [voice, setVoice] = useState(true);          // commentary on from kick-off
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const { state, clockRef, send } = useMatchStream(params);

  useEffect(() => { fetch("/api/matches").then((r) => r.json()).then((d) => { setLiveOk(!!d.live_available); setLangs(d.translate?.langs ?? []); setSpeechOk(!!d.speech?.available); setMatches(d.recorded ?? []); }).catch(() => {}); }, []);
  const persona = (id: string) => PERSONAS.find((p) => p.id === id) ?? PERSONAS[0];
  const setSpeed = (v: number) => { setParams((p) => ({ ...p, speed: v })); send({ cmd: "speed", value: v }); };
  const restart = (patch: Partial<typeof params>) => { setPaused(false); setParams((p) => ({ ...p, ...patch, run: p.run + 1 })); };
  const togglePause = () => { send({ cmd: paused ? "play" : "pause" }); setPaused(!paused); };
  const closeExplain = useCallback(() => setExplain(null), []);
  const booth = useMemo(() => new Booth(), []);
  const crowd = useMemo(() => new Crowd(), []);
  const [line, setLine] = useState<Seg | null>(null);
  useEffect(() => {
    booth.onLine = (s) => { setLine(s); crowd.duck(!!s); };
    booth.onBlocked = setAudioBlocked;
    booth.onVoiceError = setVoiceError;
  }, [booth, crowd]);
  const unlockAudio = () => { booth.unlock(); crowd.resume(); };
  // Browsers only allow sound after the viewer interacts: the first click anywhere turns it on.
  useEffect(() => {
    if (!audioBlocked) return;
    const once = () => unlockAudio();
    window.addEventListener("pointerdown", once, { once: true });
    return () => window.removeEventListener("pointerdown", once);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioBlocked]);
  const reel = useReel(state.meta, clockRef, params.speed, restart, init.reel, { on: voice, booth, lang });
  useCommentary(voice, reel.playing, state.moments, state.calls, state.lines, lang, booth, clockRef,
                params.mode === "onair" ? undefined : (h) => send({ cmd: h ? "pause" : "play" }));
  useCrowd(voice, state.events, crowd);

  const { meta, snap } = state;
  const onAir = params.mode === "onair";
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  // ?token=... on the URL unlocks starting broadcasts (and live agents) on a protected deployment.
  const token = new URLSearchParams(location.search).get("token");
  const startBroadcast = async (fresh = false) => {
    setStarting(true); setStartError(null);
    try {
      const q = new URLSearchParams({ speed: String(params.speed) });
      if (fresh) { q.set("seed", "-1"); q.set("agents", "live"); } else q.set("match", params.match);
      if (token) q.set("token", token);
      const r = await fetch(`/api/broadcast/start?${q}`, { method: "POST" });
      if (r.status === 403) throw new Error("This deployment is protected: open the page with ?token=<start token> to start broadcasts.");
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
          <label className="match-pick lang-global" title="Language for everything: TV graphics, phones, commentary and the report">
            <span className="sr-only">Language</span>
            <select value={lang} onChange={(e) => setLang(e.target.value)}>
              {allLangs.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
            </select>
          </label>
          {matches.length > 1 && !onAir && (
            <label className="match-pick">
              <span className="sr-only">Match</span>
              <select value={params.match} onChange={(e) => {
                const q = new URLSearchParams(location.search); q.set("match", e.target.value);
                history.replaceState(null, "", `?${q}`);
                restart({ match: e.target.value, at: -1, start: 0 });
              }}>
                {matches.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </label>
          )}
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
          <div className="onair-actions">
            <button className="play" onClick={() => startBroadcast(true)} disabled={starting}>
              {starting ? "Starting…" : `Kick off a brand-new match at ${params.speed}×`}</button>
            <button className="linkish" onClick={() => startBroadcast(false)} disabled={starting}>or replay {params.match}</button>
          </div>
          <p className="onair-note">A new match is simulated on the spot: every moment, fact-check, translation and line of
             commentary is made live by the agents as it streams. Turn Commentary on to hear the box.</p>
          {startError && <p className="notice">{startError}</p>}
        </section>
      )}
      {!meta && state.status !== "error" && state.status !== "idle" && <p className="notice">Connecting to the match feed…</p>}

      {meta && (
        <main className="stage">
          <div className="tv-col">
            <div className="tv-wrap">
              <Broadcast meta={meta} events={state.events} clockRef={clockRef} snap={snap}
                         cues={state.cues} moments={state.moments} persona={persona(tv)} lang={lang} canTranslate={canTranslate} />
              {voice && audioBlocked && (
                <button className="tap-audio" onClick={unlockAudio}>
                  <svg viewBox="0 0 16 16" width="18" height="18" aria-hidden="true"><path d="M2 6h3l4-3v10l-4-3H2z" fill="currentColor" /><path d="M11 5.5a3.5 3.5 0 010 5M12.8 3.8a6 6 0 010 8.4" fill="none" stroke="currentColor" strokeWidth="1.3" /></svg>
                  {ui("Tap for live commentary")}
                </button>
              )}
            </div>
            {/* Seeking only makes sense when every moment already exists (a recorded run). */}
            {meta.mode === "recorded" && <Reel reel={reel} meta={meta} lang={lang} canTranslate={canTranslate} />}
            {voice && voiceError && <p className="booth-error" role="alert">Voice unavailable: {voiceError} (captions keep running)</p>}
            {voice && (
              <p className={`booth-line ${line ? "booth-live" : ""}`} aria-live="polite">
                <span className="booth-who">{ui(line ? (line.role === "pundit" ? "Co-commentator" : "Commentator") : "Commentary box")}</span>
                <span className={`booth-text ${line?.tone === "call" ? "booth-peak" : ""}`} dir={rtl ? "rtl" : undefined}>{line ? line.text : ui("Listening for the next big moment…")}</span>
              </p>
            )}
            {meta.mode === "recorded" && !reel.playing && <Timeline meta={meta} clockRef={clockRef} onSeek={(at) => restart({ at })} />}
            <div className="tv-caption">
              <label title="Whose version of each moment the TV shows, and the commentary language">On-air graphics and commentary for
                <select value={tv} onChange={(e) => setTv(e.target.value)}>
                  {PERSONAS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                </select>
              </label>
              {speechOk && (
                <button className={`voice ${voice ? "voice-on" : ""}`} aria-pressed={voice} onClick={() => setVoice(!voice)}
                        title="Read out each big moment with Azure AI Speech">
                  <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M2 6h3l4-3v10l-4-3H2z" fill="currentColor" />
                    {voice && <path d="M11 5.5a3.5 3.5 0 010 5M12.8 3.8a6 6 0 010 8.4" fill="none" stroke="currentColor" strokeWidth="1.3" />}</svg>
                  Commentary {voice ? "on" : "off"}
                </button>
              )}
              <span className="pass-key" aria-label="Pass colours">
                <span><i style={{ background: "#3FBF6E" }} />Completed pass</span>
                <span><i style={{ background: "#E0453A" }} />Lost pass</span>
                <span>Click a player to follow him</span>
              </span>
              <span className="pipeline">
                {state.events.length.toLocaleString()} events streamed, {state.moments.length} moments published
                {state.status === "ended" ? ", full time" : ""}
                {onAir && state.status === "ended" && <button className="linkish" onClick={() => startBroadcast(true)}>Kick off another match</button>}
              </span>
            </div>
            <MomentumRiver snap={snap} meta={meta} events={state.events} duration={meta.duration} />
            <DuelBars snap={snap} meta={meta} />
            <AnalystHub meta={meta} snap={snap} clockRef={clockRef} ui={ui} />
          </div>
          <div className="phones">
            <Phone persona={persona(left)} onPersona={setLeft} moments={state.moments} cues={state.cues} meta={meta}
                   score={score} clock={state.clock} onExplain={setExplain} lang={lang} rtl={rtl} canTranslate={canTranslate} />
            <Phone persona={persona(right)} onPersona={setRight} moments={state.moments} cues={state.cues} meta={meta}
                   score={score} clock={state.clock} onExplain={setExplain} lang={lang} rtl={rtl} canTranslate={canTranslate} />
          </div>
          {state.recap && (
            <section className="recap" aria-label={ui("Full-time report")} lang={lang} dir={rtl ? "rtl" : undefined}>
              <h2>{tr(state.recap.recap.title, "en").text}</h2>
              <p className="recap-stand">{tr(state.recap.recap.standfirst, "en").text}</p>
              {state.recap.recap.paragraphs.map((p, i) => <p key={i}>{tr(p.text, "en").text}</p>)}
              <p className="recap-potm"><b>{ui("Player of the match")}: {state.recap.recap.player_of_the_match}.</b> {tr(state.recap.recap.player_of_the_match_reason, "en").text}</p>
            </section>
          )}
        </main>
      )}
      {explain && <Explain m={explain} onClose={closeExplain} />}
    </div>
  );
}
