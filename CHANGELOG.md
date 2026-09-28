# Changelog

## v0.2.1 — 2026-09-28

Session/time-of-day awareness — the arbiter now knows *when* a read
was taken, not just what the market-risk reads say:

- `session.py` (new, stdlib only): `session_component` reader +
  `read_session` / `session_extra` / `session_weights` helpers.
  Graded 0–100 session-liquidity sub-conviction wired through the
  documented `extra` extension slot — no core arbiter changes.
- US equities (`America/New_York`): 09:30–16:00 → 100 (neutral);
  pre/after-hours grade 30 ↔ 100; deep overnight 21:00–03:00 → 10;
  weekends + NYSE holidays → 5. Piecewise-linear anchors: continuous,
  no cliffs at session boundaries.
- Futures: CME-style proxy curve (cash overlap 100, overnight 70,
  17:00–18:00 halt ramps to 25, weekends 5). Crypto: 100 always.
- Fusion weight 0.15, rebalanced pro-rata (macro 0.34 / breadth
  0.2975 / vol 0.2125 / session 0.15). Max session drag 14.25 pts —
  below the 20-pt confirm band, so the session input tempers
  conviction but can never teleport it alone.
- Timezone-explicit; naive datetimes assumed UTC and flagged loudly
  in `detail`. Built-in NYSE holiday table covers 2026–2027 only
  (explicit limitation); `calendar={"holidays": [...]}` injects any
  calendar. Early closes not modeled (documented).
- Docs: `docs/SESSION.md`, `docs/INTEROP.md` (new), METHODOLOGY §1.4,
  README "The maths".
- trade-agents needs no changes: the drag flows through
  `conviction → exposure_scale` automatically.

## v0.2.0 — 2026-09-26

Minor, additive, backwards compatible. `schema_version` stays 1.

- `adapters.py` — `_base()` now also emits the arbiter's hysteresis
  context the consumer (trade-agents) needs: `hysteresis_reason` (the
  arbiter's plain-text reason, e.g. `"within deadband (+/-10 pts)"`)
  and `hysteresis_prior_conviction` (conviction before this
  assessment, `None` on first assessment). Previously only
  `hysteresis_state` was passed through and the reason was dropped.
  Both flow into all three adapters (`market_context_provider`,
  `risk_regime_input`, `hedge_tilt_input`) and are None-tolerant:
  a snapshot without a `hysteresis` block yields `None` fields,
  never a `KeyError`. Module docstring hook specs document the
  base shape.
- Pinned cross-repo contract for `market_context_provider`:
  `source`, `schema_version` (1), `conviction`, `composite_raw`,
  `timestamp`, `snapshot_id`, `missing`, `hysteresis_state`,
  `hysteresis_reason`, `hysteresis_prior_conviction`,
  `exposure_scale_advisory`, `components`, `note`.
- No change to arbiter math, hysteresis logic, or snapshot schema.

## v0.1.1 — 2026-09-26

Redesign to the authoritative arbiter spec (graded conviction, no buckets):

- `signals.py` — components now map to **0–100 sub-convictions**
  (100 = full risk-on): breadth = regime base − fragility drag ±
  thrust/divergence; macro = regime base ± z-score ± alert nudges;
  vol = inverted stress (level + forecast + acceleration + vol-of-vol)
- `arbiter.py` — **hysteresis on the conviction number itself**:
  hold within ±10 pts deadband, immediate (rate-limited) release
  beyond ±20 pts, 3-consecutive-observation persistence for moves in
  between, 25-pt max change per assessment; memory is 3 numbers with
  `memory_dict()`/`restore()` round-trip
- Snapshot contract `schema_version: 1`: timestamp, conviction,
  per-component sub-convictions + weights, hysteresis state
  (held/updated + reason), advisory `exposure_scale`, provenance
- **Removed:** stance labels (`DEFENSIVE`/`NEUTRAL`/`CONSTRUCTIVE`),
  Schmitt-trigger-on-score, `sizing.py` sleeve curves — the arbiter
  outputs a number; sizing lives in trade-risk
- `adapters.py` — renamed to the sibling convention:
  `market_context_provider` (supersedes individual breadth/macro
  wiring), `risk_regime_input` (advisory), `hedge_tilt_input`
  (−1..+1 tilt); zero sibling imports
- `presets.py` — conservative/balanced/aggressive with documented
  rationale (weights, deadband, confirm band, persistence, rate limit)
- `demo.py` — seeded 120-day arc (bull → narrowing/fragile →
  vol spike → recovery) doubling as regression fixture
- CLI: `conviction` (snapshot JSON files + `--state` hysteresis
  memory + `--history` JSONL), `components`, `presets`, `demo`
- 91 tests, all passing

## v0.1.0 — 2026-09-24

Initial release: the regime arbiter.

- `signals.py` — normalize trade-macro / trade-breadth /
  trade-volforecast snapshots to [-1, +1]; `SignalUnavailable` sentinel
- `arbiter.py` — weighted fusion with missing-signal re-weighting,
  graded 0–100% conviction, Schmitt-trigger hysteresis, `RegimeState`
  (schema_version 1, JSON-serializable)
- `sizing.py` — conviction → exposure dial, per-sleeve shutdown
  curves (mean-reversion first, trend tapers, short-vol last), hard
  stand-down floor
- `history.py` — append-only assessment log (memory + JSONL)
- `presets.py` — conservative / balanced / aggressive postures
- `adapters.py` — lazy hooks: `pm_context` (trade-agents),
  `risk_caps` (trade-risk), `hedge_trigger` (trade-hedge),
  `assess_live` (fail-soft)
- `demo.py` — seeded 300-day history with planted regime shifts
- CLI: `assess`, `history`, `weights`, `demo`, `presets`,
  `license`, `update-check`
- Docs: README ("The maths"), ARCHITECTURE, METHODOLOGY, DECISION_LOOP
- 55 tests, all passing
