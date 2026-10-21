import { useMemo, useState } from "react";
import { checkLabel, cueKind, kindLabel, PERSONAS, usefulChips } from "./personas";
import { useTranslate, type Lang, type Tr } from "./translate";
import type { Cue, Meta, Moment, Persona } from "./types";

interface Props {
  persona: Persona; onPersona: (id: string) => void; moments: Moment[]; cues: Cue[]; meta: Meta;
  score: Record<string, number>; clock: string; onExplain: (m: Moment) => void; langs: Lang[];
}

type Item = { kind: "moment"; at: number; m: Moment } | { kind: "cue"; at: number; c: Cue };
type T = (text: string, src: string) => Tr;
const EMPTY = "Moments appear here as the match unfolds.";

export function Phone({ persona, onPersona, moments, cues, meta, score, clock, onExplain, langs }: Props) {
  const [lang, setLang] = useState<string>("");
  const to = lang || null;
  const items: Item[] = [
    ...moments.map((m) => ({ kind: "moment" as const, at: m.elapsed, m })),
    ...cues.filter((c) => !c.moment_id && c.persona_id === persona.id).map((c) => ({ kind: "cue" as const, at: c.elapsed, c })),
  ].sort((a, b) => b.at - a.at).slice(0, 40);
  const fav = persona.club === meta.away.team_id ? meta.away : persona.club === meta.home.team_id ? meta.home : null;

  // Everything this phone shows, by source language, so it can be sent to Translator in one go.
  const groups = useMemo(() => {
    if (!to) return {};
    const g: Record<string, string[]> = { en: [EMPTY] };
    const add = (src: string, ...t: string[]) => { (g[src] ??= []).push(...t); };
    for (const it of items) {
      if (it.kind === "moment") {
        const r = rendering(it.m, persona);
        add(r.lang, r.lower_third, r.body, ...usefulChips(r.stat_chips).map((s) => s.label));
        add("en", kindLabel(it.m.kind, "en"), checkLabel(it.m.source, it.m.attempts, "en"));
      } else {
        add("en", kindLabel(it.c.kind ?? cueKind(it.c.type, it.c.text.strap, it.c.stats), "en"));
      }
    }
    return g;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [to, persona.id, items.length, items[0]?.at]);
  const t = useTranslate(to, groups);
  const rtl = !!langs.find((l) => l.code === lang)?.rtl;

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
        {langs.length > 0 && (
          <label className="lang-pick" title="Translated by Azure AI Translator. A translation is only shown if its numbers match the fact-checked original.">
            <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><path d="M2 3h7M5.5 2v1M3.5 3c.6 2.4 2.3 4.3 4.5 5.2M7.5 3C7 5.6 5.2 7.7 2.6 8.6M8.5 14l3-7 3 7M9.6 11.6h3.8" fill="none" stroke="currentColor" strokeWidth="1.3" /></svg>
            <span className="sr-only">Translate this feed</span>
            <select value={lang} onChange={(e) => setLang(e.target.value)}>
              <option value="">Original language</option>
              {langs.filter((l) => l.code !== persona.lang).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
            </select>
          </label>
        )}
      </header>
      <div className="feed" role="feed" aria-busy="false" dir={rtl ? "rtl" : undefined} lang={lang || persona.lang}>
        {items.length === 0 && <p className="feed-empty">{to ? t(EMPTY, "en").text : EMPTY}</p>}
        {items.map((it) => it.kind === "moment" ? (
          <MomentCard key={it.m.moment_id} m={it.m} persona={persona} onExplain={onExplain} t={to ? t : null} />
        ) : (
          <div key={it.c.cue_id} className="tick">
            <span className="tick-clock">{it.c.clock}</span>
            <span className="tick-kind">{label(it.c.kind ?? cueKind(it.c.type, it.c.text.strap, it.c.stats), persona.lang, to ? t : null)}</span>
            <span className="tick-text">{it.c.text.strap}</span>
            {it.c.stats[0] && <b className="tick-val">{it.c.stats[0].value}</b>}
          </div>
        ))}
      </div>
    </section>
  );
}

function rendering(m: Moment, persona: Persona) {
  return m.renderings.find((x) => x.persona_id === persona.id) ?? m.renderings[0];
}

function label(kind: string, lang: string, t: T | null) {
  return t ? t(kindLabel(kind, "en"), "en").text : kindLabel(kind, lang);
}

function MomentCard({ m, persona, onExplain, t }: { m: Moment; persona: Persona; onExplain: (m: Moment) => void; t: T | null }) {
  const r = rendering(m, persona);
  const big = m.kind === "goal" || m.kind === "red_card";
  const tr = (s: string) => (t ? t(s, r.lang) : { text: s, ok: true, pending: false });
  const title = tr(r.lower_third), body = tr(r.body);
  const chips = usefulChips(r.stat_chips);
  const translated = t && !title.pending && !body.pending;
  const kept = translated && (!title.ok || !body.ok);
  const check = t ? t(checkLabel(m.source, m.attempts, "en"), "en").text : checkLabel(m.source, m.attempts, persona.lang);
  return (
    <article className={`card card-${m.kind} ${big ? "card-big" : ""} ${title.pending ? "card-pending" : ""}`}>
      <button className="card-hit" onClick={() => onExplain(m)} aria-label={`Show the evidence for: ${title.text}`}>
        <div className="card-meta">
          <span className="card-clock">{m.clock}</span>
          <span className="card-kind">{label(m.kind, persona.lang, t)}</span>
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
