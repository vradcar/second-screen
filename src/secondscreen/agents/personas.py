"""Viewer profiles. The same moment is rendered once per persona."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Persona:
    persona_id: str
    label: str
    mode: str                     # "analyst" | "casual"
    lang: str = "en"
    favourite_club: str | None = None
    focus_player: str | None = None

    def to_prompt(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


DEFAULT_PERSONAS = [
    Persona("studio_analyst", "Studio analyst", "analyst", "en"),
    Persona("halcyon_fan", "Halcyon City fan", "casual", "en", favourite_club="Halcyon City"),
    Persona("redmarsh_fan_es", "Redmarsh fan (Spanish)", "casual", "es", favourite_club="Redmarsh Rovers"),
    Persona("lazaro_cam_fr", "Player cam: Ezra Lazaro (French)", "casual", "fr", focus_player="Ezra Lazaro"),
]
