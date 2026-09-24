# ARCHITECTURE

## Where the arbiter sits

```
trade-macro ──snapshot──┐
trade-breadth ─snapshot─┤─> trade-regime ──RegimeState──> trade-agents (PM: market_context)
trade-volforecast ───────┘        │                              │
                                  ├── risk_caps ────────────────> trade-risk
                                  └── hedge_trigger ───────────> trade-hedge
```

The engines are *sensors*. The arbiter is the *prefrontal cortex*:
it does not generate signals, it adjudicates them. Downstream, the
portfolio manager reads conviction and sleeve scales each cycle;
risk reads caps; the hedge desk reads stand-down events. Every arrow
is a plain-data dict; every import is lazy.

## Module map

| Module | Responsibility |
|---|---|
| `signals.py` | Normalize engine snapshots to [-1, +1]; `Signal` / `SignalUnavailable` |
| `arbiter.py` | Weighted fusion, conviction curve, Schmitt-trigger stance, `RegimeState` |
| `sizing.py` | Conviction → exposure dial, per-sleeve shutdown curves, stand-down |
| `history.py` | Append-only assessment log (memory + JSONL), transition flags |
| `presets.py` | Named risk postures: conservative / balanced / aggressive |
| `adapters.py` | Lazy hooks: `pm_context`, `risk_caps`, `hedge_trigger`, `assess_live` |
| `demo.py` | Seeded 300-day history with planted regime shifts |
| `cli.py` | `assess`, `history`, `weights`, `demo`, `presets`, `license`, `update-check` |
| `licensing.py` | License-key / update-check hooks (suite convention) |

## State model

`RegimeArbiter.assess()` is a pure function of (signals, previous
stance). The object's only state is one integer (`self.stance`).
`RegimeHistory` is the durable memory: replaying it rebuilds stance
exactly, so a crashed or restarted process loses nothing.

## The RegimeState contract (schema_version 1)

```json
{
  "schema_version": 1,
  "ts": "2026-09-24T17:00:00+00:00",
  "score": 0.45,
  "conviction": 56.2,
  "stance": 1,
  "stance_label": "CONSTRUCTIVE",
  "prev_stance": 0,
  "transition": true,
  "contributions": {"macro": {"score": 1.0, "weight": 0.4,
                              "contribution": 0.4, "detail": {}}},
  "weights_used": {"macro": 0.4},
  "missing": [],
  "n_signals": 3,
  "config": {"threshold": 0.25, "band": 0.15,
             "engage_at": 0.4, "release_at": 0.1}
}
```

`stance_label` is display-only. Decisions use `score` and
`conviction`. The dict must survive a JSON round-trip (enforced in
code).

## Scaling

- `assess()` is stateless-apart-from-stance and CPU-trivial: it
  parallelizes across symbols, days, or Monte-Carlo paths with no
  coordination. One process handles the whole suite's regime needs.
- The expensive work (building engine snapshots) lives in the
  engines, not here; the arbiter fuses precomputed numbers.
- History is append-only; concurrent writers should shard by
  symbol/book or funnel through one writer — the JSONL log is not
  lock-protected.
- Threading: `RegimeArbiter` instances are not thread-safe by design
  (stance mutation). One arbiter per thread, or external locking.
  Sharing one arbiter across threads is a bug; sharing the *code*
  across threads is the intended pattern.
