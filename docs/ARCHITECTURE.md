# ARCHITECTURE

## Where the arbiter sits

```
 trade-macro ──snapshot──┐
 trade-breadth ─snapshot─┤
 trade-volforecast ───────┤
                          ▼
                   ┌─────────────┐
                   │ trade-regime │  graded conviction 0-100 + hysteresis
                   └──────┬──────┘
                          │ market_context_provider (canonical fused context)
                          ▼
                   ┌─────────────┐
                   │ trade-agents │  PM decision layer
                   └──────┬──────┘
                          │ risk_regime_input (advisory)
                          ▼
                   ┌─────────────┐
                   │  trade-risk  │  owns final sizing
                   └──────┬──────┘
                          │ hedge_tilt_input (direction/magnitude)
                          ▼
                   ┌─────────────┐
                   │ trade-hedge  │  proposes overlays, never executes
                   └─────────────┘
```

The arbiter is a pure function of (components, prior memory).  It
never fetches data, never imports siblings, never trades.

## Module map

| module        | responsibility |
|---------------|----------------|
| `signals.py`  | engine snapshots → 0–100 sub-convictions; `Component` / `ComponentUnavailable`; `read_all` (+ `extra` extension slot) |
| `arbiter.py`  | weighted fusion → raw composite; conviction hysteresis; snapshot contract (`schema_version: 1`); `exposure_scale` (advisory) |
| `presets.py`  | conservative / balanced / aggressive postures with documented rationale |
| `adapters.py` | `market_context_provider`, `risk_regime_input`, `hedge_tilt_input` — plain dicts, zero imports |
| `demo.py`     | seeded 120-day arc (bull → narrowing → vol spike → recovery); doubles as regression fixture |
| `history.py`  | `ConvictionHistory`: append-only snapshot log (memory + JSONL) |
| `cli.py`      | `demo`, `conviction`, `components`, `presets`, `license`, `update-check` |
| `licensing.py`| suite-wide license-key / update-check hooks |

## State model

The arbiter's memory is exactly three numbers:

- `conviction` — the held conviction (None until first assessment)
- `_persist_count` / `_persist_dir` — how many consecutive
  same-direction observations have sat beyond the deadband edge

That is the entire state.  It serializes via `memory_dict()` /
`restore()`, which is what the CLI `--state` file carries between
runs.  A crashed process loses nothing that the last snapshot plus
three numbers cannot rebuild.

## Snapshot contract (schema_version 1)

```json
{
  "schema_version": 1,
  "snapshot_id": "<uuid4 hex>",
  "timestamp": "<ISO-8601 UTC>",
  "conviction": 72.4,
  "composite_raw": 78.1,
  "components": {
    "macro":   {"sub_conviction": 82.5, "weight": 0.40, "contribution": 33.0, "detail": {...}},
    "breadth": {"sub_conviction": 70.0, "weight": 0.35, "contribution": 24.5, "detail": {...}},
    "vol":     {"sub_conviction": 94.3, "weight": 0.25, "contribution": 23.6, "detail": {...}}
  },
  "weights_configured": {"macro": 0.4, "breadth": 0.35, "vol": 0.25},
  "hysteresis": {
    "state": "held",
    "reason": "within deadband (+/-10 pts)",
    "prior_conviction": 72.4,
    "deadband": 10.0,
    "confirm_band": 20.0,
    "persistence": "0/3",
    "max_daily_change": 25.0
  },
  "exposure_scale": 0.724,
  "missing": [],
  "provenance": {
    "input_snapshot_ids": {"macro": "...", "breadth": "...", "vol": "..."},
    "input_schema_versions": {"macro": 1, "breadth": 1, "vol": 1},
    "trade_regime_version": "0.2.0",
    "preset": "balanced"
  }
}
```

Every snapshot is asserted JSON-serializable at construction time
(`json.dumps` in `assess`).  Downstream code may rely on these keys;
new keys may be added, existing keys will not change meaning within
schema_version 1.

## Scaling

- **Throughput:** `assess()` is O(components).  A universe of 500
  names assessed through one shared arbiter is one call per bar —
  trivial.
- **Parallelism:** `assess` is a pure function of its inputs plus the
  tiny memory dict; per-symbol arbiters are independent and
  embarrassingly parallel.  Share nothing.
- **Latency:** no I/O, no network, no sibling imports.  The hot path
  is microseconds of arithmetic.
- **Memory:** O(1) per arbiter instance.  History is opt-in
  (`ConvictionHistory`); the arbiter itself never accumulates.
- **Determinism:** identical (components, memory, config) → identical
  snapshot.  The demo arc is seeded for the same reason.
