# METHODOLOGY

Every formula in trade-regime, its rationale, and its failure modes.

## 1. Signal normalization (signals.py)

| Engine | Primary formula | Fallback |
|---|---|---|
| trade-macro | `clamp(z_252 / 3)` | regime label → ±0.5 / 0.0 |
| trade-breadth | `clamp(regime_score / 1.5) − 0.5 × fragility` | regime label → ±0.5 / 0.0, minus fragility drag |
| trade-volforecast | `1 − 2 × percentile(current_vol)` | flat history → 0.0 |

**Why /3 for macro.** The z_252 is a 252-day rolling z-score; |z| = 3
is a ~3-sigma event. Mapping full-scale at 3 keeps ordinary
fluctuations (|z| < 1) in the ±0.33 band — present but not decisive —
while genuine regime extremes saturate. Linear inside, flat outside:
beyond 3 sigma the indicator carries no *additional* information.

**Why /1.5 for breadth.** The breadth regime_score is itself a
z-composite with ±0.5 classification thresholds. Full scale at 1.5
puts the engines' own "official" boundary at one-third of the dial:
classification-grade evidence, not maximum conviction.

**Why the fragility drag.** A market can read NEUTRAL on participation
while concentration risk builds underneath. Subtracting half the
fragility gauge (∈ [0,1]) guarantees a maximally fragile market
scores ≤ +0.5. The drag is asymmetric by design — fragility only ever
pushes toward risk-off.

**Why percentile for vol.** Volatility has no natural scale (a 20%
VIX and a 60% VIX are different worlds); percentile over the trailing
window is self-calibrating. Linear in percentile — vol is already the
fastest input, so no extra curvature.

**Failure modes.** A stale z-score (engines not refreshed) looks like
conviction. Warm-up periods (z = None) fall back to half-scale
labels — weaker by design. Percentile vol needs a full window;
short histories understate extremes.

## 2. Weighted fusion (arbiter.py)

`score = Σ wᵢ·sᵢ / Σ wᵢ` over available signals; missing signals drop
out and weights renormalize. Default weights:

| Signal | Weight | Rationale |
|---|---|---|
| macro | 0.40 | Slowest, most fundamental; anchors the composite |
| breadth | 0.35 | Confirms/contradicts what price action claims |
| vol | 0.25 | Fastest, noisiest; cannot flip the arbiter alone |

All-missing fuses to **0.0** — no information is neutral, not
risk-off. Risk-off requires evidence; the absence of data must never
masquerade as a defensive signal (that would stand the book down
every time a feed hiccups).

**Failure mode.** Correlated signals double-count: in a crisis, macro,
breadth, and vol all scream together, and the weighted mean treats
them as independent witnesses. The composite saturates (fine), but
don't mistake "three signals agree" for "three independent reasons."

## 3. Conviction curve

`conviction = 100 × min(1, |score| / 0.8)`. Piecewise-linear,
monotone in |score|. Saturation at 0.8: reaching ±0.8 needs strong
cross-signal agreement (e.g. all three at ±0.8), so beyond that the
arbiter is already maximally convinced.

## 4. Hysteresis (Schmitt trigger)

From neutral: engage at |score| ≥ threshold + band (default 0.40).
From engaged: release at |score| ≤ threshold − band (default 0.10).
Violent reversals walk through neutral over two assessments.

**Why.** The dead zone (0.10–0.40) is where measurement noise lives.
Without hysteresis, a score oscillating 0.38/0.42 flips the stance
every other day and the book with it. The cost is delay: a true
regime change is recognized up to the dead-zone width late. In a
crash, the arbiter is late *and says so* — conviction is visible, so
downstream can see the hesitation instead of discovering it.

## 5. Sizing curves (sizing.py)

- `exposure_scale`: 0 below conviction 25; `0.2 + 0.8(c−25)/75`
  above. The 0.2 intercept makes re-entry tentative.
- Sleeve shutdown order: mean-reversion (dead < 40) → trend (linear
  taper, never binary) → short-vol (dead < 65). The order encodes
  *causal* fragility: ranges break first, trends persist, short vol
  is only paid in calm.
- `STAND_DOWN_FLOOR = 25`: below it, everything is 0. "I don't know"
  maps to flat.

## 6. Presets

| Preset | Engage | Release | Floor | Use |
|---|---|---|---|---|
| conservative | ±0.45 | ±0.15 | 35 | live capital, field-day autonomy |
| balanced | ±0.40 | ±0.10 | 25 | default research/paper |
| aggressive | ±0.30 | ±0.10 | 15 | research, high-conviction books |

Conservative also overweights macro (0.45) — slower signals, fewer
false alarms.
