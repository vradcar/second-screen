"""Deterministic grounding checks. These run before any LLM judge, are free,
and catch the failure modes that matter most on air: invented numbers,
invented people, and claims that cite nothing.

Two levels of strictness:
- Each claim may only use numbers from the facts it cites.
- Headline, summary and persona renderings may use any number in the FACTS table
  (or the already-approved story), because those are restyled presentations;
  the LLM judge checks that they're used in the right sense.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from secondscreen.agents.schemas import MomentDraft, Rendering
from secondscreen.simulator.teams import FIRST_NAMES, LAST_NAMES

NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
NAME = re.compile(r"\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b")
FIRST, LAST = set(FIRST_NAMES), set(LAST_NAMES)
STORY_KEY = "story_so_far"

# Numbers that are fine anywhere: "one", "a 1-0", "zero".
FREE_NUMBERS = {0.0, 1.0}


def _clean(text: str) -> str:
    return THOUSANDS.sub("", str(text))   # 8,460 -> 8460


def numbers_in(value: Any) -> set[float]:
    if isinstance(value, bool):
        return set()
    if isinstance(value, (int, float)):
        return {abs(float(value))}
    return {float(n) for n in NUM.findall(_clean(value))}


def _raw_numbers(value: Any) -> list[tuple[float, bool]]:
    """(number, is_fraction) pairs, sign dropped ("momentum -70" is written as "70").
    Only real fractions (0.71) get percentage variants; an integer 1 (a score, a
    count) must never license "100%"."""
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [(abs(float(value)), False)]
    if isinstance(value, float):
        return [(abs(value), 0 < abs(value) < 1)]
    return [(float(n), "." in n and 0 < float(n) < 1) for n in NUM.findall(_clean(value))]


def allowed_numbers(values: Iterable[Any]) -> set[float]:
    """Numbers a sentence may use, given some fact values, including the usual
    presentations: 0.71 -> 71%, 2.36 -> 2.4 or 2, 8460 m -> 8.5 km, 8.46 km -> 8460 m."""
    out: set[float] = set()
    for v in values:
        for n, frac in _raw_numbers(v):
            variants = {n, round(n), round(n, 1), round(n, 2)}
            if frac:
                variants |= {round(n * 100), round(n * 100, 1)}
            if n >= 1000:
                variants |= {round(n / 1000, 1), round(n / 1000, 2), round(n / 1000)}
            elif n != int(n):
                variants |= {round(n * 1000)}           # km written as metres
            out |= variants
    return out


def key_numbers(keys: Iterable[str]) -> set[float]:
    """Numbers embedded in fact key names, e.g. touches_last_12 -> 12."""
    return {float(n) for k in keys for n in re.findall(r"\d+", k)}


def number_ok(n: float, allowed: set[float]) -> bool:
    return any(abs(n - a) <= 0.051 or (a >= 100 and abs(n - a) / a <= 0.005) for a in allowed)


def unknown_names(text: str, roster: set[str]) -> list[str]:
    """Person-like names that aren't in the match roster. Flags a capitalised pair
    when the first word is a known first name (an invented or mismatched player),
    including a roster first name with the wrong surname. Ordinary capitalised
    words ("Goles Fontaine", "Halcyon City") pass."""
    roster_first = {n.split()[0] for n in roster}
    bad = []
    for first, last in NAME.findall(text):
        full = f"{first} {last}"
        if full in roster:
            continue
        if first in FIRST or first in roster_first:
            bad.append(full)
    return bad


ALIASES = {"signal.clock": "match.clock", "signal.minute": "match.minute", "signal.period": "match.period",
           "match.score": "match.score"}


def resolve_keys(cited: Iterable[str], facts: dict[str, Any], story: list[str] | None = None
                 ) -> tuple[list[str], list[str]]:
    """Cited keys that resolve, and the ones that don't. Accepts exact keys, parents
    (signal.players_on_pitch covers signal.players_on_pitch.HAL), common aliases
    (signal.clock -> match.clock) and story lines quoted verbatim."""
    story = story or []
    known, missing = [], []
    for k in cited:
        k = ALIASES.get(k, k)
        if k in facts:
            known.append(k)
        elif k == STORY_KEY or k in story:
            known.append(STORY_KEY)
        elif children := [f for f in facts if f.startswith(k + ".")]:
            known.extend(children)
        else:
            missing.append(k)
    return known, missing


def _values(keys: Iterable[str], facts: dict, context: dict) -> list[Any]:
    out = []
    for k in keys:
        out.append(" | ".join(context.get("story_so_far", [])) if k == STORY_KEY else facts[k])
    return out


def _time_numbers(facts: dict) -> set[float]:
    """The clock, and the minute both ways: 11:55 is 'the 11th' or 'the 12th minute'."""
    out = allowed_numbers([facts.get("match.clock")])
    m = facts.get("match.minute")
    if isinstance(m, int):
        out |= {float(m), float(m + 1)}
    return out


def _global_allowed(context: dict) -> set[float]:
    facts = context["facts"]
    return (allowed_numbers(facts.values()) | key_numbers(facts) | _time_numbers(facts)
            | allowed_numbers(context.get("story_so_far", [])) | FREE_NUMBERS)


def check_draft(draft: MomentDraft, context: dict) -> list[str]:
    facts: dict[str, Any] = context["facts"]
    roster = set(context["roster"])
    issues: list[str] = []
    if len(draft.headline) > 80:
        issues.append(f"Headline is {len(draft.headline)} characters; keep it under 70.")
    if not draft.claims:
        issues.append("No claims were listed. Every factual statement needs a claim with fact keys.")
    for i, c in enumerate(draft.claims):
        known, missing = resolve_keys(c.facts, facts, context.get("story_so_far"))
        if missing:
            issues.append(f"Claim {i} cites keys that don't exist: {missing}. Use keys exactly as listed in FACTS.")
        if not known:
            issues.append(f"Claim {i} ('{c.text}') cites no valid facts.")
            continue
        # Window lengths live in key names (touches_last_12), so those numbers are grounded too.
        # Timestamps ("at 64:44", "the 65th minute") are never stats, so any claim may use them.
        allowed = (allowed_numbers(_values(known, facts, context)) | key_numbers(known)
                   | _time_numbers(facts) | FREE_NUMBERS)
        for n in numbers_in(c.text):
            if not number_ok(n, allowed):
                issues.append(f"Claim {i} uses the number {n:g}, which isn't in its cited facts {known}. "
                              "Cite the fact that contains it, or remove the number.")
    narrative = " ".join((draft.headline, draft.summary, draft.why_it_matters))
    allowed = _global_allowed(context)
    for n in numbers_in(narrative):
        if not number_ok(n, allowed):
            issues.append(f"The headline/summary uses the number {n:g}, which is not in FACTS.")
    for text in [narrative] + [c.text for c in draft.claims]:
        for name in unknown_names(text, roster):
            issues.append(f"'{name}' is not a player in this match.")
    return sorted(set(issues))


def check_rendering(r: Rendering, approved: MomentDraft, context: dict) -> list[str]:
    """A persona rendering may restyle the moment and draw on FACTS, but never add
    a number or a person that isn't there."""
    allowed = _global_allowed(context)
    issues = []
    if len(r.lower_third) > 70:
        issues.append("lower_third too long")
    text = " ".join([r.lower_third, r.body] + [f"{s.label} {s.value}" for s in r.stat_chips])
    for n in numbers_in(text):
        if not number_ok(n, allowed):
            issues.append(f"number {n:g} not in facts")
    for name in unknown_names(text, set(context["roster"])):
        issues.append(f"unknown player '{name}'")
    return issues
