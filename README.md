# Second Screen: Explainable Live Match Intelligence

A multi-agent system that turns a live synthetic football match into fact-checked moments,
broadcast-ready overlays, and personalized experiences for analysts and casual fans.

Built for the Microsoft + Premier League *Inside the Game* Developer Hackathon.
All clubs, players, and match data are fictional and synthetically generated.

## Pipeline

| Stage | Component | Status |
|---|---|---|
| Ingest | `secondscreen.simulator`: synthetic match engine → event stream | ✅ |
| Interpret | Stats engine: possession, pressure index, PPDA, xG, pass difficulty, momentum | 🚧 |
| Explain | Agents: Moment Detector, Tactical Explainer, Fact-Checker, Recap | 🚧 |
| Render | Overlay cues: timed JSON synced to the match clock | 🚧 |
| Personalize | Persona agent: analyst / casual, favourite club & player, language | 🚧 |

## The simulator

A possession-by-possession model of a 90-minute match between two fictional clubs:
**Halcyon City** (patient possession, mid-block) and **Redmarsh Rovers** (direct, high press).

- Every pass, carry, pressure, tackle, interception, shot, save, foul, card, corner and substitution
  is emitted with an event ID, match clock, x/y coordinates (105×68 m) and player references.
- Raw measurements: pass distance, ball speed, shot speed, sprint speed, and distance covered
  (in physical snapshots every 5 minutes).
- Player fatigue, tactical blocks (high press / mid block / low block) and game-state reactions
  (chasing teams press, leading teams sit deep) drive the probabilities.
- **Hidden story arcs** bend each match: a pressing spell, a star takeover, a late fatigue fade,
  a late surge from the trailing side. Arcs are **never in the event feed**; they go into a separate
  `*.truth.json` so we can measure whether the stats engine and agents rediscover them from raw events.

Calibrated across 150 simulated matches: ~2.9 goals, ~27 shots, ~81% pass completion,
~9.6 km per player, top sprint speeds of 32–36 km/h.

### Usage

```bash
pip install -e ".[dev]"

# Simulate one match → data/match_SS00076.jsonl + data/match_SS00076.truth.json
python -m secondscreen.simulator generate --seed 76

# Find dramatic seeds (lead changes, comebacks, late goals)
python -m secondscreen.simulator scan --seeds 400 --top 10

# Replay as a live stream at 20× speed (a 90-minute match in ~5 minutes)
python -m secondscreen.simulator replay data/match_SS00076.jsonl --speed 20 --compact

pytest
```

### Demo match: seed 76

Halcyon City 4–2 Redmarsh Rovers. Redmarsh press high early and lead 2–1, then go down to ten men
at 54', fade physically, and get overrun as Halcyon throw everything forward in the last 20 minutes.

### Event schema (example)

```json
{
  "event_id": "SS00076-00301", "match_id": "SS00076", "seq": 301,
  "period": 1, "clock": "09:04", "clock_seconds": 544.9, "elapsed_seconds": 544.9,
  "type": "pass", "team_id": "RED", "player_id": "RED-07", "player_name": "…",
  "x": 10.4, "y": 46.1, "end_x": 17.8, "end_y": 52.3,
  "outcome": "complete", "recipient_id": "RED-11",
  "distance_m": 9.7, "ball_speed_kmh": 38.6, "under_pressure": false,
  "height": "ground", "progressive_m": -7.5,
  "score": {"HAL": 0, "RED": 0}, "possession_id": 31
}
```

Coordinates are normalised so the home team always attacks toward x = 105.

## Tech stack (target)

Microsoft Foundry · Microsoft Agent Framework · Azure Event Hubs · Azure Cosmos DB ·
Azure Container Apps · React · GitHub Copilot
