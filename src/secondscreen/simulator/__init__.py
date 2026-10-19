"""Synthetic, football-realistic match simulator for Second Screen."""
from secondscreen.simulator.engine import MatchSimulator, simulate
from secondscreen.simulator.teams import Club, Player, build_club, default_clubs

__all__ = ["MatchSimulator", "simulate", "Club", "Player", "build_club", "default_clubs"]
