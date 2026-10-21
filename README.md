# Second Screen: Explainable Live Match Intelligence

A multi-agent system that turns a live synthetic football match into fact-checked moments,
broadcast-ready overlays, and personalized experiences for analysts and casual fans.

Built for the Microsoft + Premier League *Inside the Game* Developer Hackathon.
All clubs, players, and match data are fictional and synthetically generated.

## Pipeline

| Stage | Component | Status |
|---|---|---|
| Ingest | `secondscreen.simulator`: synthetic match engine → event stream | ✅ |
| Interpret | `secondscreen.stats`: possession, PPDA, pressing intensity, xG, pass difficulty, momentum, control/chaos, evidence-linked signals | ✅ |
| Explain | `secondscreen.agents`: Tactical Analyst → Fact-Checker (revise loop) → Recap, on Microsoft Agent Framework + Foundry | ✅ |
| Render | Timed, machine-readable overlay cues (lower thirds, player tags, stat pops) | ✅ |
| Personalize | Persona agent: analyst / casual, favourite club, player cam, EN / ES / FR | ✅ |

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
pip install -e ".[agents,dev]"

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

## The stats engine

`secondscreen.stats.StatsEngine` ingests events one at a time (the same code path for live
streams and batch replays) and emits **signals**: goals with game state, big chances, red cards,
speed alerts, elite passes, momentum swings, control/chaos regime changes, pressing spells,
hot streaks, fatigue fades, and late surges.

Every signal carries the stat values (`facts`) and the event IDs (`evidence`) behind it.
That contract is what lets the Fact-Checker agent reject any sentence it can't trace to data.

Key definitions:
- **xG**: location model (distance + goal-mouth angle), discounted for headers and free kicks
- **Pass difficulty (0–10)**: how often an average passer fails that pass, from distance,
  progression, pressure and whether it ends in the box
- **PPDA**: opponent passes in their own 60% per defensive action there
- **Pressing intensity**: high defensive actions per minute of opponent possession versus the
  team's own baseline, shrunk with a pseudo-count so low-pressing sides don't trigger on noise
- **Momentum (−100…100)**: exponentially decayed threat (box entries, shots weighted by xG,
  high turnovers, corners)
- **Regime**: control (one side ≥66% of the ball over 5 minutes), chaos (≥3.4 possession
  changes a minute), or balanced, with confirmation and dwell time to avoid flicker

### Does it find the hidden stories?

Detectors were tuned on seeds 0–39 and scored on 60 **held-out** matches (`seeds 1000–1059`):

| Hidden arc | Recall | Precision | Detections per match |
|---|---|---|---|
| Late surge | 0.87 | 0.65 | 1.2 |
| Fatigue fade | 0.78 | 0.57 | 1.4 |
| Pressing spell | 0.68 | 0.36 | 2.7 |
| Star takeover (hot streak) | 0.35 | 0.48 | 0.7 |

Pressing precision counts detections that line up with a real tactical switch (e.g. a side
chasing the game) as correct. Hot streaks deliberately favour precision: a false
"he's taking over" on air is worse than a missed one.

```bash
python -m secondscreen.stats data/match_SS00076.jsonl --out data   # signals + snapshot
python -m secondscreen.stats.evaluate --seeds 60 --start 1000       # detector scorecard
```

## The agents

Built on **Microsoft Agent Framework** (`Agent`, `WorkflowBuilder`) with models served from
**Microsoft Foundry**.

```
signal ──► Tactical Analyst ──draft──► Fact-Checker ──approved──► Persona ──► moment + overlay cues
               ▲                          │    │
               └──── revise (feedback) ───┘    └── rejected 3× / model outage ──► Fallback template
```

| Agent | Job | Output |
|---|---|---|
| Tactical Analyst | Explains *why* a flagged moment matters (game state, pressing, momentum, control vs chaos) | `MomentDraft`: headline, summary, why it matters, claims citing fact keys |
| Fact-Checker | Deterministic grounding rules (every number, name and fact key must trace to the stats engine), then an LLM judge for causal and semantic support | approve, or send back specific feedback |
| Persona | Renders the approved moment for each viewer: analyst or casual, favourite club, player cam, language | one rendering per persona, re-checked; any that adds a number or person is replaced |
| Recap | Full-time report from approved moments and final stats only | `Recap`, checked with the same rules |

Design choices:
- **Numbers come from code, words come from models.** Agents only ever see a flat table of
  `key = value` facts and must cite keys for every claim, which makes fact-checking mechanical.
- **Models only where language adds value.** Speed tags, cards, substitutions and pass-difficulty
  pops are deterministic overlay cues and render instantly.
- **Failure is a path, not a crash.** A rejected draft gets specific feedback; after two revisions,
  or if the model times out or returns bad JSON, a fact-safe template goes to air instead.
- **Record / replay.** Live runs cache every model response, so the demo replays exactly with no
  network and no cost.

Overlay cue (what a rendering partner consumes):

```json
{"cue_id": "SS00076-M028-halcyon_fan", "persona_id": "halcyon_fan", "lang": "en",
 "type": "lower_third", "clock": "79:46", "elapsed": 4910.2, "duration_s": 10, "priority": 1.0,
 "team_id": "HAL", "player_id": "HAL-08",
 "text": {"strap": "…", "card": "…"}, "stats": [{"label": "xG", "value": "0.31"}],
 "evidence": ["SS00076-02281", "…"]}
```

### Running the agents

```bash
pip install -e ".[agents,dev]"

# Offline: deterministic mock model (CI uses this)
python -m secondscreen.agents data/match_SS00076.jsonl --mode mock --inject-errors 4

# Live against Foundry, recording every response to data/llm_cache.jsonl
cp .env.example .env    # fill in your endpoint; key or `az login`
python -m secondscreen.agents data/match_SS00076.jsonl --mode record

# Replay the recorded run: no network, identical output
python -m secondscreen.agents data/match_SS00076.jsonl --mode replay
```

Auth: set `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_API_KEY`, or set `AZURE_AI_PROJECT_ENDPOINT`
and run `az login` (grant yourself access once with `infra/grant-access.sh`).

## Watch it: the broadcast + second screen UI

```bash
pip install -e ".[agents,server,dev]"
python -m secondscreen.server          # open http://localhost:8000
```

- **The TV** plays the synthetic match as a broadcast: ball and 22 players animated from the
  event feed, scorebug, game-state chip, player tags (speed, shot speed, cards) and on-air
  lower thirds that wipe in as the agents publish.
- **Two phones** show the second-screen app for two viewer profiles side by side (analyst,
  Halcyon fan, Redmarsh fan in Spanish, Lazaro player cam in French). Same moment, different story.
- **Tap any card** to see why it's on screen: each claim, the exact facts it cites, the
  fact-check trail (rejections, revisions, judge verdicts) and the source event IDs.
- Below the TV: a momentum river for the whole match and a live stat duel.

Controls: agent source (recorded live run, offline mock, or live Foundry), start point, speed,
and, for recorded runs, a timeline scrubber: drag to any minute (back or forward), or click a goal /
red-card marker to jump to just before it. Seeking rebuilds the stats engine's state up to that
point instantly. Live and offline-model modes have no scrubber, since agent moments are written as
the match plays.
The server replays the event file on its real timestamps; the stats engine runs on every event
and agent moments run in a background queue, so the stream never waits on a model.

The UI is React + TypeScript (`web/`); `npm run build` writes into the Python package so the
server ships it.

## Tech stack (target)

Microsoft Foundry · Microsoft Agent Framework · Azure Event Hubs · Azure Cosmos DB ·
Azure Container Apps · React · GitHub Copilot
