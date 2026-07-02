---
name: cascade
description: Token- and cost-optimised multi-model pipeline for code work — Fable analyses upfront, Opus plans every change with code citations, Sonnet 5 executes edits, Haiku does mechanical work, each stage emitting one human standby line plus a dense machine lane (.cf records with stable IDs, path:line locators, anchored minimal payloads), with a haiku→sonnet→opus→fable escalation ladder. Use whenever the user wants to run a task "through the cascade / pipeline / tiers", route work across Claude models by cost or capability, produce LLM-readable (not human-readable) analysis→plan→change handoffs, minimise output tokens between agents, or wire multi-model orchestration into Claude Code subagents or raw API calls — even if they only say things like "fable analyses then opus plans then sonnet edits" or "have the cheap model do the edits".
license: MIT
compatibility: Designed for Claude Code; stage prompts reference Claude model tiers but the .cf format and escalation ladder are usable as a raw-API orchestration pattern with any provider.
metadata:
  author: jasonkneen
  version: "1.0.0"
---

# cascade

One expensive pass of thinking, many cheap passes of doing. Fable reasons once and writes it down densely; every downstream model references that artifact instead of re-deriving it. The wire format exists so no stage ever spends tokens re-explaining, re-quoting code, or narrating for a human who isn't reading.

Humans read exactly one line per stage. Everything else is for the next model.

## Tier map — the only place model IDs live

| Tier | Model ID | Stage | Job |
|---|---|---|---|
| F | `claude-fable-5` | ANALYZE | Upfront analysis, high-level recommendations, arbitrate design escalations |
| O | `claude-opus-4-8` | PLAN | Turn findings into grounded change specs with code citations |
| S | `claude-sonnet-5` | EXECUTE | Apply changes, verify each, delegate mechanical work |
| H | `claude-haiku-4-5` | ASSIST | Mechanical edits, bulk operations, fetching context on request |

When a new family version ships, update this table and nothing else — every prompt and agent file refers to tiers, not models. (Verified current as of 2026-07: Sonnet 5 is GA; Fable 5 rejects an explicit `thinking: {type:"disabled"}` — omit the thinking parameter entirely on API calls.)

## The five output rules (every tier, every message — including escalations)

1. **First line is `HUMAN: <≤20 words>`** — the only prose a person reads. It's a standby line ("Auth analysed — 3 fixes planned, executing."), not data. Nothing a human must act on goes here.
2. **Everything after is the machine lane.** One record per line, `TYPE id k=v …`, payloads in `<<<id … >>>` blocks. No markdown, no headers, no restating input, no preamble, no apology, no narration.
3. **Reference, don't reproduce.** Locate code as `path:start-end#"anchor line"`. Quote at most that single anchor line per locator. Never paste code the next model can read from disk — it has the repo; you're paying output tokens to duplicate its filesystem.
4. **Exceptions only.** Silence means fine. No per-file OKs, no "no issues found in X" enumerations. A record exists because something needs doing or went wrong.
5. **Errors are digests, not dumps.** `err="<≤120 chars>" exit=N log=cascade/logs/x.txt`. Full output goes to disk and is referenced; a senior that wants more asks with NEED.

The full record grammar, field vocabulary, and a complete worked run live in `references/format.md`. Read it before emitting your first record; each stage prompt carries a condensed copy of just the records it emits.

## Pipeline

Artifacts are plain-text `.cf` files under `cascade/` in the repo. Each stage reads its predecessor's file plus the repo — never chat history.

```
cascade/00-task.txt → [F] 10-findings.cf → [O] 20-plan.cf → [S/H] 30-changes.cf
                                                     esc/E*.cf ↔ senior tiers
                                                     logs/     full command output
```

**Stage F — ANALYZE** (`references/prompts/analyze.md`). Reads the task and the repo. Emits FIND records — severity, locator, what, fix-direction, dependencies, cross-references — plus at most 3 OPEN questions for genuine ambiguity. No code bodies, no diffs, no implementation detail: F's judgment is expensive, so it's spent on *what and why*, never *how*. Soft budget ~600 output tokens.

**Stage O — PLAN** (`references/prompts/plan.md`). Resolves every FIND into PLAN records: operation, locator+anchor, and citations (`ref=`) for the definition site and call sites of everything touched — Opus greps to ground each edit in the real code, so S never has to re-discover context. Carries a `test=` command per item and `order=` for dependencies. Payload blocks only for code that must be authored; where S can write it from the spec, mark `fill=S` and skip the payload.

**Stage S — EXECUTE** (`references/prompts/execute.md`). Applies PLAN items in order. Anchors are truth, line numbers are hints — relocate by anchor and report `drift=±n`. Runs each item's `test=` and emits CHG records where `ver=pass` means *the named check actually passed*, not "the command exited 0". Mechanical items (renames, repeated multi-file edits, formatting, log gathering) are marked `st=deleg` for H. Two failed attempts on one item → ESC, then move on; never spin.

**Stage H — ASSIST** (`references/prompts/assist.md`). Does exactly what its records say, answers NEED with GIVE payloads, never improvises design. If an instruction is ambiguous, that's an ESC to S, not a guess.

## Escalation ladder

Any stuck editor climbs H → S → O → F, one tier per hop, under the same output rules.

- **Trigger:** two failed attempts on one item, or `why=design-flaw` / `why=spec-conflict` — those two jump straight to F, because re-planning a broken design at O wastes a hop.
- **The ESC record is the whole handoff:** id, why-code, what was tried, evidence locators, error digest. The senior receives *only* that (plus the chained records it references) — typically under 15 lines. It pulls anything more via NEED, answered by H or the caller, so the expensive model reasons over extracts instead of paying to read whole files.
- **Seniors answer, juniors act.** The senior replies with RES + respec'd PLAN records; the originating tier executes them. This keeps execution tokens on the cheap model. If the same item bounces twice, the senior may take it (`verdict=take`).
- Every hop is appended to `30-changes.cf`, so the final DONE line carries honest counts: `ok= adapt= blk= deleg= esc=`.

## Micro-example (condensed — full run in references/format.md)

```
HUMAN: Auth analysed — 2 issues, no blockers.
FIND F1 sev=H tag=race at=src/auth/session.ts:41-58#"async function refresh" what="401 triggers parallel double-refresh" fix=serialize-refresh ref=src/auth/client.ts:112 dep=-
FIND F2 sev=M tag=dead at=src/auth/legacy.ts what="module unreferenced" fix=delete ref=- dep=F1
DONE stage=F find=2 open=0 tok~=170
```
```
HUMAN: Plan ready — 2 changes, 1 with new code.
PLAN P1<-F1 op=replace at=src/auth/session.ts:44-46#"const t = await fetchToken" why=serialize ref=src/auth/session.ts:19,src/auth/client.ts:112 test="pnpm vitest run auth" order=1
<<<P1
const t = await this.refreshLock.run(() => fetchToken(this.rt));
>>>
PLAN P2<-F2 op=delete at=src/auth/legacy.ts why=dead ref=- test="pnpm vitest run" order=2
DONE stage=O plan=2 tok~=210
```
```
HUMAN: One applied clean, one escalated — legacy is still imported.
CHG C1<-P1 st=ok ver=pass t="auth 12/12" drift=+2
ESC E1 from=S on=P2 why=conflict tried=[delete,grep-callers] ev=src/boot/index.ts:9#"import './auth/legacy'" err="deleting breaks boot import" exit=1
DONE stage=S ok=1 blk=1 esc=1 tok~=140
```
O replies with `RES R1->E1 verdict=respec` plus P2b (delete the import first) and P2c (delete the module); S executes both and appends the CHGs.

## Running it

**Claude Code (primary target).** Install `assets/claude-code/agents/*.md` into `.claude/agents/` and `assets/claude-code/commands/cascade.md` into `.claude/commands/`, then `/cascade <task>`. The main thread is the orchestrator: it spawns cascade-analyze → cascade-plan → cascade-execute sequentially via Task, each subagent pinned to its tier's model. Subagents can't nest, so the orchestrator mediates: after S returns, it hands any `st=deleg` items to cascade-assist and any ESC records to the correct senior agent — passing *only* those records — then feeds RES respecs back to a fresh cascade-execute. It also meters every spawn into `cascade/usage.json` and closes with `scripts/cascade_cost.py`, which prices the run and reports savings vs a single-model baseline two ways (fact-grade reprice floor; modeled counterfactual — see `references/economics.md`). If your plan lacks Fable access, point cascade-analyze's `model:` at `claude-opus-4-8`.

**Raw API / your own orchestrator (e.g. Conduit).** One `messages` call per stage: system = the stage prompt from `references/prompts/`, user = the predecessor `.cf` file (plus GIVE extracts as needed), model per the tier map, `max_tokens` near the stage budget. Escalations are a fresh call to the senior tier whose user turn is just the ESC bundle. Here S *can* call H directly — nesting is yours. Record each call's `usage.input_tokens`/`usage.output_tokens` into `cascade/usage.json` (exact splits — better data than Claude Code's totals) and run the same cost script. Omit the `thinking` parameter on `claude-fable-5`.

**Claude.ai chat.** No subagents, so the economics don't apply — but the format still does. When asked to "cascade" a task here, run the stages yourself in order, writing each `.cf` artifact, so output stays in the wire format and can be resumed by real tiers later.

## Interop

Stage F's analysis discipline is the `fable-method` skill (diagnose from evidence, prune hypotheses before testing) if it's installed; Stage S's `ver=pass` rule is its ship-gate — a green exit code is not a pass, the named assertion passing is. Neither skill is required; the stage prompts carry the load-bearing rules.

## Files

- `references/format.md` — canonical `.cf` grammar, field vocabulary, full worked run with escalation. The source of truth when any record is ambiguous.
- `references/economics.md` — rate card, savings decomposition, the modeled example, when the cascade loses, and the `usage.json` measurement spec.
- `references/prompts/{analyze,plan,execute,assist}.md` — self-contained stage playbooks; use verbatim as system prompts.
- `scripts/cascade_cost.py` — stdlib-only cost report: prices `cascade/usage.json` against the rate card (auto-switches Sonnet intro→standard by date), writes back floor/modeled savings vs a baseline, and appends every run to the cross-repo ledger (`~/.cascade/runs.jsonl`).
- `scripts/cascade_stats.py` — fleet efficiency over the ledger: spend and savings totals, cost per landed change, token share by tier, escalation why-code histogram, stage-budget adherence, trend, and measured multipliers once `--kind baseline` runs exist.
- `assets/claude-code/` — drop-in subagent definitions and the `/cascade` command.
