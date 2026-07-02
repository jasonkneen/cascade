#!/usr/bin/env python3
"""Fleet efficiency report for cascade runs.

Reads the run ledger (JSONL appended by cascade_cost.py) and reports overall
efficiency: spend and savings vs baseline, token share by tier, unit
economics (cost per landed change), escalation/delegation rates with a
why-code histogram, average stage output vs the soft budgets, and a
recent-vs-all-time trend. If baseline-kind records exist (single-model
benchmark runs logged with `cascade_cost.py --kind baseline`), a crude
measured snowball/echo is derived from median volume ratios.

Usage:
  python cascade_stats.py [ledger] [--last N] [--repo SUBSTR] [--json]
Ledger default: $CASCADE_LOG or ~/.cascade/runs.jsonl
"""
import argparse
import json
import os
import statistics
import sys

try:  # die quietly when piped to head/less
    from signal import SIGPIPE, SIG_DFL, signal
    signal(SIGPIPE, SIG_DFL)
except ImportError:
    pass

LEDGER_ENV = "CASCADE_LOG"
LEDGER_DEFAULT = os.path.join(os.path.expanduser("~"), ".cascade", "runs.jsonl")
BUDGETS = {"F": 600, "O": 1200, "S": 400, "H": 200}  # soft out-token budgets
TIER_OF = {"fable": "F", "opus": "O", "sonnet": "S", "haiku": "H"}


def tier(model):
    for key, t in TIER_OF.items():
        if key in (model or ""):
            return t
    return "?"


def load(path):
    runs, bad = [], 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                runs.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    return runs, bad


def unit_econ(runs):
    spend = sum(r["totals"]["cost_usd"] for r in runs)
    items = sum(r.get("counters", {}).get("plan", 0) for r in runs)
    landed = sum(r.get("counters", {}).get("ok", 0) + r.get("counters", {}).get("adapt", 0)
                 for r in runs)
    esc = sum(sum((r.get("esc_why") or {}).values()) for r in runs)
    return spend, items, landed, esc


def main():
    ap = argparse.ArgumentParser(description="Overall efficiency across cascade runs.")
    ap.add_argument("ledger", nargs="?", default=None)
    ap.add_argument("--last", type=int, default=None, help="only the most recent N cascade runs")
    ap.add_argument("--repo", default=None, help="filter: repo name contains SUBSTR")
    ap.add_argument("--json", dest="as_json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    path = args.ledger or os.environ.get(LEDGER_ENV) or LEDGER_DEFAULT
    if not os.path.exists(path):
        sys.exit(f"no ledger at {path} — run cascade_cost.py on a usage.json first")
    records, bad = load(path)
    if args.repo:
        records = [r for r in records if args.repo in (r.get("repo") or "")]

    baselines = [r for r in records if r.get("kind") == "baseline"]
    runs = [r for r in records if r.get("kind", "cascade") == "cascade"]
    runs.sort(key=lambda r: r.get("ts") or "")
    if args.last:
        runs = runs[-args.last:]
    if not runs:
        sys.exit("no cascade runs match")

    spend, items, landed, esc = unit_econ(runs)
    floor = sum(r.get("savings", {}).get("floor_usd") or 0 for r in runs)
    modeled = sum(r.get("savings", {}).get("modeled_usd") or 0 for r in runs)
    tin = sum(r["totals"]["in"] for r in runs)
    tout = sum(r["totals"]["out"] for r in runs)

    by_tier = {}  # tier -> [in, out, cost]
    stage_out = {}  # tier -> list of out tokens (FOSH stage entries only)
    for r in runs:
        for s in r.get("per_stage") or []:
            t = s["label"] if s["label"] in BUDGETS else tier(s.get("model"))
            slot = by_tier.setdefault(t, [0, 0, 0.0])
            slot[0] += s.get("in", 0)
            slot[1] += s.get("out", 0)
            slot[2] += s.get("cost_usd", 0.0)
            if s["label"] in BUDGETS:
                stage_out.setdefault(s["label"], []).append(s.get("out", 0))

    why = {}
    for r in runs:
        for code, n in (r.get("esc_why") or {}).items():
            why[code] = why.get(code, 0) + n
    deleg = sum(r.get("counters", {}).get("deleg", 0) for r in runs)
    blk = sum(r.get("counters", {}).get("blk", 0) for r in runs)

    trend = None
    if len(runs) >= 4:
        recent = runs[-min(5, len(runs)):]
        rs, ri, rl, re = unit_econ(recent)
        trend = {
            "window": len(recent),
            "cost_per_landed": [round(spend / landed, 3) if landed else None,
                                round(rs / rl, 3) if rl else None],
            "esc_per_item": [round(esc / items, 3) if items else None,
                             round(re / ri, 3) if ri else None],
        }

    measured = None
    if baselines:
        b_in = statistics.median(b["totals"]["in"] for b in baselines)
        b_out = statistics.median(b["totals"]["out"] for b in baselines)
        c_in = statistics.median(r["totals"]["in"] for r in runs)
        c_out = statistics.median(r["totals"]["out"] for r in runs)
        if c_in and c_out:
            measured = {"snowball": round(b_in / c_in, 2), "echo": round(b_out / c_out, 2),
                        "baseline_runs": len(baselines),
                        "note": "crude — median volume ratio, not task-matched"}

    report = {
        "ledger": path, "skipped_lines": bad,
        "runs": len(runs), "repos": sorted({r.get("repo") or "?" for r in runs}),
        "span": [runs[0].get("ts"), runs[-1].get("ts")],
        "spend_usd": round(spend, 2),
        "baseline_floor_usd": round(floor, 2),
        "baseline_modeled_usd": round(modeled, 2),
        "savings_floor_x": round(floor / spend, 2) if spend else None,
        "savings_modeled_x": round(modeled / spend, 2) if spend else None,
        "tokens": {"in": tin, "out": tout},
        "by_tier": {t: {"in": v[0], "out": v[1], "cost_usd": round(v[2], 2),
                        "cost_share": round(v[2] / spend, 2) if spend else None}
                    for t, v in sorted(by_tier.items(), key=lambda kv: "FOSH?".find(kv[0]))},
        "unit_economics": {
            "plan_items": items, "landed": landed, "blocked": blk,
            "landed_rate": round(landed / items, 2) if items else None,
            "cost_per_landed_usd": round(spend / landed, 3) if landed else None,
            "tokens_per_landed": round((tin + tout) / landed) if landed else None,
        },
        "escalations": {"total": esc,
                        "per_item": round(esc / items, 3) if items else None,
                        "why": dict(sorted(why.items(), key=lambda kv: -kv[1]))},
        "delegated_items": deleg,
        "avg_stage_out_vs_budget": {
            t: {"avg_out": round(statistics.mean(v)), "soft_budget": BUDGETS[t]}
            for t, v in sorted(stage_out.items(), key=lambda kv: "FOSH".find(kv[0]))},
        "trend_all_vs_recent": trend,
        "measured_multipliers": measured,
    }

    if args.as_json:
        print(json.dumps(report, indent=2))
        return

    u = report["unit_economics"]
    print(f"cascade fleet — {report['runs']} runs, {len(report['repos'])} repo(s), "
          f"{report['span'][0]} .. {report['span'][1]}")
    print(f"spend ${report['spend_usd']:.2f} | baseline floor ${report['baseline_floor_usd']:.2f} "
          f"({report['savings_floor_x']}x) | modeled ${report['baseline_modeled_usd']:.2f} "
          f"({report['savings_modeled_x']}x)")
    print(f"tokens in {tin:,} / out {tout:,}")
    for t, v in report["by_tier"].items():
        print(f"  {t}: in {v['in']:>10,}  out {v['out']:>7,}  ${v['cost_usd']:<7.2f} "
              f"({int((v['cost_share'] or 0) * 100)}% of spend)")
    print(f"unit economics: {u['plan_items']} plan items, {u['landed']} landed "
          f"({int((u['landed_rate'] or 0) * 100)}%), {u['blocked']} blocked | "
          f"${u['cost_per_landed_usd']}/landed, {u['tokens_per_landed']:,} tok/landed")
    e = report["escalations"]
    why_s = ", ".join(f"{k} {v}" for k, v in e["why"].items()) or "none"
    print(f"escalations: {e['total']} ({e['per_item']}/item) — {why_s}; delegated: {deleg}")
    budg = "  ".join(f"{t} {v['avg_out']}/{v['soft_budget']}"
                     for t, v in report["avg_stage_out_vs_budget"].items())
    print(f"avg stage out vs soft budget: {budg}")
    if trend:
        print(f"trend (all -> last {trend['window']}): cost/landed "
              f"${trend['cost_per_landed'][0]} -> ${trend['cost_per_landed'][1]}, "
              f"esc/item {trend['esc_per_item'][0]} -> {trend['esc_per_item'][1]}")
    if measured:
        print(f"measured multipliers from {measured['baseline_runs']} baseline run(s): "
              f"snowball x{measured['snowball']}, echo x{measured['echo']} ({measured['note']})")
    if bad:
        print(f"note: skipped {bad} malformed ledger line(s)")


if __name__ == "__main__":
    main()
