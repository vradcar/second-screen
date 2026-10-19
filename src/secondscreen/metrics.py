"""Shared football math used by both the simulator and the stats engine.

Coordinates are in metres on a 105 x 68 pitch. Functions here take positions
in the *attacking frame*: x runs from the team's own goal line (0) to the
opponent's goal line (105), y from the right touchline (0) to the left (68).
"""
from __future__ import annotations

import math

PITCH_X = 105.0
PITCH_Y = 68.0
GOAL_Y = PITCH_Y / 2
GOAL_WIDTH = 7.32

# Penalty area bounds in the attacking frame.
BOX_X = PITCH_X - 16.5
BOX_Y_MIN = GOAL_Y - 20.16
BOX_Y_MAX = GOAL_Y + 20.16


def sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def in_box(x: float, y: float) -> bool:
    return x >= BOX_X and BOX_Y_MIN <= y <= BOX_Y_MAX


def shot_geometry(x: float, y: float) -> tuple[float, float]:
    """Distance to goal centre (m) and the angle the goal mouth subtends (rad)."""
    dx = max(PITCH_X - x, 0.1)
    dy = abs(y - GOAL_Y)
    dist = math.hypot(dx, dy)
    angle = math.atan2(GOAL_WIDTH * dx, dx * dx + dy * dy - (GOAL_WIDTH / 2) ** 2)
    if angle < 0:
        angle += math.pi
    return dist, angle


def expected_goals(x: float, y: float, body_part: str = "foot", situation: str = "open_play") -> float:
    """Simple location-based xG model.

    Calibrated so a central shot from the penalty spot is ~0.29, from 6 m ~0.58,
    and from 25 m ~0.03. Headers and direct free kicks are discounted.
    """
    if situation == "penalty":
        return 0.76
    dist, angle = shot_geometry(x, y)
    logit = 0.3 - 0.16 * dist + 0.9 * angle
    if body_part == "head":
        logit -= 0.9
    if situation == "counter":
        logit += 0.25
    elif situation == "free_kick":
        logit -= 0.5
    return round(sigmoid(logit), 4)


def pass_logit(distance_m: float, under_pressure: bool, progressive_m: float, into_box: bool) -> float:
    """Baseline completion logit for an average (70-rated) passer."""
    logit = 3.6 - 0.05 * distance_m - 0.025 * max(progressive_m, 0.0)
    if under_pressure:
        logit -= 0.8
    if into_box:
        logit -= 1.0
    return logit


def pass_difficulty(distance_m: float, under_pressure: bool, progressive_m: float, into_box: bool) -> float:
    """Difficulty rating 0-10: how likely an average passer is to fail this pass."""
    p = sigmoid(pass_logit(distance_m, under_pressure, progressive_m, into_box))
    return round((1.0 - p) * 10.0, 1)
