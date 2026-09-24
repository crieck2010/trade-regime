# trade-regime

The regime **arbiter** for the trade-suite: it fuses the continuous
scores of the suite's regime *engines* — `trade-macro`, `trade-breadth`,
`trade-volforecast` — into one graded conviction number (0–100%) with
hysteresis, and maps conviction to exposure.

The engines answer "what is the market doing." The arbiter answers
"how strongly should we believe it, and how much risk does that
justify." Per explicit design direction: **graded conviction sizing,
not more labeled buckets** — buckets cut from noisy signals are false
precision. Stance labels (`DEFENSIVE`/`NEUTRAL`/`CONSTRUCTIVE`) exist
for display only; no decision is ever taken on a label.

Part of the [trade-suite](https://github.com/crieck2010/trade-suite)
algorithmic trading system. It sits in the decision loop between the
regime engines and the portfolio manager: engines → arbiter →
`trade-agents` PM → `trade-risk` caps → `trade-hedge` stand-down events.

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
from trade_regime.signals import read_all
from trade_regime.sizing import sleeve_scales

# Plain snapshot dicts from the engines (or your own data):
signals = read_all(
    macro_snapshot={"z_score": 1.8, "regime": "EXPANSION"},
    breadth_snapshot={"regime_score": 0.9, "fragility": 0.2},
    vol_summary={"current_vol": 0.14, "vol_min": 0.10, "vol_max": 0.45},
)

arbiter = RegimeArbiter()          # balanced preset defaults
state = arbiter.assess(signals)    # -> RegimeState dict, schema_version 1
print(state["score"], state["conviction"], state["stance_label"])
print(sleeve_scales(state["conviction"]))
```

Missing engines never break anything — unavailable signals are
re-weighted out and listed in `state["missing"]`:

```python
from trade_regime.signals import read_all
state = RegimeArbiter().assess(read_all(None, None, None))
# score 0.0, conviction 0.0, missing ['breadth', 'macro', 'vol']
```

CLI:

```bash
trade-regime demo                        # planted-shift walkthrough
trade-regime assess --demo               # latest demo day + PM context
trade-regime assess --live               # from installed engines (fail-soft)
trade-regime history --transitions-only  # stance changes in the demo
trade-regime presets                     # conservative / balanced / aggressive
trade-regime weights --validate macro=0.5,breadth=0.3,vol=0.2
```

See `examples/regime_example.py` for the full walkthrough.

## The maths

**What you learn.** How much to trust the market's current regime — as
a number you can size against, not a label you argue about. The
arbiter turns three noisy regime reads into one conviction dial and
one rule for exposure, with memory (hysteresis) so it doesn't flap on
boundary noise.

**Why it matters.** Binary regime labels whipsaw: a z-score of 0.49
vs 0.51 is the same market wearing two different hats. Sizing on
labels means your book lurches on noise. Sizing on a graded,
hysteresis-smoothed conviction means exposure moves continuously with
evidence — and the hard stand-down rule means "I don't know" maps to
flat, not to a coin flip.

**The maths.**

- *Signal normalization.* Each engine snapshot becomes a score in
  [-1, +1] (risk-off → risk-on):
  `macro = clamp(z_252 / 3)` — a 3-sigma copper/gold deviation is a
  full-scale regime read; beyond that the indicator is already
  screaming. `breadth = clamp(regime_score / 1.5) − 0.5 × fragility`
  — the fragility drag is the point: a maximally fragile market can
  never score above +0.5. `vol = 1 − 2 × percentile(current vol)` over
  the trailing window. Missing z/labels fall back to half-scale
  regime-label maps (±0.5); missing everything is `SignalUnavailable`.
- *Weighted fusion.* `score = Σ wᵢ·sᵢ / Σ wᵢ` over *available*
  signals; unavailable ones are dropped and the remainder
  renormalized. Default weights macro 0.40 / breadth 0.35 / vol 0.25:
  the slowest, most fundamental read anchors; vol is fastest and
  noisiest, so it can never flip the arbiter alone. All-missing fuses
  to 0.0 — no information is neutral, not risk-off; risk-off requires
  *evidence*.
- *Conviction.* `conviction = 100 × min(1, |score| / 0.8)`,
  piecewise-linear and monotone in |score|: every unit of agreement
  buys the same unit of conviction. Saturates at |score| = 0.8
  (strong cross-signal agreement).
- *Hysteresis (Schmitt trigger).* Stance ∈ {−1, 0, +1} flips only
  across a dead zone: from neutral, engage at |score| ≥ 0.40; release
  back to neutral at |score| ≤ 0.10. A violent reversal walks *through*
  neutral over two assessments — it never teleports. The memory of
  the arbiter is exactly one integer.
- *Exposure.* `exposure_scale = 0` below conviction 25 (stand-down),
  else `0.2 + 0.8 × (c − 25)/75` — re-entry after stand-down is
  tentative by construction. Sleeves die in order: mean-reversion
  first (dead below 40 — ranges break first), trend tapers linearly
  (never binary — it keeps its crisis alpha), short-vol last (needs
  conviction ≥ 65 — pennies, steamroller).

**Honest limitations.** Garbage in from the engines = garbage
conviction out; the arbiter cannot fix bad inputs, it can only refuse
to be confident about them. Weights are judgment, not science — they
encode a belief about signal speeds, and other beliefs are
defensible. Hysteresis delays *true* regime changes by design (up to
the dead-zone width); in a crash, the arbiter is late and says so.
The stand-down floor (25) is a convention. Demo data is illustrative,
not backtest evidence.

## Interop

Stable `schema_version: 1` `RegimeState` contract (see
`docs/ARCHITECTURE.md`). Lazy adapters for `trade-agents`
(`pm_context` — the dict the PM reads each cycle), `trade-risk`
(`risk_caps`), `trade-hedge` (`hedge_trigger`) — no hard
dependencies; siblings are imported only when called. The full
supervised/autonomous loop this enables is specified in
`docs/DECISION_LOOP.md`.

## Docs

- `docs/ARCHITECTURE.md` — where the arbiter sits, state model, scaling
- `docs/METHODOLOGY.md` — every formula, preset, and failure mode
- `docs/DECISION_LOOP.md` — the supervised/autonomous decision loop
- `CHANGELOG.md` — release history

## License

MIT. See `LICENSE`.
