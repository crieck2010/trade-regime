# METHODOLOGY

Every formula in trade-regime, its rationale, and its failure modes.

## 1. Component transforms (signals.py)

Each engine snapshot becomes a sub-conviction in [0, 100]
(100 = full risk-on) via a documented, inspectable formula.  Readers
never raise: bad input becomes `ComponentUnavailable(name, reason)`.

### 1.1 trade-breadth → breadth

```
sub = clamp(base(regime) − 50·fragility + 10·thrust − 10·divergence, 0, 100)
base: BROADENING 75 / NEUTRAL 50 / NARROWING 25
```

- Regime labels are coarse, so they sit at quarter-points.  Extremes
  must be *earned* by the continuous adjustments below.
- `fragility` ∈ [0, 1] (clamped): concentration-risk drag, asymmetric
  by design — it only ever pushes toward risk-off.  A maximally
  fragile market scores at most 50 before thrust adjustments.
- `thrusts` truthy (Zweig-style breadth thrust): +10.  Thrusts are
  rare and powerful; the bonus is capped so one event cannot flip the
  component alone.
- `divergence_warning` truthy: −10.

Failure modes: a stale breadth snapshot (yesterday's fragility)
silently understates concentration risk.  The arbiter cannot detect
staleness — feed it fresh snapshots.

### 1.2 trade-macro → macro

```
sub = clamp(base(regime) + 10·clamp(z/2, −1, 1) ± 5·alerts, 0, 100)
base: EXPANSION 75 / NEUTRAL 50 / CONTRACTION 25
```

- `z_score` (copper/gold 252d z): ±10 points at |z| = 2, linear
  inside, saturating outside.  A 2-sigma deviation is a strong regime
  read; beyond that the indicator is already screaming and extra
  z carries no extra information.
- `transition_alerts` (list of strings): a fresh CONTRACTION alert
  −5, a fresh EXPANSION alert +5.  Small on purpose — alerts are
  discrete events, not continuous evidence.

Failure modes: copper/gold is a *slow* indicator.  In a fast crash the
macro component is the last to know; that is why it anchors the
weights rather than leading them.

### 1.3 trade-volforecast → vol

```
pct     = (current − min) / (max − min)          # trailing window level
f_pct   = (forecast − min) / (max − min)         # GARCH/HAR forward read
stress  = 0.6·pct + 0.4·f_pct
stress += 0.15  if forecast > 1.25·current       # accelerating
stress += 0.10  if vol_of_vol > 0.5              # unstable vol regime
sub     = 100·(1 − stress)
```

- Inverted: high vol is risk-off *pressure*, so the sub-conviction is
  `1 − stress`.
- The forecast gets 40% because vol mean-reverts — the forward read
  tempers the spot read instead of amplifying it.
- `forecast_vol` is optional: without it, `stress = pct`.
- Flat history (max == min): percentile undefined → 0.5 (no
  dispersion, no information → neutral).

Failure modes: vol-stress lags by construction (trailing window +
forecast).  In a gap-driven crash the vol component reacts a day
late; the confirm-band path in the hysteresis exists partly for this.

## 2. Weighted fusion (arbiter.py)

```
composite = Σ wᵢ·subᵢ / Σ wᵢ        over available components only
```

- Unavailable components are dropped; remaining weights renormalize.
  Every missing name is listed in `missing` — silent re-weighting
  would be a lie.
- All-missing → 50.0.  No information is neutral, not risk-off;
  risk-off requires *evidence*.
- Default weights macro 0.40 / breadth 0.35 / vol 0.25: the slowest,
  most fundamental read anchors; the fastest, noisiest read can temper
  but never flip the composite alone.

## 3. Hysteresis on conviction (arbiter.py)

Let `r` be the raw composite, `c` the held conviction (balanced
preset values; presets change the numbers, not the mechanism):

| condition | action | reason |
|---|---|---|
| `\|r − c\| ≤ 10` | hold | within deadband |
| `\|r − c\| > 20` | update now | large move beyond confirm band |
| `10 < \|r − c\| ≤ 20`, same direction × 3 obs | update | persistent move beyond band edge |
| `10 < \|r − c\| ≤ 20`, otherwise | hold | awaiting persistence (k/3) |

- A direction flip restarts the persistence count: alternating noise
  around the band edge *never* releases, by construction.
- Every release is rate-limited: `|Δc| ≤ 25` per assessment.
  Conviction walks; it never teleports.
- First assessment: `c = r` ("initialization") — there is no prior to
  hold.

Why hysteresis instead of smoothing (e.g. EWMA)?  Smoothing *lags
everything equally* and still moves on noise, just less.  Hysteresis
*moves on evidence*: it ignores confirmed noise entirely and reacts
fully (rate-limited) to confirmed breaks.  For a sizing input, the
difference between "jittered a little every day" and "did not move
for a week, then stepped" is the difference between churn and intent.

## 4. Presets (presets.py)

| preset | weights (m/b/v) | deadband | confirm | persist | max Δ |
|---|---|---|---|---|---|
| balanced | 0.40/0.35/0.25 | ±10 | ±20 | 3 | 25 |
| conservative | 0.50/0.30/0.20 | ±15 | ±30 | 4 | 15 |
| aggressive | 0.30/0.40/0.30 | ±7 | ±14 | 2 | 40 |

- **conservative**: overweights the slowest signal, widest bands,
  slowest moves.  For live capital.  Price: last to know in a real
  break.
- **aggressive**: breadth (fastest *fundamental* read) leads, tight
  bands.  For research.  Price: whipsaws in chop.
- All numbers are policy, not science.  The rationale for each is in
  `presets.py` and printed by `trade-regime presets`.

## 5. Exposure scale

`exposure_scale = conviction / 100`, linear.  Deliberately dumb: the
arbiter *suggests*, **trade-risk owns final sizing**.  Floors, curves,
and stand-down rules belong downstream where position-level
constraints live.

## 6. Extension slot: adding a fourth component

1. Write a reader: `def my_reader(snapshot: dict) -> Component |
   ComponentUnavailable` (any 0–100 transform; document it like §1).
2. Pass it at read time — no core changes:
   `read_all(macro, breadth, vol, extra={"sentiment": (snap, my_reader)})`
3. Give it a weight: `RegimeArbiter(weights={"macro": .35, "breadth": .3,
   "vol": .2, "sentiment": .15}, preset_name="custom+sentiment")`.
4. The snapshot's `components` section carries it automatically;
   adapters forward it untouched.

## 7. Known failure modes (summary)

- Garbage engine input → garbage conviction.  The arbiter refuses to
  *move* on bad input; it cannot refuse to *be wrong* about good input
  that is stale.
- Hysteresis delays true regime changes (deadband + persistence lag).
  In a crash, the arbiter is late and says so.
- Daily inputs → intraday conviction is stale.  Do not run this on
  minute bars.
- Weights/bands are judgment.  Validate them against *your* book's
  turnover and drawdown tolerance before trusting them.
