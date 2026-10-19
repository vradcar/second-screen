"""Fictional clubs and players. Nothing here represents a real club or person."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

FORMATION_433 = ["GK", "RB", "CB", "CB", "LB", "DM", "CM", "CM", "RW", "ST", "LW"]
BENCH = ["GK", "CB", "RB", "DM", "CM", "RW", "ST"]

FIRST_NAMES = [
    "Theo", "Kai", "Matteo", "Idris", "Rafael", "Jonah", "Elias", "Tomas", "Ruben", "Callum",
    "Amadou", "Leon", "Nico", "Sami", "Felix", "Owen", "Dario", "Kofi", "Arlo", "Mateus",
    "Isak", "Remy", "Ezra", "Hugo", "Tariq", "Bastian", "Luca", "Joaquin", "Femi", "Anton",
    "Milo", "Cyrus", "Yusuf", "Emil", "Santi", "Oskar", "Jasper", "Malik", "Teo", "Bram",
    "Ilan", "Soren", "Kian", "Davi", "Rory", "Lenny", "Ayo", "Viktor",
]
LAST_NAMES = [
    "Arkwell", "Brannick", "Castelo", "Dunmore", "Ellery", "Garrow", "Hollins", "Jandro",
    "Kessel", "Lowrie", "Marchetti", "Norwood", "Okoro", "Pellan", "Quarry", "Rask",
    "Sauveur", "Thorne", "Ugwu", "Varga", "Wendell", "Yarrow", "Zelenko", "Abernath",
    "Corvin", "Dace", "Embry", "Fallow", "Grisham", "Hadley", "Ilunga", "Juhl", "Kavanagh",
    "Lazaro", "Moreau", "Nakamura", "Oduya", "Prescot", "Ravel", "Steen", "Tavish", "Ueda",
    "Vossberg", "Whitlock", "Amsel", "Bexley", "Cardell", "Delacroix", "Esterly", "Fontaine",
]

# Attribute profile by position: (pace, passing, finishing, dribbling, defending, pressing, stamina)
PROFILE = {
    "GK": (45, 62, 20, 30, 74, 30, 70),
    "CB": (64, 66, 38, 50, 76, 62, 72),
    "RB": (76, 68, 45, 64, 68, 70, 78),
    "LB": (76, 68, 45, 64, 68, 70, 78),
    "DM": (64, 74, 50, 62, 72, 74, 80),
    "CM": (68, 77, 60, 70, 62, 72, 80),
    "RW": (84, 70, 70, 79, 42, 66, 72),
    "LW": (84, 70, 70, 79, 42, 66, 72),
    "ST": (78, 64, 79, 72, 40, 66, 70),
}
ATTRS = ("pace", "passing", "finishing", "dribbling", "defending", "pressing", "stamina")


@dataclass
class Player:
    player_id: str
    name: str
    number: int
    position: str
    team_id: str
    pace: int
    passing: int
    finishing: int
    dribbling: int
    defending: int
    pressing: int
    stamina: int
    fatigue: float = 0.0
    distance_m: float = 0.0
    top_speed_kmh: float = 0.0
    on_pitch: bool = False
    yellow_cards: int = 0
    sent_off: bool = False

    def eff(self, attr: str) -> float:
        """Attribute after fatigue."""
        return getattr(self, attr) * (1.0 - 0.15 * self.fatigue)

    def public(self) -> dict:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "number": self.number,
            "position": self.position,
        }


@dataclass
class Club:
    team_id: str
    name: str
    short_name: str
    colors: tuple[str, str]
    style: dict
    players: list[Player] = field(default_factory=list)

    def on_pitch(self) -> list[Player]:
        return [p for p in self.players if p.on_pitch]

    def bench(self) -> list[Player]:
        return [p for p in self.players if not p.on_pitch and not p.sent_off and p.distance_m == 0]

    def goalkeeper(self) -> Player:
        on = self.on_pitch()
        return next((p for p in on if p.position == "GK"), on[0])

    def player(self, player_id: str) -> Player:
        return next(p for p in self.players if p.player_id == player_id)

    def public(self) -> dict:
        return {
            "team_id": self.team_id,
            "name": self.name,
            "short_name": self.short_name,
            "colors": list(self.colors),
            "formation": "4-3-3",
            "starting_xi": [p.public() for p in self.players if p.on_pitch],
            "bench": [p.public() for p in self.players if not p.on_pitch],
        }


def build_club(team_id: str, name: str, short_name: str, colors: tuple[str, str], style: dict,
               quality: int = 0, seed: int | None = None, taken: set[str] | None = None) -> Club:
    """Build a squad deterministically from the club's own seed, so lineups stay
    the same no matter which match seed is used."""
    rng = random.Random(seed if seed is not None else team_id)
    club = Club(team_id, name, short_name, colors, style)
    taken = taken if taken is not None else set()  # names already used, shared across clubs
    numbers = iter([1, 2, 5, 4, 3, 6, 8, 10, 7, 9, 11, 13, 15, 12, 16, 14, 17, 19])
    for i, pos in enumerate(FORMATION_433 + BENCH):
        while True:
            first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
            if first not in taken and last not in taken:
                taken.update((first, last))
                full = f"{first} {last}"
                break
        base = PROFILE[pos]
        vals = {a: max(15, min(95, round(b + quality + rng.gauss(0, 5)))) for a, b in zip(ATTRS, base)}
        num = next(numbers)
        p = Player(player_id=f"{team_id}-{num:02d}", name=full, number=num, position=pos,
                   team_id=team_id, **vals)
        p.on_pitch = i < 11
        club.players.append(p)
    return club


def default_clubs() -> tuple[Club, Club]:
    """The two demo clubs: a patient possession side and a direct pressing side."""
    taken: set[str] = set()
    home = build_club(
        "HAL", "Halcyon City", "Halcyon", ("#1F4E8C", "#F2C14E"),
        style={"directness": 0.22, "block": "mid_block", "tempo": 1.0},
        quality=2, seed=1001, taken=taken,
    )
    away = build_club(
        "RED", "Redmarsh Rovers", "Redmarsh", ("#B3261E", "#F5F5F5"),
        style={"directness": 0.48, "block": "high_press", "tempo": 1.1},
        quality=0, seed=2002, taken=taken,
    )
    return home, away
