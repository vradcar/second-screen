import { useEffect, useRef } from "react";
import type { Moment, Persona } from "./types";

const SPOKEN = new Set(["goal", "red_card", "penalty_awarded", "big_save", "big_chance_missed", "late_surge",
                        "hot_streak", "fatigue_fade", "pressing_spell"]);

/**
 * Read out the fact-checked strap for each new big moment with Azure AI Speech
 * (/api/speak). Only moments that arrive while it is on are spoken (no backlog), one
 * at a time; a goal or red card cuts in, smaller moments are dropped if it is busy.
 */
export function useCommentary(on: boolean, moments: Moment[], persona: Persona) {
  const seen = useRef<Set<string>>(new Set());
  const audio = useRef<HTMLAudioElement | null>(null);
  const busy = useRef(false);

  // Turning it on (or a reset) marks everything already shown as heard.
  useEffect(() => { seen.current = new Set(moments.map((m) => m.moment_id)); },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [on, persona.id]);

  useEffect(() => {
    if (!on) { audio.current?.pause(); busy.current = false; return; }
    const fresh = moments.filter((m) => !seen.current.has(m.moment_id));
    fresh.forEach((m) => seen.current.add(m.moment_id));
    const next = fresh.filter((m) => SPOKEN.has(m.kind)).sort((a, b) => b.importance - a.importance)[0];
    if (!next) return;
    const big = next.kind === "goal" || next.kind === "red_card";
    if (busy.current && !big) return;
    const r = next.renderings.find((x) => x.persona_id === persona.id) ?? next.renderings[0];
    audio.current?.pause();
    const a = new Audio(`/api/speak?lang=${encodeURIComponent(r.lang)}&text=${encodeURIComponent(r.lower_third)}`);
    audio.current = a;
    busy.current = true;
    a.onended = a.onerror = () => { if (audio.current === a) busy.current = false; };
    a.play().catch(() => { busy.current = false; });
  }, [on, moments, persona]);

  useEffect(() => () => audio.current?.pause(), []);
}
