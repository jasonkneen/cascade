# cascade

## Why this exists

Long agentic coding sessions get expensive not because models are pricey, but because of the *shape* of a single-model session:

- **The snowball.** Every turn re-sends the whole growing transcript. Even with caching, effective input ends up several times the actual reasoning work — most of it re-read, not re-thought.
- **One model, every job.** The same model analyses the problem, plans the change, edits the files, and verifies the result — priced at that model's rate, even though most of those tokens are file reads and mechanical edits that don't need frontier judgment.
- **The echo.** Plans get narrated, edits get re-explained, results get summarized — the same information paid for two or three times before it's done.

Cascade fixes the shape, not the model. A task is split into four short stages, each pinned to the cheapest model capable of that stage's job, and each stage reads only its predecessor's written artifact — never the accumulated chat history. The expensive model reasons once, writes its judgment down densely, and every downstream model references that artifact instead of re-deriving it.

## Core strengths

- **Tier arbitrage.** Judgment-heavy, low-volume work (analysis, planning) runs on Fable/Opus; token-heavy, low-judgment work (editing, mechanical changes) runs on Sonnet/Haiku — 5–10x cheaper per token. Most of a coding session's tokens land on the cheap tier.
- **No snowball.** Each stage is a fresh, short context reading a plain-text `.cf` file, not a growing transcript. Code is referenced by locator, never re-quoted, so no stage pays to duplicate what the next stage can read straight off disk.
- **Dense wire format.** One human-readable status line per stage; everything else is machine-readable `.cf` records. No narration, no restating input, no "looks fine" noise — roughly 35–40% fewer output tokens than a prose-narrated session.
- **Escalation, not context-dumping.** A stuck stage sends the senior tier a ~15-line evidence bundle — what was tried, the error digest, the locators — instead of the whole session. Roughly 25x cheaper per consult than keeping the expensive model resident "just in case."
- **Measured, not just modeled.** Ships with a cost script that prices real runs against a rate card, and a fleet-stats script that tracks cost-per-landed-change, escalation patterns, and tier adherence across every run — so the savings claim is auditable, not a vibe.
- **Portable pipeline.** The `.cf` format and escalation ladder are provider-agnostic. Claude Code is the primary target (drop-in subagents + `/cascade` command), but the same four stages run as plain API calls under any orchestrator.

On a modeled mid-size task (8 plan items, 6 files, 1 escalation), cascade lands around $1.14 versus ~$3.05 for all-Opus and ~$1.83 for all-Sonnet-standard on the same work. See [`skills/cascade/references/economics.md`](skills/cascade/references/economics.md) for the full breakdown, the rate card, and when the cascade *doesn't* win (small tasks, under ~3 plan items — just run Sonnet).

See [`skills/cascade/SKILL.md`](skills/cascade/SKILL.md) for the full methodology: the `.cf` record grammar, the F → O → S/H pipeline, and the escalation ladder.

## Install

### Claude Code (plugin)

```
/plugin marketplace add jasonkneen/cascade
/plugin install cascade
```

This registers the `/cascade` command and the `cascade-analyze` / `cascade-plan` / `cascade-execute` / `cascade-assist` subagents automatically (via `.claude-plugin/plugin.json`).

### Claude Code (skill only, no plugin)

```
npx skills add jasonkneen/cascade --skill cascade -a claude-code
```

### Any agent supported by skills.sh

```
npx skills add jasonkneen/cascade
```

`skills add` resolves the `skills/cascade/` folder per the [Agent Skills spec](https://agentskills.io/specification) and installs (or symlinks) it into whichever of the 70+ supported agents you target with `-a`.

### Manual

Copy or symlink `skills/cascade/` into your agent's skills directory. If your harness supports Claude Code-style subagents, also copy `skills/cascade/assets/claude-code/agents/*.md` into `.claude/agents/` and `skills/cascade/assets/claude-code/commands/cascade.md` into `.claude/commands/`.

## Repo layout

```
cascade/
├── .claude-plugin/
│   ├── plugin.json        # Claude Code plugin manifest
│   └── marketplace.json   # Self-hosted marketplace (this repo installs itself)
├── skills/
│   └── cascade/
│       ├── SKILL.md               # agentskills.io / skills.sh compatible skill definition
│       ├── references/            # wire format, prompts, economics
│       ├── scripts/               # cascade_cost.py, cascade_stats.py
│       └── assets/claude-code/    # agents + /cascade command for Claude Code
├── LICENSE
└── README.md
```

## Compatibility

- **Claude Code**: plugin (`.claude-plugin/plugin.json` + `marketplace.json`) and raw skill both supported.
- **agentskills.io**: `skills/cascade/SKILL.md` follows the spec — `name` matches its parent directory, `description` states what/when, optional `license`/`compatibility`/`metadata` fields set.
- **skills.sh**: installable via `npx skills add jasonkneen/cascade`, which fans out to any of its supported agents (OpenCode, Codex, Cursor, etc.) via symlink or copy.

## Local development symlink

On the author's machine, `~/.claude/skills/cascade` is a symlink into this repo (`skills/cascade/`), so editing here is picked up by Claude Code directly without a reinstall step.
