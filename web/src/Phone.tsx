import { checkLabel, cueKind, kindLabel, PERSONAS, usefulChips } from "./personas";
import type { Cue, Meta, Moment, Persona } from "./types";

interface Props {
  persona: Persona; onPersona: (id: string) => void; moments: Moment[]; cues: Cue[]; meta: Meta;
  score: Record<string, number>; clock: string; onExplain: (m: Moment) => void;
}

type Item = { kind: "moment"; at: number; m: Moment } | { kind: "cue"; at: number; c: Cue };

export function Phone({ persona, onPersona, moments, cues, meta, score, clock, onExplain }: Props) {
  const items: Item[] = [
    ...moments.map((m) => ({ kind: "moment" as const, at: m.elapsed, m })),
    ...cues.filter((c) => !c.moment_id && c.persona_id === persona.id).map((c) => ({ kind: "cue" as const, at: c.elapsed, c })),
  ].sort((a, b) => b.at - a.at).slice(0, 40);
  const fav = persona.club === meta.away.team_id ? meta.away : persona.club === meta.home.team_id ? meta.home : null;

  return (
    <section className="phone" style={{ ["--accent" as string]: persona.accent }} aria-label={`Second screen: ${persona.label}`}>
      <div className="phone-notch" />
      <header className="phone-head">
        <label className="persona-pick">
          <span className="sr-only">Viewer profile</span>
          <select value={persona.id} onChange={(e) => onPersona(e.target.value)}>
            {PERSONAS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </label>
        <div className="phone-score">
          <span className={fav?.team_id === meta.home.team_id ? "fav" : ""}>{meta.home.short_name} {score[meta.home.team_id] ?? 0}</span>
          <span className="phone-clock">{clock}</span>
          <span className={fav?.team_id === meta.away.team_id ? "fav" : ""}>{score[meta.away.team_id] ?? 0} {meta.away.short_name}</span>
        </div>
      </header>
      <div className="feed" role="feed" aria-busy="false">
        {items.length === 0 && <p className="feed-empty">Moments appear here as the match unfolds.</p>}
        {items.map((it) => it.kind === "moment" ? (
          <MomentCard key={it.m.moment_id} m={it.m} persona={persona} onExplain={onExplain} />
        ) : (
          <div key={it.c.cue_id} className="tick">
            <span className="tick-clock">{it.c.clock}</span>
            <span className="tick-kind">{kindLabel(it.c.kind ?? cueKind(it.c.type, it.c.text.strap, it.c.stats), persona.lang)}</span>
            <span className="tick-text">{it.c.text.strap}</span>
            {it.c.stats[0] && <b className="tick-val">{it.c.stats[0].value}</b>}
          </div>
        ))}
      </div>
    </section>
  );
}

function MomentCard({ m, persona, onExplain }: { m: Moment; persona: Persona; onExplain: (m: Moment) => void }) {
  const r = m.renderings.find((x) => x.persona_id === persona.id) ?? m.renderings[0];
  const big = m.kind === "goal" || m.kind === "red_card";
  return (
    <article className={`card card-${m.kind} ${big ? "card-big" : ""}`}>
      <button className="card-hit" onClick={() => onExplain(m)} aria-label={`Show the evidence for: ${r.lower_third}`}>
        <div className="card-meta">
          <span className="card-clock">{m.clock}</span>
          <span className="card-kind">{kindLabel(m.kind, persona.lang)}</span>
        </div>
        <h3 className="card-title">{r.lower_third}</h3>
        <p className="card-body">{r.body}</p>
        {usefulChips(r.stat_chips).length > 0 && (
          <div className="chips">{usefulChips(r.stat_chips).map((s) => <span key={s.label} className="chip"><b>{s.value}</b>{s.label}</span>)}</div>
        )}
        <div className={`check check-${m.source === "fallback" ? "safe" : m.attempts > 1 ? "revised" : "ok"}`}>
          <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M3 8.5l3 3 7-7" fill="none" stroke="currentColor" strokeWidth="2.2" /></svg>
          {checkLabel(m.source, m.attempts, persona.lang)}
        </div>
      </button>
    </article>
  );
}
