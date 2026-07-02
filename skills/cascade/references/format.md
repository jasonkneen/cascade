# The .cf wire format — canonical reference

Every cascade message, from every tier, in every direction (downstream handoff, escalation, respec) has this shape:

```
HUMAN: <one plain sentence, ≤20 words>
<records, one per line>
<<<id
<payload>
>>>
DONE stage=<F|O|S|H> <counters> tok~=<estimate>
```

Nothing else. No markdown, no blank-line padding, no code fences, no restating what you were given. If you're tempted to explain something to a human, it belongs in the HUMAN line or nowhere.

## Record syntax

```
TYPE id[<-parent | ->target] key=value key="value with spaces" key=[a,b,c]
```

- **ids**: stage letter + integer — `F3 P7 C7 E1 R1 N2 G2 Q1`. Respecs suffix a letter: `P2b`. Ids are immutable once emitted.
- **lineage**: `<-` chains downstream (`P4<-F2`, `C4<-P4`); `->` points a reply at what it answers (`R1->E1`, `G2->N2`). Lineage lets any tier trace an item back to the original finding without reading history.
- **values**: bare if no whitespace; double-quoted otherwise; lists as `[a,b,c]`. Omit keys whose value is empty or default — absence is information.
- **forward compat**: readers ignore keys they don't recognise; never fail on one.

## Locators

```
path                 src/auth/legacy.ts              (whole file — create/delete/move)
path:line            src/auth/session.ts:44
path:start-end       src/auth/session.ts:44-51
…#"anchor"           src/auth/session.ts:44-51#"const t = await fetchToken"
```

The anchor is the exact text of the first line of the target region, ≤80 chars, and it wins: when line numbers have drifted, relocate by anchor and report `drift=±n`. Quote at most one anchor line per locator — the executor has the file; it needs a fingerprint, not a copy.

## Record types

**FIND** — Stage F. One per issue worth acting on.
```
FIND F1 sev=H tag=race at=<locator> what="<≤12 words>" fix=<direction-slug> ref=<locator[,locator]> dep=<Fid|->
```
`sev` H|M|L · `tag` one-slug category (race, dead, perf, sec, api, dx…) · `fix` a direction, never an implementation · `ref` where else this issue touches · `dep` finding that must land first.

**OPEN** — Stage F, ≤3 per run. A genuine ambiguity a human or F must settle.
```
OPEN Q1 q="<question>" blocking=<Fid|->
```

**PLAN** — Stage O. One per concrete change.
```
PLAN P1<-F1 op=<op> at=<locator+anchor> why=<slug> ref=<citations> test="<cmd>" order=<n> fill=<-|S>
```
`op` replace|insert|delete|create|move|diff · `ref` citations grounding the edit — definition site, call sites, the type/interface involved — as locators · `test` the check that proves this item, runnable as-is · `order` execution sequence; equal numbers may run in parallel · `fill=S` means the payload is intentionally absent and Sonnet authors the code from the spec.
Payload required for replace/insert/create/diff unless `fill=S`. `insert` payloads go immediately after the anchor line. `move` uses `to=<locator>`.

**CHG** — Stages S/H. One per PLAN item touched.
```
CHG C1<-P1 st=<st> ver=pass|fail|- t="<test digest>" drift=<±n> note=<slug>
```
`st` ok|adapt|blk|skip|deleg|took — `adapt` = applied with deviation (say what in `note=`); `blk` = escalated, see the ESC; `deleg` = handed to H; `took` = a senior executed it after a bounce.
`ver=pass` is a claim that the named check passed and the change is really in the file — not that a command exited 0. If you can't show it, it's `ver=-`.

**ESC** — any tier, upward.
```
ESC E1 from=<H|S|O> on=<Pid|Cid> why=<code> tried=[a,b] ev=<locator[,…]> err="<≤120 chars>" exit=<n> log=<path>
```
This record plus the records it chains to is the senior's entire context. Make `ev` count.
`why` codes: `anchor-missing test-fail build-fail ambiguous conflict design-flaw spec-conflict env perms flaky`. `design-flaw` and `spec-conflict` skip straight to F.

**RES** — the senior's reply to an ESC.
```
RES R1->E1 verdict=respec|wontfix|defer|take reason=<slug>
```
`respec` is followed by replacement PLAN records (suffixed ids: `P2b`, `P2c`) which the *originating* tier executes. `take` means the senior did it and appends its own CHG with `st=took`.

**NEED / GIVE** — context requests, any direction.
```
NEED N1 want=<locator|glob|"cmd"> why=<slug>
GIVE G1->N1
<<<G1
<the extract or command output, trimmed to what was asked>
>>>
```
Seniors NEED; H (or the caller) GIVEs. This is how an expensive model reads three functions instead of three files.

**DONE** — terminator, always last.
```
DONE stage=F find=3 open=1 tok~=220
DONE stage=O plan=5 tok~=800
DONE stage=S ok=4 adapt=1 blk=1 deleg=2 esc=1 tok~=520
```

## Payload blocks

```
<<<P4
verbatim new content
>>>
```
- Content only — the region being written, not the whole file (except `op=create`).
- `op=diff` payload is a unified diff, context = 1 line, paths repo-relative, one hunk per logical change. Prefer anchor+payload for single regions; diff for scattered multi-hunk edits in one file.
- Nothing decorative inside: no fences, no comments explaining the change (that's `why=`).

## Budgets (soft — going slightly over beats being cryptic)

| Thing | Cap |
|---|---|
| HUMAN line | 20 words |
| Stage F output | ~600 tokens |
| Stage O output | ~1200 tokens + payloads |
| Stage S records | ~400 tokens (payloads exempt) |
| Stage H output | ~200 tokens |
| err digest | 120 chars |
| anchor quote | 1 line, 80 chars, per locator |

## Full worked run

Task (`cascade/00-task.txt`): "Session refresh sometimes fires twice on 401 and there's an old legacy auth module — clean both up."

`10-findings.cf` — Fable:
```
HUMAN: Auth analysed — a real race plus dead code, no blockers.
FIND F1 sev=H tag=race at=src/auth/session.ts:41-58#"async function refresh" what="401 triggers parallel double-refresh" fix=serialize-refresh ref=src/auth/client.ts:112 dep=-
FIND F2 sev=M tag=dead at=src/auth/legacy.ts what="module unreferenced by feature code" fix=delete ref=- dep=F1
DONE stage=F find=2 open=0 tok~=170
```

`20-plan.cf` — Opus:
```
HUMAN: Two changes planned; the race fix carries new code.
PLAN P1<-F1 op=replace at=src/auth/session.ts:44-46#"const t = await fetchToken" why=serialize ref=src/auth/session.ts:19#"private refreshLock",src/auth/client.ts:112 test="pnpm vitest run auth" order=1
<<<P1
const t = await this.refreshLock.run(() => fetchToken(this.rt));
>>>
PLAN P2<-F2 op=delete at=src/auth/legacy.ts why=dead ref=- test="pnpm vitest run" order=2
DONE stage=O plan=2 tok~=210
```

`30-changes.cf` — Sonnet, first pass:
```
HUMAN: Race fixed and verified; legacy delete blocked — boot still imports it.
CHG C1<-P1 st=ok ver=pass t="auth 12/12" drift=+2
ESC E1 from=S on=P2 why=conflict tried=[delete,grep-callers] ev=src/boot/index.ts:9#"import './auth/legacy'" err="tsc: cannot find module './auth/legacy'" exit=2 log=cascade/logs/p2-tsc.txt
DONE stage=S ok=1 blk=1 esc=1 tok~=150
```

`esc/E1.cf` — Opus, receiving only E1 + P2 + F2:
```
HUMAN: Respec'd — drop the boot import first, then the module.
RES R1->E1 verdict=respec reason=stale-import
PLAN P2b<-F2 op=delete at=src/boot/index.ts:9#"import './auth/legacy'" why=unblock ref=- test="pnpm tsc --noEmit" order=1
PLAN P2c<-F2 op=delete at=src/auth/legacy.ts why=dead ref=- test="pnpm vitest run" order=2
DONE stage=O plan=2 tok~=120
```

`30-changes.cf` — Sonnet, appended (P2b was mechanical, so it went to Haiku):
```
HUMAN: Legacy fully removed; suite green.
CHG C2<-P2b st=deleg
CHG C2b<-P2b st=ok ver=pass t="tsc clean"
CHG C3<-P2c st=ok ver=pass t="vitest 84/84"
DONE stage=S ok=2 deleg=1 blk=0 esc=0 tok~=110
```

Total human reading across the entire run: six one-liners. Total machine lane: ~40 lines, every one load-bearing.
