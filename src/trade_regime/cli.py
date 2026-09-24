"""Command-line interface for trade-regime."""

from __future__ import annotations

import argparse
import json

from . import __version__
from .adapters import assess_live, hedge_trigger, pm_context, risk_caps
from .arbiter import RegimeArbiter
from .demo import demo_signals, run_demo, timeline
from .history import RegimeHistory
from .licensing import check_license, check_update
from .presets import PRESETS, get_preset
from .signals import Signal, read_all
from .sizing import sleeve_scales


def _fmt_state(state: dict) -> str:
    labels = {-1: "DEFENSIVE", 0: "NEUTRAL", 1: "CONSTRUCTIVE"}
    lines = [
        f"score      {state['score']:+.3f}",
        f"conviction {state['conviction']:.1f}%",
        f"stance     {labels[state['stance']]} (was {labels[state['prev_stance']]})"
        + ("  TRANSITION" if state["transition"] else ""),
        f"signals    {state['n_signals']} used" +
        (f"; missing: {', '.join(state['missing'])}" if state["missing"] else ""),
    ]
    for name, c in state["contributions"].items():
        lines.append(f"  {name:8s} score {c['score']:+.3f} x weight {c['weight']:.2f} "
                     f"= {c['contribution']:+.3f}")
    return "\n".join(lines)


def cmd_assess(args: argparse.Namespace) -> int:
    if args.live:
        state, notes = assess_live(seed=args.seed, preset=args.preset)
        if args.format == "json":
            print(json.dumps({"state": state, "notes": notes}, indent=2))
        else:
            print(_fmt_state(state))
            print(f"engines: {notes['engines']}")
        return 0
    signals = None
    if args.signals:
        with open(args.signals, encoding="utf-8") as fh:
            raw = json.load(fh)
        signals = read_all(raw.get("macro"), raw.get("breadth"), raw.get("vol"))
    else:  # latest demo day
        signals = demo_signals(seed=args.seed)[-1]
    arbiter = RegimeArbiter(**_arbiter_kw(args))
    state = arbiter.assess(signals)
    if args.format == "json":
        print(json.dumps(state, indent=2))
    else:
        print(_fmt_state(state))
        print("\npm_context (trade-agents hook):")
        print(json.dumps(pm_context(state), indent=2))
        trig = hedge_trigger(state)
        if trig:
            print("\nhedge_trigger FIRED:")
            print(json.dumps(trig, indent=2))
    return 0


def _arbiter_kw(args: argparse.Namespace) -> dict:
    if args.preset:
        p = get_preset(args.preset)
        kw = {"weights": p["weights"], "threshold": p["threshold"], "band": p["band"]}
    else:
        kw = {}
    if args.weights:
        w = {}
        for pair in args.weights.split(","):
            name, val = pair.split("=")
            w[name.strip()] = float(val)
        kw["weights"] = w
    return kw


def cmd_history(args: argparse.Namespace) -> int:
    demo = run_demo(seed=args.seed, preset=args.preset or "balanced")
    history = RegimeHistory()
    for r in demo["records"]:
        history.record(r)
    rows = history.transitions() if args.transitions_only else history.records[:: args.stride]
    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        labels = {-1: "DEF", 0: "NEU", 1: "CON"}
        for r in rows:
            print(f"day {r['seq']:3d}  {r['score']:+.2f}  {r['conviction']:5.1f}%  "
                  f"{labels[r['prev_stance']]}->{labels[r['stance']]}"
                  + ("  TRANSITION" if r["transition"] else ""))
    return 0


def cmd_weights(args: argparse.Namespace) -> int:
    if args.validate:
        w = {}
        for pair in args.validate.split(","):
            name, val = pair.split("=")
            w[name.strip()] = float(val)
        from .arbiter import validate_weights
        clean = validate_weights(w)
        print("valid:", json.dumps(clean))
        return 0
    print(json.dumps(PRESETS, indent=2))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    demo = run_demo(seed=args.seed, preset=args.preset or "balanced")
    print(f"trade-regime demo  seed={demo['seed']}  preset={demo['preset']}  "
          f"{demo['n_days']} days")
    print(f"transitions: {demo['n_transitions']}  "
          f"stand-down days: {len(demo['stand_down_days'])}")
    print()
    for line in timeline(demo, stride=args.stride):
        print(line)
    final = demo["final"]
    print()
    print("final state:")
    print(_fmt_state(final))
    print("\nsizing at final conviction:")
    print(json.dumps(sleeve_scales(final["conviction"]), indent=2))
    print("\nrisk_caps:")
    print(json.dumps(risk_caps(final), indent=2))
    return 0


def cmd_presets(args: argparse.Namespace) -> int:
    for name, p in PRESETS.items():
        w = ",".join(f"{k}={v}" for k, v in p["weights"].items())
        print(f"{name:12s} weights({w}) threshold={p['threshold']} "
              f"band={p['band']} floor={p['stand_down_floor']}")
        print(f"             {p['description']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trade-regime",
                                description="Regime arbiter: fuse engine signals "
                                            "into graded conviction.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("assess", help="assess one signal set")
    a.add_argument("--demo", action="store_true",
                   help="use the seeded demo's latest day (default)")
    a.add_argument("--live", action="store_true",
                   help="assess from installed engines' demo snapshots (fail-soft)")
    a.add_argument("--signals", help="JSON file with macro/breadth/vol snapshots")
    a.add_argument("--seed", type=int, default=7)
    a.add_argument("--preset", choices=sorted(PRESETS))
    a.add_argument("--weights", help="e.g. macro=0.5,breadth=0.3,vol=0.2")
    a.add_argument("--format", choices=("table", "json"), default="table")
    a.set_defaults(func=cmd_assess)

    h = sub.add_parser("history", help="replay the seeded demo history")
    h.add_argument("--seed", type=int, default=7)
    h.add_argument("--preset", choices=sorted(PRESETS))
    h.add_argument("--stride", type=int, default=10)
    h.add_argument("--transitions-only", action="store_true")
    h.add_argument("--format", choices=("table", "json"), default="table")
    h.set_defaults(func=cmd_history)

    w = sub.add_parser("weights", help="show presets or validate a weight map")
    w.add_argument("--validate", help="e.g. macro=0.5,breadth=0.3,vol=0.2")
    w.set_defaults(func=cmd_weights)

    d = sub.add_parser("demo", help="run the planted-shift demonstration")
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--preset", choices=sorted(PRESETS))
    d.add_argument("--stride", type=int, default=25)
    d.set_defaults(func=cmd_demo)

    pr = sub.add_parser("presets", help="list arbiter presets")
    pr.set_defaults(func=cmd_presets)

    li = sub.add_parser("license", help="check license key")
    li.add_argument("--key")
    li.set_defaults(func=lambda a: (print(json.dumps(check_license(a.key), indent=2)), 0)[1])

    up = sub.add_parser("update-check", help="check for a newer release")
    up.set_defaults(func=lambda a: (print(json.dumps(check_update(), indent=2)), 0)[1])

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
