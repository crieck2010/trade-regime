# Changelog

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
