"""Deterministic stats engine: raw match events in, statistics and evidence-linked signals out."""
from secondscreen.stats.engine import StatsEngine
from secondscreen.stats.signals import THRESHOLDS, Signal

__all__ = ["StatsEngine", "Signal", "THRESHOLDS"]
