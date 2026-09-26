# trade-regime

The regime **arbiter** for the trade-suite: it fuses the continuous
reads of the suite's regime *engines* — `trade-macro`, `trade-breadth`,
`trade-volforecast` — into one graded conviction number (0–100%) with
hysteresis.

The engines answer "what is the market doing." The arbiter answers
"how strongly should we believe it." Per explicit design direction:
**graded conviction, continuous 0–100% — not labeled buckets.**
Buckets cut from noisy signals are false precision. The arbiter
outputs a number; consumers threshold it if they want. There are no
stance labels anywhere in this package, not even for display.

It sits in the decision loop between the regime engines and the
portfolio manager: engines → arbiter → `trade-agents` PM →
`trade-risk` caps → `trade-hedge` tilt.

## Install

```bash
pip install trade-regime
# or from source
git clone https://github.com/crieck2010/trade-regime
cd trade-regime
pip install -e .
```

Requires Python 3.10+. No third-party dependencies — not even NumPy.

## Quick start

```python
from trade_regime.arbiter import RegimeArbiter
from trade_regime.presets import arbiter_kwargs
from trade_regime.signals import read_all

# Plain snapshot dicts from the engines (or your own data):
components = read_all(
    macro_snapshot={"regime": "EXPANSION", "z_score": 1.8},
    breadth_snapshot={"regime": "BROADENING", "fragility": 0.15},
    vol_summary={"current_vol": 0.13, "vol_min": 0.10, "vol_max": 0.45,
                 "forecast_vol": 0.13},
)

arbiter = RegimeArbiter(**arbiter_kwargs("balanced"))
snap = arbiter.assess(components)   # schema_version 1, JSON-serializable
print(snap["conviction"], snap["hysteresis"]["state"], snap["exposure_scale"])
```

Missing engines never break anything — unavailable components are
re-weighted out and listed in `snap["missing"]`:

```python
snap = RegimeArbiter(**arbiter_kwargs("balanced")).assess(read_all(None, None, None))
# composite 50.0 (neutral), conviction 50.0, missing ['breadth', 'macro', 'vol']
```

Hysteresis memory survives restarts via a tiny state dict (the CLI
`--state` pattern):

```python
mem = arbiter.memory_dict()          # {"conviction":..., "persist_count":..., ...}
fresh = RegimeArbiter(**arbiter_kwargs("balanced"))
fresh.restore(mem)                   # identical hysteresis behavior
```

CLI:

```bash
trade-regime demo                                   # seeded 120-day arc
trade-regime conviction --macro m.json --breadth b.json --vol v.json
trade-regime conviction --macro m.json --state state.json --history hist.jsonl
trade-regime components --demo --day 55             # inspect sub-convictions
trade-regime presets                                # postures + rationale
```

See `examples/regime_example.py` for the full walkthrough.

## The maths

**What you learn.** How much to trust the market's current regime — as
a single number you can reason about, not a label you argue about.
The arbiter turns three noisy regime reads into one conviction dial
with memory, so downstream sizing moves continuously with evidence
instead of lurching on boundary noise.

**Why it matters.** Daily regime reads are noisy. A raw composite that
jitters between 68 and 74 means nothing changed, but a sizing layer
watching the raw number would flap exposure every day. Hysteresis is
the arbiter's memory: small wobbles are absorbed, sustained drifts
earn a move, violent breaks act at once. "I don't know" maps to *hold*,
not to a coin flip — and because there are no buckets, there is no
boundary to sit on.

**The maths.**

- *Component transforms (0–100 each, 100 = full risk-on).* Every
  engine snapshot becomes a sub-conviction through an inspectable
  formula — no black boxes:
  - breadth: `clamp(base(regime) − 50·fragility + 10·thrust − 10·divergence)`,
    with base BROADENING 75 / NEUTRAL 50 / NARROWING 25. Labels are
    coarse, so they sit at quarter-points — extremes must be *earned*
    by the continuous adjustments. The fragility drag is asymmetric by
    design: it only ever pushes toward risk-off.
  - macro: `clamp(base(regime) + 10·clamp(z/2, −1, 1) ± 5·alerts)`,
    base EXPANSION 75 / NEUTRAL 50 / CONTRACTION 25. A 2-sigma
    copper/gold deviation is a strong read; beyond that the indicator
    is already screaming. Fresh transition alerts nudge ±5.
  - vol (inverted — high vol is risk-off pressure):
    `stress = 0.6·pct(current) + 0.4·pct(forecast)` over the trailing
    window, `+ 0.15` if the forecast exceeds 1.25× current
    (accelerating into the spike), `+ 0.10` if vol-of-vol > 0.5;
    `sub = 100·(1 − stress)`. The forecast gets 40% because vol
    mean-reverts — the forward read tempers the spot read.
- *Weighted fusion.* `composite = Σ wᵢ·subᵢ / Σ wᵢ` over *available*
  components; unavailable ones are dropped and the remainder
  renormalized. Default weights macro 0.40 / breadth 0.35 / vol 0.25:
  the slowest, most fundamental read anchors; vol is fastest and
  noisiest, so it can temper the composite but never flip it alone.
  All-missing fuses to 50.0 — no information is neutral, not risk-off;
  risk-off requires *evidence*.
- *Hysteresis on conviction.* Let `r` be the raw composite and `c`
  the held conviction (balanced preset):
  - `|r − c| ≤ 10` → **hold** ("within deadband").
  - `|r − c| > 20` → **update at once** ("large move beyond confirm
    band") — a violent break should not wait for confirmation.
  - in between → **update only after 3 consecutive same-direction
    observations** beyond the band edge ("persistent move") —
    stubborn small moves earn trust; a direction flip restarts the
    count, so alternating noise *never* releases.
  - every release is **rate-limited to 25 pts** per assessment —
    conviction walks, it never teleports.
  The memory of the arbiter is exactly three numbers: the held
  conviction, the persistence count, and its direction.
- *Exposure.* `exposure_scale = conviction / 100`, linear and
  deliberately dumb. The arbiter **suggests**; `trade-risk` owns final
  sizing. Any floor, curve, or stand-down rule lives downstream.

**Honest limitations.** Garbage in from the engines = garbage
conviction out; the arbiter cannot fix bad inputs, it can only refuse
to move on them. Weights, deadbands, and presets are *policy
choices*, not discovered constants — other choices are defensible and
the presets document their bets. Hysteresis delays *true* regime
changes by design (up to the deadband plus persistence lag); in a
crash the arbiter is late and says so. Vol-stress lags by
construction (trailing window + forecast). Breadth/macro inputs are
daily — intraday conviction will be stale; do not run this on
minute bars and expect it to keep up. The demo arc is illustrative,
not backtest evidence.

## Interop

Stable `schema_version: 1` snapshot contract (see
`docs/ARCHITECTURE.md`). Lazy, plain-data adapters — no sibling
imports, ever:

- `market_context_provider(snapshot)` → trade-agents: the canonical
  fused context. This **supersedes wiring trade-breadth / trade-macro
  snapshots into the agents individually**; the direct engine paths
  keep working unchanged.
- `risk_regime_input(snapshot)` → trade-risk: advisory regime input.
  `exposure_scale` is explicitly advisory — trade-risk owns sizing.
- `hedge_tilt_input(snapshot)` → trade-hedge: defensive/aggressive
  tilt in [−1, +1]; direction and magnitude only, never orders.

All three adapters share a base shape: `source`, `schema_version`
(1), `conviction`, `composite_raw`, `timestamp`, `snapshot_id`,
`missing`, `hysteresis_state` (`"held"`/`"updated"`),
`hysteresis_reason` (arbiter's plain-text reason, e.g.
`"within deadband (+/-10 pts)"`), and
`hysteresis_prior_conviction` (conviction before this assessment,
`None` on first assessment). The hysteresis fields are
None-tolerant: a snapshot without a `hysteresis` block yields
`None`, never a `KeyError`.

Extension slot: `read_all(..., extra={"name": (snapshot, reader)})`
adds a fourth component without touching the core readers — see
`docs/METHODOLOGY.md`.

## Docs

- `docs/ARCHITECTURE.md` — where the arbiter sits, state model, scaling
- `docs/METHODOLOGY.md` — every formula, preset, and failure mode
- `docs/DECISION_LOOP.md` — the supervised/autonomous decision loop
- `CHANGELOG.md` — release history

## License

MIT. See `LICENSE`.
