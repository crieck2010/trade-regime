# Session component (`trade_regime.session`)

The arbiter fuses *market-risk* reads (macro, breadth, vol) but had no
notion of *when* a read was taken: a 3am equity assessment could still
size at ×0.75 because nothing in the composite knew the session was
dead.  The session component is a fourth, graded 0–100 sub-conviction
measuring **session liquidity** — wired through the documented
`extra` extension slot, with no core arbiter changes.

## The model

`session_component(snapshot)` reads a plain-data snapshot:

```python
{"now": <aware datetime | ISO-8601 str | None>,   # None = right now
 "asset_class": "equities" | "futures" | "crypto", # default "equities"
 "calendar": {"holidays": ["2026-07-03", ...]} | None}
```

and returns `Component("session", sub_conviction, detail)` — or
`ComponentUnavailable` on bad input (never raises; `fuse()` then
renormalizes over the remaining components, which is the graceful
degradation path).

Convenience wrappers:

```python
from trade_regime.session import read_session, session_extra, session_weights
from trade_regime import read_all, RegimeArbiter

# one-liner for the extra slot
comps = read_all(macro, breadth, vol,
                 extra=session_extra(now=None, asset_class="equities"))
arbiter = RegimeArbiter(weights=session_weights())  # macro .34 / breadth .2975 / vol .2125 / session .15
snap = arbiter.assess(comps)
```

`read_session(now, asset_class, calendar)` is the same reader without
the `extra` envelope; `session_extra(...)` builds the
`{"session": (snapshot, reader)}` mapping `read_all()` expects.

## Anchor tables (the maths)

Values are piecewise-linear in minutes-since-midnight ET.  Adjacent
anchors share endpoints, so the curve has kinks (slope changes) but
**no step discontinuities** — the 9:29 → 9:30 → 9:45 walk is smooth
by construction (9:29 scores ≈ 99.8, 9:30 scores 100).

**US equities** (`America/New_York`):

| ET window | value | reading |
|---|---|---:|
| 21:00 – 03:00 | 10 | deep overnight — the session itself is the risk |
| 03:00 – 04:00 | 10 → 30 | ramp into pre-market |
| 04:00 – 09:30 | 30 → 100 | pre-market grades up |
| 09:30 – 16:00 | 100 | regular session — neutral, defers to market-risk components |
| 16:00 – 20:00 | 100 → 30 | after-hours grades down |
| 20:00 – 21:00 | 30 → 10 | ramp into the deep overnight |
| Sat / Sun, NYSE holidays | 5 | venue closed — effectively stand-down for equities |

**Futures** (CME-style equity-index proxy — a defensible
simplification, not a venue spec): 09:30–16:00 ET scores 100 (cash
overlap); overnight electronic 18:00–09:30 scores 70 (trades, but
thinner and news-driven); the 17:00–18:00 ET daily trading halt ramps
100 → 25 → 70; weekends score 5 (closed).

**Crypto**: 100 always — no session concept.

## Fusion weight (the maths)

`session_weights()` rebalances pro-rata:

```
w_i' = w_i · (1 − 0.15)      for macro / breadth / vol
w_session = 0.15
```

Default: macro 0.34, breadth 0.2975, vol 0.2125, session 0.15.  The
relative voice of the three market-risk components is unchanged — the
session component buys its weight from all three equally instead of
demoting any one of them.

Bounded influence, by construction:

```
max session drag = 0.15 × (100 − 5) = 14.25 conviction points   (weekend)
typical overnight  = 0.15 × (100 − 10) = 13.5 points            (3am)
```

14.25 < 20 (the confirm band): **the session component alone can
never trigger an immediate conviction move.**  It must persist for 3
consecutive observations or combine with market-risk moves.  This is
deliberate — the session input tempers; it does not veto.  A hard
session veto (never trade at 3am, full stop) belongs downstream in
desk scheduling / trade-risk limits, not in the arbiter.

Honest consequence: a *single* 3am assessment against a held
conviction of 75 moves the raw composite to ≈ 65.3 — inside the
±10 deadband — so conviction **holds**.  The 3am failure mode is
caught when the drag persists (or when the arbiter initializes
overnight, where the raw composite is taken as-is).  Hysteresis still
governs conviction; the session component only guarantees the *raw*
composite reflects session liquidity.

## Timezone policy

- Session boundaries are defined in `America/New_York` (`SESSION_TZ`).
- Aware datetimes are converted; naive datetimes are **assumed UTC**
  and the assumption is recorded loudly in `detail["tz_assumption"]`
  — never silently.
- `now=None` reads the current UTC clock.

## Holiday policy

- Built-in table: NYSE holidays **2026–2027 only**, verified against
  weekday calendars (see `session.py`).  A holiday scores like a
  weekend (5.0) for equities.
- **Explicit limitations** (documented, not silently "handled"):
  - Years outside 2026–2027: holidays are *not* in the table — a
    holiday in an uncovered year scores as a normal weekday.
  - Early closes (day after Thanksgiving, Christmas Eve, …) are
    treated as full sessions.
  - The table covers equities; futures keep their anchor curve on
    NYSE holidays (CME equity futures generally still trade).
- The seam: pass `calendar={"holidays": ["YYYY-MM-DD", ...]}` to
  inject any calendar — the intended path to a full exchange-calendar
  dependency later.

## Interop

- **trade-regime (this repo)** owns the component: snapshot shape,
  anchor tables, holiday table, `session_weights()`.
- **trade-agents** needs no changes: it consumes
  `conviction → exposure_scale` from the fused snapshot, and the
  session drag flows through that number automatically.  See
  `docs/INTEROP.md`.
- **trade-risk** untouched by design: sizing vetoes stay downstream;
  the arbiter remains advisory.

## Failure modes

- Wrong clock, wrong answer: the component trusts the caller's `now`.
  Backtests must pass bar timestamps, not wall-clock time.
- A daily 8am ET desk run reads pre-market (≈ 81), not the regular
  session — schedule assessments at the session you actually trade,
  or accept the tempering.
- The futures mapping is a proxy; single-stock futures, commodities,
  and FX have different halt structures — use `asset_class="crypto"`
  (neutral 100) rather than a wrong mapping, or extend the anchors.
