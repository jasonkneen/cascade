#!/usr/bin/env python3
"""Cost report for a cascade run.

Reads cascade/usage.json, prices each stage/escalation against the tier
rate card, and computes savings vs a single-model baseline two ways:

  floor   - this exact token volume repriced at the baseline model.
            Fact-grade: no counterfactual assumptions, pure tier arbitrage.
  modeled - floor volume scaled by snowball (input) and echo (output)
            multipliers approximating a real single-session run.
            Estimate-grade: multipliers are printed with the result.

Entries may carry exact input_tokens/output_tokens (API mode - prefer) or
total_tokens + out_reported (Claude Code notifications expose only totals;
output comes from the stage's DONE tok~= and input is derived as total-out).

Update RATES alongside the tier map in SKILL.md. Verified 2026-07-02.
Stdlib only. Usage:
  python cascade_cost.py cascade/usage.json [--baseline MODEL] [--rates rates.json]
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys

LEDGER_ENV = "CASCADE_LOG"
LEDGER_DEFAULT = os.path.join(os.path.expanduser("~"), ".cascade", "runs.jsonl")

try:  # die quietly when piped to head/less
    from signal import SIGPIPE, SIG_DFL, signal
    signal(SIGPIPE, SIG_DFL)
except ImportError:
    pass

SONNET_INTRO_ENDS = dt.date(2026, 8, 31)


def rate_card(today=None):
    today = today or dt.date.today()
    sonnet = (2.0, 10.0) if today <= SONNET_INTRO_ENDS else (3.0, 15.0)
    return {
        "claude-fable-5": (10.0, 50.0),
        "claude-opus-4-8": (5.0, 25.0),
        "claude-sonnet-5": sonnet,
        "claude-haiku-4-5": (1.0, 5.0),
    }


def split_tokens(entry):
    """Return (input_tokens, output_tokens, grade)."""
    i, o = entry.get("input_tokens"), entry.get("output_tokens")
    if i is not None and o is not None:
        return int(i), int(o), "exact"
    total = int(entry.get("total_tokens") or 0)
    out = int(entry.get("out_reported") or 0)
    return max(total - out, 0), out, "derived"


def cost(i, o, rate):
    return i / 1e6 * rate[0] + o / 1e6 * rate[1]


def repo_name():
    for cmd in (["git", "remote", "get-url", "origin"],
                ["git", "rev-parse", "--show-toplevel"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if out.returncode == 0 and out.stdout.strip():
                name = out.stdout.strip().rstrip("/").split("/")[-1]
                return name[:-4] if name.endswith(".git") else name
        except Exception:
            pass
    return os.path.basename(os.getcwd())


def sum_counters(*entry_lists):
    agg = {}
    for e in (e for lst in entry_lists for e in lst):
        for k, v in (e.get("counters") or {}).items():
            try:
                agg[k] = agg.get(k, 0) + int(v)
            except (TypeError, ValueError):
                pass
    return agg


def main():
    ap = argparse.ArgumentParser(
        description="Price a cascade run and report savings vs a baseline."
    )
    ap.add_argument("usage", help="path to cascade/usage.json")
    ap.add_argument("--baseline", default=None,
                    help="baseline model id (default: usage.json baseline_model, else claude-opus-4-8)")
    ap.add_argument("--rates", default=None,
                    help="JSON file {model: [in,out]} merged over the built-in card")
    ap.add_argument("--kind", default="cascade", choices=["cascade", "baseline"],
                    help="ledger record kind; 'baseline' marks a single-model benchmark run")
    ap.add_argument("--log-path", default=None,
                    help=f"ledger file (default: ${LEDGER_ENV} or {LEDGER_DEFAULT})")
    ap.add_argument("--no-log", dest="log", action="store_false",
                    help="skip appending this run to the ledger")
    args = ap.parse_args()

    card = rate_card()
    if args.rates:
        with open(args.rates) as f:
            card.update({k: tuple(v) for k, v in json.load(f).items()})

    with open(args.usage) as f:
        data = json.load(f)

    baseline = args.baseline or data.get("baseline_model") or "claude-opus-4-8"
    if baseline not in card:
        sys.exit(f"unknown baseline {baseline!r}; known: {', '.join(sorted(card))} (or pass --rates)")

    assume = data.get("assumptions") or {}
    snowball = float(assume.get("snowball", 2.3))
    echo = float(assume.get("echo", 1.6))

    entries = list(data.get("stages") or []) + list(data.get("escalations") or [])
    if not entries:
        sys.exit("usage.json has no stages/escalations to price")

    rows, tin, tout, tcost, derived = [], 0, 0, 0.0, False
    for e in entries:
        model = e.get("model")
        if not model:
            sys.exit(f"entry missing 'model': {e}")
        if model not in card:
            sys.exit(f"unknown model {model!r}; known: {', '.join(sorted(card))} (or pass --rates)")
        i, o, grade = split_tokens(e)
        derived = derived or grade == "derived"
        c = cost(i, o, card[model])
        label = e.get("stage") or f"ESC {e.get('id', '?')}"
        rows.append((label, model, i, o, grade, c))
        tin, tout, tcost = tin + i, tout + o, tcost + c

    floor = cost(tin, tout, card[baseline])
    modeled = cost(int(tin * snowball), int(tout * echo), card[baseline])

    w = max([len(r[0]) for r in rows] + [len("cascade total")]) + 2
    print(f"{'stage':<{w}}{'model':<18}{'in_tok':>10}{'out_tok':>9}  src      cost")
    for label, model, i, o, grade, c in rows:
        print(f"{label:<{w}}{model:<18}{i:>10,}{o:>9,}  {grade:<8} ${c:.3f}")
    print(f"{'cascade total':<{w}}{'':<18}{tin:>10,}{tout:>9,}  {'':<8} ${tcost:.3f}")
    print()
    print(f"baseline {baseline} (in ${card[baseline][0]}/MTok, out ${card[baseline][1]}/MTok):")
    print(f"  floor   (reprice, same volume)              ${floor:.3f}"
          f"   {floor / tcost:.2f}x" if tcost else "")
    print(f"  modeled (snowball x{snowball}, echo x{echo})        ${modeled:.3f}"
          f"   {modeled / tcost:.2f}x" if tcost else "")
    if derived:
        print("  note: some splits derived from total_tokens - out_reported (Claude Code mode);"
              " API-mode exact splits are better data")

    data["computed"] = {
        "priced_at": dt.date.today().isoformat(),
        "rates": {m: list(r) for m, r in card.items()},
        "per_entry": [
            {"label": l, "model": m, "input_tokens": i, "output_tokens": o,
             "split": g, "cost_usd": round(c, 4)}
            for l, m, i, o, g, c in rows
        ],
        "totals": {"input_tokens": tin, "output_tokens": tout, "cost_usd": round(tcost, 4)},
        "baseline": {
            "model": baseline,
            "floor_usd": round(floor, 4),
            "modeled_usd": round(modeled, 4),
            "savings_floor_x": round(floor / tcost, 2) if tcost else None,
            "savings_modeled_x": round(modeled / tcost, 2) if tcost else None,
            "assumptions": {"snowball": snowball, "echo": echo},
        },
    }
    with open(args.usage, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\ncomputed block written back to {args.usage}")

    if args.log:
        path = args.log_path or os.environ.get(LEDGER_ENV) or LEDGER_DEFAULT
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        esc_why = {}
        for e in data.get("escalations") or []:
            code = e.get("why") or "?"
            esc_why[code] = esc_why.get(code, 0) + 1
        duration = sum(int(e.get("duration_ms") or 0) for e in entries)
        rec = {
            "ts": data.get("ts") or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "kind": args.kind,
            "repo": repo_name(),
            "task": (data.get("task") or "")[:120],
            "baseline_model": baseline,
            "per_stage": [
                {"label": l, "model": m, "in": i, "out": o, "cost_usd": round(c, 4)}
                for l, m, i, o, g, c in rows
            ],
            "totals": {"in": tin, "out": tout, "cost_usd": round(tcost, 4)},
            "counters": sum_counters(data.get("stages") or [], data.get("escalations") or []),
            "esc_why": esc_why,
            "duration_ms": duration or None,
            "savings": data["computed"]["baseline"],
        }
        with open(path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        runs = []
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("kind", "cascade") == "cascade":
                        runs.append(r)
                except json.JSONDecodeError:
                    pass
        spend = sum(r["totals"]["cost_usd"] for r in runs)
        modeled = sum(r.get("savings", {}).get("modeled_usd") or 0 for r in runs)
        landed = sum(r.get("counters", {}).get("ok", 0) + r.get("counters", {}).get("adapt", 0)
                     + r.get("counters", {}).get("took", 0)
                     for r in runs)
        summary = f"logged {args.kind} run -> {path} | lifetime ({len(runs)} cascade runs): ${spend:.2f} spend"
        if spend and modeled:
            summary += f", modeled baseline ${modeled:.2f} ({modeled / spend:.2f}x)"
        if landed:
            summary += f", ${spend / landed:.3f}/landed change"
        print(summary)


if __name__ == "__main__":
    main()
