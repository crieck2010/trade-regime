# DECISION LOOP

The supervised/autonomous trading loop that trade-regime enables.
This is a specification for how the suite's pieces fit — not all
pieces are built yet.

## The loop

```
each cycle (e.g. 3x daily, or every N minutes intraday):
  1. engines refresh snapshots (macro, breadth, vol, ...)
  2. arbiter.assess(signals) -> RegimeState {score, conviction, stance}
  3. adapters.pm_context(state) -> merged into trade-agents market_context
  4. PM agent proposes allocations, scaled by sleeve_scales(conviction)
  5. adapters.risk_caps(state) -> trade-risk validates / tightens
  6. IF stand_down or defensive flip:
       adapters.hedge_trigger(state) -> trade-hedge proposes overlays
  7. orders -> approval queue (supervised) or execution (autonomous)
  8. fills -> trade-paper ledger; state -> RegimeHistory
```

## The mode switch (planned)

One configuration value, `mode: supervised | autonomous`, owned by
the future orchestration layer (not this repo):

- **supervised** (now): step 7 routes every order through the human
  approval queue. The human is the decision layer; the arbiter is
  an advisor.
- **autonomous** (later): step 7 executes within standing guardrails —
  daily loss limit, per-position caps, regime stand-down, and the
  arbiter's sleeve scales as hard multipliers. The human moves to
  oversight: kill switch + daily digest.

Designing the switch now matters because the *interfaces* must not
change later: `pm_context`, `risk_caps`, and `hedge_trigger` are the
same dicts in both modes. Only the consumer of step 7 changes. This
repo is written so that transition is a config flip, not a rewrite.

## Guardrails for autonomous mode (requirements, not implementation)

1. **Daily loss limit** — halt new risk at −X% day; arbiter cannot
   override.
2. **Per-position caps** — from `risk_caps`, scaled by conviction.
3. **Regime stand-down** — conviction < floor → flat; no discretion.
4. **Kill switch** — human-initiated, phone-accessible, halts the
   loop in one action.
5. **Daily digest** — every autonomous session ends with a
   human-readable summary (stances, transitions, fills, P&L).

## What the arbiter does NOT do

- It does not generate trade ideas (that's trade-agents).
- It does not set absolute risk limits (that's trade-risk; the
  arbiter only tightens them by regime).
- It does not execute or approve anything.
- Its labels are display-only. Any downstream component found
  branching on `stance_label` instead of `score`/`conviction` is
  misusing the contract.
