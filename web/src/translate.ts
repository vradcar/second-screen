import { useEffect, useMemo, useRef, useState } from "react";

export interface Lang { code: string; name: string; rtl: boolean }
export interface Tr { text: string; ok: boolean; pending: boolean }

// Shared across phones and re-renders: one request per text per language.
const cache = new Map<string, { text: string; ok: boolean }>();
const inflight = new Set<string>();
const key = (src: string, to: string, text: string) => `${src}\u0001${to}\u0001${text}`;

/**
 * Translate a set of strings (grouped by source language) through /api/translate
 * (Azure AI Translator). Returns a lookup that falls back to the original text while a
 * translation is pending, or when the server kept the original (numbers changed, budget).
 */
export function useTranslate(to: string | null, groups: Record<string, string[]>) {
  const [, bump] = useState(0);
  const sig = useMemo(() => JSON.stringify(groups), [groups]);

  useEffect(() => {
    if (!to) return;
    let alive = true;
    const timer = setTimeout(() => {
      for (const [src, texts] of Object.entries(groups)) {
        if (src === to) continue;
        const missing = [...new Set(texts)].filter((t) => t && !cache.has(key(src, to, t)) && !inflight.has(key(src, to, t)));
        for (let i = 0; i < missing.length; i += 40) {
          const batch = missing.slice(i, i + 40);
          batch.forEach((t) => inflight.add(key(src, to, t)));
          fetch("/api/translate", { method: "POST", headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ texts: batch, to, from: src }) })
            .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
            .then((d: { items: { text: string; ok: boolean }[] }) => {
              batch.forEach((t, j) => cache.set(key(src, to, t), d.items[j] ?? { text: t, ok: false }));
            })
            .catch(() => batch.forEach((t) => cache.set(key(src, to, t), { text: t, ok: false })))
            .finally(() => { batch.forEach((t) => inflight.delete(key(src, to, t))); if (alive) bump((n) => n + 1); });
        }
      }
    }, 120);
    return () => { alive = false; clearTimeout(timer); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [to, sig]);

  return (text: string, src: string): Tr => {
    if (!to || src === to || !text) return { text, ok: true, pending: false };
    const hit = cache.get(key(src, to, text));
    return hit ? { ...hit, pending: false } : { text, ok: false, pending: true };
  };
}

/** Translate now (for audio, which can't show a pending state). `ok` is false when the original
 * came back (no translator, budget, or the translation changed a number). */
export async function translateNow(texts: string[], src: string, to: string): Promise<{ text: string; ok: boolean }[]> {
  if (src === to) return texts.map((text) => ({ text, ok: true }));
  const missing = [...new Set(texts)].filter((t) => t && !cache.has(key(src, to, t)));
  for (let i = 0; i < missing.length; i += 40) {
    const batch = missing.slice(i, i + 40);
    try {
      const r = await fetch("/api/translate", { method: "POST", headers: { "Content-Type": "application/json" },
                                                 body: JSON.stringify({ texts: batch, to, from: src }) });
      const d: { items: { text: string; ok: boolean }[] } = await r.json();
      batch.forEach((t, j) => cache.set(key(src, to, t), d.items?.[j] ?? { text: t, ok: false }));
    } catch {
      batch.forEach((t) => cache.set(key(src, to, t), { text: t, ok: false }));
    }
  }
  return texts.map((t) => cache.get(key(src, to, t)) ?? { text: t, ok: false });
}

/** Languages with native commentary and UI labels (no translation needed). */
export const NATIVE: Lang[] = [
  { code: "en", name: "English", rtl: false }, { code: "es", name: "Español", rtl: false },
  { code: "fr", name: "Français", rtl: false },
];

/**
 * Translate whatever is on screen, on demand: returns the cached translation (or the original
 * while it's fetched) and batches anything new into one request a moment later.
 */
export function useLiveTranslate(to: string | null) {
  const [, bump] = useState(0);
  const want = useRef(new Map<string, Set<string>>());
  const timer = useRef(0);
  const flush = async () => {
    timer.current = 0;
    const w = want.current; want.current = new Map();
    if (!to) return;
    await Promise.all([...w].map(([src, set]) => {
      const texts = [...set];
      texts.forEach((t) => inflight.add(key(src, to, t)));
      return translateNow(texts, src, to).finally(() => texts.forEach((t) => inflight.delete(key(src, to, t))));
    }));
    bump((n) => n + 1);
  };
  return (text: string, src: string): Tr => {
    if (!to || !text || src === to) return { text, ok: true, pending: false };
    const hit = cache.get(key(src, to, text));
    if (hit) return { ...hit, pending: false };
    if (!inflight.has(key(src, to, text))) {
      if (!want.current.has(src)) want.current.set(src, new Set());
      want.current.get(src)!.add(text);
      if (!timer.current) timer.current = window.setTimeout(flush, 80);
    }
    return { text, ok: false, pending: true };
  };
}
