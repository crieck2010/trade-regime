# DECISION LOOP

The supervised/autonomous trading loop that trade-regime enables.
This is a specification for how the suite's pieces fit — not all
pieces are built yet.

## The loop

```
each decision cycle (e.g. 3x daily, before the paper-trading run):
  1. engines  -> snapshots (trade-macro, trade-breadth, trade-volforecast)
  2. arbiter  -> conviction 0-100 (hysteresis-smoothed), exposure_scale advisory
  3. agents   -> market_context_provider(snapshot) merged into PM context;
                 researchers propose, debate runs, PM decides
  4. risk     -> risk_regime_input(snapshot) as one advisory voice among
                 mandate caps, drawdown guards, per-name limits
  5. hedge    -> hedge_tilt_input(snapshot): defensive/aggressive tilt
                 suggestion; hedge desk proposes overlays (never executes)
  6. paper    -> orders flow through the approval queue; user is the gate
```

## Conviction's role at each step

- **Agents (step 3):** conviction is *context*, not a command.  The PM
  may threshold it (e.g. "no new ideas below 30") but the number
  itself carries no buckets — any threshold is the consumer's policy,
  stated in the consumer's config, not the arbiter's.
- **Risk (step 4):** `exposure_scale` is advisory.  trade-risk owns
  final sizing and may override, floor, or ignore it.  The arbiter does
  not know position-level constraints, liquidity, or mandate limits.
- **Hedge (step 5):** the tilt is direction + magnitude only.
  trade-hedge proposes; execution stays behind the user approval gate.

## Supervised vs autonomous

- **Supervised (now):** every order needs user approval (trade-paper
  approval queue).  Conviction informs, never authorizes.
- **Autonomous (future, explicit rule change required):** conviction
  could gate autonomous sizing bands — but the kill switch (stale
  data, drawdown breach) must stay outside the arbiter, in trade-hedge
  / trade-risk, where it cannot be smoothed away by hysteresis.

## What the arbiter must never do

- Never label the market (no buckets, no stance names).
- Never set a final position size.
- Never place, approve, or veto an order.
- Never be the kill switch — hysteresis is the wrong mechanism for
  emergencies; emergencies need thresholds, not memory.
