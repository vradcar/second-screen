import { useMemo } from "react";
import { checkLabel, cueKind, kindLabel, nativeLabels, PERSONAS, renderFor, usefulChips } from "./personas";
import { useTranslate, type Tr } from "./translate";
import type { Cue, Meta, Moment, Persona } from "./types";

interface Props {
  persona: Persona; onPersona: (id: string) => void; moments: Moment[]; cues: Cue[]; meta: Meta;
  score: Record<string, number>; clock: string; onExplain: (m: Moment) => void;
  lang: string; rtl: boolean; canTranslate: boolean;
}

type Item = { kind: "moment"; at: number; m: Moment } | { kind: "cue"; at: number; c: Cue };
type T = (text: string, src: string) => Tr;
const EMPTY = "Moments appear here as the match unfolds.";

/** One viewer's second screen, in the viewer's chosen language (global, set in the header). */
export function Phone({ persona, onPersona, moments, cues, meta, score, clock, onExplain, lang, rtl, canTranslate }: Props) {
  const items: Item[] = [
    ...moments.map((m) => ({ kind: "moment" as const, at: m.elapsed, m })),
    ...cues.filter((c) => !c.moment_id && c.persona_id === persona.id).map((c) => ({ kind: "cue" as const, at: c.elapsed, c })),
  ].sort((a, b) => b.at - a.at).slice(0, 40);
  const fav = persona.club === meta.away.team_id ? meta.away : persona.club === meta.home.team_id ? meta.home : null;
  const native = nativeLabels(lang);

  // Everything this phone shows that isn't already in the viewer's language, by source language.
  const groups = useMemo(() => {
    if (!canTranslate) return {};
    const g: Record<string, string[]> = {};
    const add = (src: string, ...t: string[]) => { if (src !== lang) (g[src] ??= []).push(...t); };
    if (!native) add("en", EMPTY);
    for (const it of items) {
      if (it.kind === "moment") {
        const { r, src } = renderFor(it.m, persona, lang, canTranslate);
        add(src, r.lower_third, r.body, ...usefulChips(r.stat_chips).map((s) => s.label));
        if (!native) add("en", kindLabel(it.m.kind, "en"), checkLabel(it.m.source, it.m.attempts, "en"));
      } else {
        if (!native) add("en", kindLabel(it.c.kind ?? cueKind(it.c.type, it.c.text.strap, it.c.stats), "en"));
        add(it.c.lang, ...it.c.stats.map((s) => s.label));
      }
    }
    return g;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang, canTranslate, persona.id, items.length, items[0]?.at]);
  const t = useTranslate(canTranslate ? lang : null, groups);
  const label = (kind: string) => (native ? kindLabel(kind, lang) : t(kindLabel(kind, "en"), "en").text);

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
      <div className="feed" role="feed" aria-busy="false" dir={rtl ? "rtl" : undefined} lang={lang}>
        {items.length === 0 && <p className="feed-empty">{native ? EMPTY : t(EMPTY, "en").text}</p>}
        {items.map((it) => it.kind === "moment" ? (
          <MomentCard key={it.m.moment_id} m={it.m} persona={persona} onExplain={onExplain} t={t} lang={lang}
                      canTranslate={canTranslate} label={label} native={native} />
        ) : (
          <div key={it.c.cue_id} className="tick">
            <span className="tick-clock">{it.c.clock}</span>
            <span className="tick-kind">{label(it.c.kind ?? cueKind(it.c.type, it.c.text.strap, it.c.stats))}</span>
            <span className="tick-text">{it.c.text.strap}</span>
            {it.c.stats[0] && <b className="tick-val">{it.c.stats[0].value}</b>}
          </div>
        ))}
      </div>
    </section>
  );
}

function MomentCard({ m, persona, onExplain, t, lang, canTranslate, label, native }: {
  m: Moment; persona: Persona; onExplain: (m: Moment) => void; t: T; lang: string; canTranslate: boolean;
  label: (kind: string) => string; native: boolean;
}) {
  const { r, src } = renderFor(m, persona, lang, canTranslate);
  const big = m.kind === "goal" || m.kind === "red_card";
  const tr = (s: string) => t(s, src);
  const title = tr(r.lower_third), body = tr(r.body);
  const chips = usefulChips(r.stat_chips);
  const translated = src !== lang && canTranslate && !title.pending && !body.pending;
  const kept = translated && (!title.ok || !body.ok);
  const check = native ? checkLabel(m.source, m.attempts, lang) : t(checkLabel(m.source, m.attempts, "en"), "en").text;
  return (
    <article className={`card card-${m.kind} ${big ? "card-big" : ""} ${title.pending ? "card-pending" : ""}`}>
      <button className="card-hit" onClick={() => onExplain(m)} aria-label={`Show the evidence for: ${title.text}`}>
        <div className="card-meta">
          <span className="card-clock">{m.clock}</span>
          <span className="card-kind">{label(m.kind)}</span>
        </div>
        <h3 className="card-title">{title.text}</h3>
        <p className="card-body">{body.text}</p>
        {chips.length > 0 && (
          <div className="chips">{chips.map((s) => <span key={s.label} className="chip"><b>{s.value}</b>{tr(s.label).text}</span>)}</div>
        )}
        <div className={`check check-${m.source === "fallback" ? "safe" : m.attempts > 1 ? "revised" : "ok"}`}>
          <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M3 8.5l3 3 7-7" fill="none" stroke="currentColor" strokeWidth="2.2" /></svg>
          {check}
          {translated && <span className="tr-note">{kept ? " · original shown (translation changed a number)" : " · translated, numbers verified"}</span>}
        </div>
      </button>
    </article>
  );
}
