# Cascade economics — cost model and measurement

Everything here is a model until a run measures it. The `tok~=` counters, `cascade/usage.json`, and `scripts/cascade_cost.py` exist to replace these estimates with actuals — trust a measured run over this page.

## Rate card ($/MTok, verified 2026-07-02 — update alongside the tier map in SKILL.md)

| Tier | Model | Input | Output |
|---|---|---|---|
| F | claude-fable-5 | 10 | 50 |
| O | claude-opus-4-8 | 5 | 25 |
| S | claude-sonnet-5 | 2 intro → 3 after 2026-08-31 | 10 intro → 15 |
| H | claude-haiku-4-5 | 1 | 5 |

Cache hits price at ~10% of the input rate; batch halves both. One erosion factor: Sonnet 5's tokenizer can map the same text to ~1.0–1.35x more tokens than 4.6 — re-profile after migrating.

## Where the savings come from, in order of size

1. **Tier arbitrage.** The high-turn execution loop — file reads, tool churn, code authoring — is where most tokens live, and the cascade bills it at S/H rates instead of F/O. Fable:Sonnet is 5x on both sides; Fable:Haiku is 10x. This is the biggest lever.
2. **Snowball capping.** A single long session re-sends its growing transcript every turn; even cache-discounted, effective input lands several times the sum of the cascade's four short, fresh stage contexts. Reference-not-reproduce compounds this: every block a stage doesn't quote is input the next stage never pays for.
3. **Format compression.** ~35–40% fewer output tokens — no narration, no summaries, each region authored exactly once instead of echoed in plan, edit, and recap. Real, but keep it in proportion: output is ~3% of a run's tokens and ~12% of its cost.
4. **Escalation economics.** A ~2k ESC bundle to a senior costs ~$0.02 of Opus input vs ~$0.50+ for adopting a full session context — 25x+ per consult. The larger effect is structural: the senior isn't resident for the whole session "just in case".

## Modeled example — mid-size task (~8 plan items, 6 files, 1 escalation)

Cascade, stage by stage (intro Sonnet pricing):

| Stage | In tok | Out tok | Cost |
|---|---|---|---|
| F fable | 50,000 | 700 | $0.535 |
| O opus | 45,000 | 2,500 | $0.288 |
| S sonnet | 120,000 | 3,000 | $0.270 |
| H haiku | 25,000 | 1,000 | $0.030 |
| ESC→O | 1,500 | 400 | $0.018 |
| **Total** | **241,500** | **7,600** | **$1.14** |

Single-model baselines for the same work (assumes ~550k cache-adjusted effective input from the session snowball, ~12k verbose output):

| Config | Cost | vs cascade |
|---|---|---|
| All-Fable | $6.10 | 5.3x |
| All-Opus | $3.05 | 2.7x |
| All-Sonnet 5 (intro) | $1.22 | 1.07x |
| All-Sonnet 5 (standard) | $1.83 | 1.4x (cascade rises to ~$1.28) |

The honest pitch is the third row: at parity with all-Sonnet, the cascade has Fable analysing and Opus planning — frontier judgment at workhorse price, because Fable reads once and emits ~600 tokens. Output-only view: $0.14 vs $0.60 all-Fable (~4x), on ~37% fewer tokens.

The baseline rows derive from two multipliers on the cascade's measured volume: **snowball ×2.3** on input (550k/241.5k) and **echo ×1.6** on output (12k/7.6k). They're assumptions — declared here, tunable in `usage.json`, and printed in every report so the counterfactual is auditable.

## When the cascade loses

Fixed floor ≈ three repo orientations (F, O, S each read in) plus orchestration — roughly $0.70–0.90 before the first edit lands. Below ~3 plan items, a single Sonnet session wins. Heuristic: cascade when the plan would have ≥3–4 items or spans multiple files; otherwise just run Sonnet.

## Measuring real runs — usage.json

The orchestrator appends one entry per spawn to `cascade/usage.json`:

```json
{
  "task": "first line of cascade/00-task.txt",
  "ts": "2026-07-02T09:00:00Z",
  "baseline_model": "claude-opus-4-8",
  "assumptions": {"snowball": 2.3, "echo": 1.6},
  "stages": [
    {"stage": "F", "model": "claude-fable-5",
     "input_tokens": null, "output_tokens": null,
     "total_tokens": 50700, "out_reported": 700,
     "duration_ms": 41000,
     "counters": {"find": 2, "open": 0}}
  ],
  "escalations": [
    {"id": "E1", "from": "S", "why": "conflict", "model": "claude-opus-4-8",
     "total_tokens": 1900, "out_reported": 400}
  ]
}
```

Two data grades, prefer the first:
- **API mode**: record each call's `usage.input_tokens` / `usage.output_tokens` — exact splits.
- **Claude Code**: Task completion notifications expose only `total_tokens`. Capture it the moment each notification arrives (it isn't persisted anywhere else), set `out_reported` from the stage's DONE `tok~=`, and the script derives input as total − output.

Then:

```
python scripts/cascade_cost.py cascade/usage.json --baseline claude-opus-4-8
```

The script prices every entry against the rate card (auto-switching Sonnet intro→standard by date), writes a `computed` block back into the file, and reports savings two ways:
- **floor** — this exact token volume repriced at the baseline model. Fact-grade: no counterfactual, pure tier arbitrage. The number to quote when you need to be unimpeachable.
- **modeled** — floor volume scaled by the snowball/echo multipliers. Estimate-grade: the realistic single-session counterfactual.

A run's real savings sit between the two. When enough runs accumulate, fit the multipliers to your own repos and retire the defaults.

## Fleet stats — the run ledger

Every cost-script invocation also appends a run record to the ledger — `$CASCADE_LOG`, default `~/.cascade/runs.jsonl` — unless `--no-log`: per-stage volumes and costs, aggregated DONE counters, escalation why-codes, duration if captured, and the floor/modeled savings. It prints a one-line lifetime summary after each run so overall efficiency is visible without ceremony.

```
python scripts/cascade_stats.py [--last N] [--repo SUBSTR] [--json]
```

turns the ledger into the overall-efficiency picture: spend vs both baselines; token and cost share by tier; **cost per landed change** — spend ÷ (ok + adapt), the unit-economics headline; escalation rate per plan item with the why-code histogram; delegation share; average stage output against the soft budgets (is the format holding, or drifting back toward prose?); and an all-time vs last-5 trend once there are ≥4 runs.

The why-code histogram is the tuning signal, not trivia: a pile of `anchor-missing` means O's locators go stale before S runs (tighten anchors or shorten the plan→execute gap); `test-fail` means plans under-specify their checks; `design-flaw` means F's analysis is too thin for the tasks being fed in; `flaky`/`env` means the harness, not the cascade, needs work.

To replace the modeled multipliers with measured ones: occasionally run a comparable task single-model, record its usage into a one-entry `usage.json`, and log it with `--kind baseline`. Stats then derives a measured snowball/echo from median volume ratios — labeled crude because runs aren't task-matched; a handful of baselines makes it honest, at which point set `assumptions` in your runs from the measured values.
