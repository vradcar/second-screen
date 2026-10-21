import { useEffect, useRef } from "react";
import type { Moment } from "./types";

/** The evidence behind one moment: claims, the facts each cites, and the fact-check trail. */
export function Explain({ m, onClose }: { m: Moment; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  const facts = m.facts ?? {};
  const trail = m.check_log.filter((e) => ["analyst", "fact_check", "fallback", "persona_check", "persona_fallback", "judge"].includes(String(e.step)));

  return (
    <div className="explain-wrap" onClick={onClose}>
      <aside className="explain" role="dialog" aria-modal="true" aria-label="Why this moment is on screen"
             tabIndex={-1} ref={ref} onClick={(e) => e.stopPropagation()}>
        <button className="explain-close" onClick={onClose} aria-label="Close">×</button>
        <p className="explain-when"><span>{m.clock}</span><span>{m.kind.replace(/_/g, " ")}</span></p>
        <h2>{m.draft.headline}</h2>
        <p className="explain-why">{m.draft.why_it_matters}</p>

        <h3>What it claims, and what backs it</h3>
        <ol className="claims">
          {m.draft.claims.map((c, i) => (
            <li key={i}>
              <p>{c.text}</p>
              <div className="facts">
                {c.facts.map((k) => (
                  <code key={k}>{k}{k in facts ? <> = <b>{String(facts[k])}</b></> : null}</code>
                ))}
              </div>
            </li>
          ))}
        </ol>

        <h3>How it got on air</h3>
        <ol className="trail">
          {trail.map((e, i) => <TrailStep key={i} e={e} />)}
          <li className="step step-ok"><span>Published{m.latency_s ? ` in ${m.latency_s.toFixed(1)} s` : ""} for {m.renderings.length} viewer profiles</span></li>
        </ol>

        <h3>Source events</h3>
        <p className="evidence">{m.evidence.map((id) => <code key={id}>{id}</code>)}</p>
      </aside>
    </div>
  );
}

function TrailStep({ e }: { e: Record<string, unknown> }) {
  const step = String(e.step);
  if (step === "analyst") {
    return <li className={`step ${e.error ? "step-bad" : ""}`}><span>Analyst draft {String(e.attempt)}{e.error ? " failed" : `: “${String(e.headline ?? "")}”`}</span></li>;
  }
  if (step === "fact_check") {
    const ok = e.verdict === "approved";
    const issues = (e.issues as string[]) ?? [];
    return (
      <li className={`step ${ok ? "step-ok" : "step-bad"}`}>
        <span>{ok ? "Approved" : "Rejected"} by the {e.stage === "judge" ? "fact-check judge" : "grounding rules"}</span>
        {issues.length > 0 && <ul>{issues.slice(0, 3).map((x, i) => <li key={i}>{x}</li>)}</ul>}
      </li>
    );
  }
  if (step === "fallback") return <li className="step step-bad"><span>Replaced with a fact-safe template</span></li>;
  if (step === "persona_check") return <li className="step step-bad"><span>{String(e.persona)} version rejected: {((e.rejected as string[]) ?? []).slice(0, 2).join("; ")}</span></li>;
  if (step === "persona_fallback") return <li className="step"><span>{String(e.persona)} shown the checked base text</span></li>;
  return null;
}
