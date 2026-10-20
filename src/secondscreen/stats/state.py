"""Running team and player statistics."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlayerStats:
    player_id: str
    name: str
    team_id: str
    position: str
    number: int
    on_pitch: bool = True
    touches: int = 0
    passes: int = 0
    passes_completed: int = 0
    progressive_passes: int = 0
    key_passes: int = 0
    elite_passes: int = 0
    shots: int = 0
    shots_on_target: int = 0
    xg: float = 0.0
    goals: int = 0
    assists: int = 0
    dribbles: int = 0
    tackles_won: int = 0
    interceptions: int = 0
    pressures: int = 0
    fouls: int = 0
    yellow_cards: int = 0
    red_card: bool = False
    distance_m: float = 0.0
    top_speed_kmh: float = 0.0
    max_shot_speed_kmh: float = 0.0

    @property
    def pass_completion(self) -> float | None:
        return round(self.passes_completed / self.passes, 3) if self.passes else None

    def to_dict(self) -> dict:
        d = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in self.__dict__.items()}
        d["pass_completion"] = self.pass_completion
        return d


@dataclass
class TeamStats:
    team_id: str
    name: str
    goals: int = 0
    xg: float = 0.0
    shots: int = 0
    shots_on_target: int = 0
    big_chances: int = 0
    passes: int = 0
    passes_completed: int = 0
    progressive_passes: int = 0
    final_third_passes: int = 0
    box_entries: int = 0
    pass_difficulty_sum: float = 0.0
    pressures: int = 0
    tackles_won: int = 0
    interceptions: int = 0
    high_turnovers: int = 0
    fouls: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    corners: int = 0
    possession_seconds: float = 0.0
    # PPDA: opponent passes in their own 60% / our defensive actions in that zone
    ppda_opp_passes: int = 0
    ppda_def_actions: int = 0
    players_on_pitch: int = 11
    players: dict[str, PlayerStats] = field(default_factory=dict)

    @property
    def pass_completion(self) -> float | None:
        return round(self.passes_completed / self.passes, 3) if self.passes else None

    @property
    def ppda(self) -> float | None:
        return round(self.ppda_opp_passes / self.ppda_def_actions, 2) if self.ppda_def_actions else None

    def to_dict(self, possession_pct: float, field_tilt: float) -> dict:
        return {
            "team_id": self.team_id,
            "name": self.name,
            "goals": self.goals,
            "xg": round(self.xg, 2),
            "shots": self.shots,
            "shots_on_target": self.shots_on_target,
            "big_chances": self.big_chances,
            "possession_pct": possession_pct,
            "field_tilt_pct": field_tilt,
            "passes": self.passes,
            "pass_completion": self.pass_completion,
            "progressive_passes": self.progressive_passes,
            "box_entries": self.box_entries,
            "avg_pass_difficulty": round(self.pass_difficulty_sum / self.passes, 2) if self.passes else None,
            "pressures": self.pressures,
            "tackles_won": self.tackles_won,
            "interceptions": self.interceptions,
            "high_turnovers": self.high_turnovers,
            "ppda": self.ppda,
            "fouls": self.fouls,
            "yellow_cards": self.yellow_cards,
            "red_cards": self.red_cards,
            "corners": self.corners,
            "players_on_pitch": self.players_on_pitch,
        }
