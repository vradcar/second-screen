"""Deterministic grounding checks. These run before any LLM judge, are free,
and catch the failure modes that matter most on air: invented numbers,
invented people, and claims that cite nothing."""
from __future__ import annotations

import re
from typing import Any, Iterable

from secondscreen.agents.schemas import MomentDraft, Rendering
from secondscreen.simulator.teams import FIRST_NAMES, LAST_NAMES

NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
NAME = re.compile(r"\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\b")
FIRST, LAST = set(FIRST_NAMES), set(LAST_NAMES)


def numbers_in(value: Any) -> set[float]:
    if isinstance(value, bool):
        return set()
    if isinstance(value, (int, float)):
        return {float(value)}
    return {float(n) for n in NUM.findall(str(value))}


def _raw_numbers(value: Any) -> list[tuple[float, bool]]:
    """(number, is_fraction) pairs. Only real fractions (0.71) get percentage variants;
    an integer 1 (a score, a count) must never license "100%"."""
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [(float(value), False)]
    if isinstance(value, float):
        return [(value, 0 < value < 1)]
    return [(float(n), "." in n and 0 < float(n) < 1) for n in NUM.findall(str(value))]


def allowed_numbers(values: Iterable[Any]) -> set[float]:
    """Numbers a sentence may use, given the facts it cites, including the usual
    presentations: 0.71 -> 71%, 2.36 -> 2.4 or 2, 8460 m -> 8.5 km."""
    out: set[float] = set()
    for v in values:
        for n, frac in _raw_numbers(v):
            variants = {n, round(n), round(n, 1), round(n, 2)}
            if frac:
                variants |= {round(n * 100), round(n * 100, 1)}
            if n >= 1000:
                variants |= {round(n / 1000, 1), round(n / 1000, 2), round(n / 1000)}
            out |= variants
    return out


def key_numbers(keys: Iterable[str]) -> set[float]:
    """Numbers embedded in fact key names, e.g. touches_last_12 -> 12."""
    return {float(n) for k in keys for n in re.findall(r"\d+", k)}


def number_ok(n: float, allowed: set[float]) -> bool:
    return any(abs(n - a) <= 0.051 or (a >= 100 and abs(n - a) / a <= 0.005) for a in allowed)


def unknown_names(text: str, roster: set[str]) -> list[str]:
    """Person-like names that aren't in the match roster."""
    bad = []
    for first, last in NAME.findall(text):
        full = f"{first} {last}"
        if full in roster:
            continue
        if first in FIRST or last in LAST:
            bad.append(full)
    return bad


# Numbers that are fine anywhere: small counts written in prose ("two", "1-0" handled via facts).
FREE_NUMBERS = {0.0, 1.0}


def check_draft(draft: MomentDraft, context: dict) -> list[str]:
    facts: dict[str, Any] = context["facts"]
    roster = set(context["roster"])
    issues: list[str] = []
    if len(draft.headline) > 80:
        issues.append(f"Headline is {len(draft.headline)} characters; keep it under 70.")
    if not draft.claims:
        issues.append("No claims were listed. Every factual statement needs a claim with fact keys.")
    cited_all: set[str] = set()
    for i, c in enumerate(draft.claims):
        missing = [k for k in c.facts if k not in facts]
        if missing:
            issues.append(f"Claim {i} cites keys that don't exist: {missing}.")
        known = [k for k in c.facts if k in facts]
        if not known:
            issues.append(f"Claim {i} ('{c.text}') cites no valid facts.")
            continue
        cited_all |= set(known)
        # Window lengths live in key names (touches_last_12), so those numbers are grounded too.
        allowed = allowed_numbers(facts[k] for k in known) | key_numbers(known) | FREE_NUMBERS
        for n in numbers_in(c.text):
            if not number_ok(n, allowed):
                issues.append(f"Claim {i} uses the number {n:g}, which isn't in its cited facts {known}.")
    narrative = " ".join((draft.headline, draft.summary, draft.why_it_matters))
    allowed = allowed_numbers(facts[k] for k in cited_all) | key_numbers(cited_all) | allowed_numbers(
        [facts.get("match.clock"), facts.get("match.minute")]) | FREE_NUMBERS
    for n in numbers_in(narrative):
        if not number_ok(n, allowed):
            issues.append(f"The narrative uses the number {n:g}, which no claim supports.")
    for text in [narrative] + [c.text for c in draft.claims]:
        for name in unknown_names(text, roster):
            issues.append(f"'{name}' is not a player in this match.")
    return sorted(set(issues))


def check_rendering(r: Rendering, approved: MomentDraft, context: dict) -> list[str]:
    """A persona rendering may restyle the moment but not add numbers or people."""
    facts = context["facts"]
    cited = {k for c in approved.claims for k in c.facts if k in facts}
    allowed = allowed_numbers(facts[k] for k in cited) | key_numbers(cited) | allowed_numbers(
        [facts.get("match.clock"), facts.get("match.minute")]) | FREE_NUMBERS
    allowed |= allowed_numbers(facts[k] for k in facts if k.startswith("match.score"))
    issues = []
    if len(r.lower_third) > 70:
        issues.append("lower_third too long")
    text = " ".join([r.lower_third, r.body] + [f"{s.label} {s.value}" for s in r.stat_chips])
    for n in numbers_in(text):
        if not number_ok(n, allowed):
            issues.append(f"number {n:g} not in approved facts")
    for name in unknown_names(text, set(context["roster"])):
        issues.append(f"unknown player '{name}'")
    return issues
