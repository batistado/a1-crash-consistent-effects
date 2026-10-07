# A1 LangGraph Production Port v2 — "Research Assistant" Results

The v2 scenario (see `DESIGN_V2.md`) answers the follow-up to the v1 linear
loop: does the crash-consistent checkpointing protocol survive a
production-shaped agent — branching supervisor, `Send`-based parallel
fan-out to a compiled worker subgraph, framework-level retry with real
backoff, escalation branch — or only a toy loop?

**Setup:** 180 episodes (60/condition), seed 20261011, real `SIGKILL` per
episode via an external predicate watchdog, tool server on :8766.
One crash per episode: mid_fanout (p=0.5), post_branch (p=0.25),
retry_backoff (p=0.25). Planner scripted (no API spend); the fault under
study is harness-side crash consistency, not cognition.

## Headline results

| Condition | Episodes | Duplicate-effect rate | Exactly-once rate |
|---|---|---|---|
| wal (claim log + fencing) | 60 | **0.0000** | **1.0000** |
| baseline (no keys, no log) | 60 | 0.8000 (48/60) | 0.2000 |
| deterministic keys | 60 | **0.0000** | **1.0000** |

Crash-injection integrity: 0 missed crashes, 0 recovery failures in all
conditions. Zombie probes (stale-epoch calls post-recovery): fenced 60/60
(HTTP) and 60/60 (file) in every condition.

## Crash-point breakdown

| Condition | mid_fanout (n) | dup eps | retry_backoff (n) | dup eps | post_branch (n) | dup eps |
|---|---|---|---|---|---|---|
| wal | 33 | 0 | 20 | 0 | 7 | 0 |
| baseline | 30 | 30 | 18 | 18 | 12 | 0 |
| deterministic | 32 | 0 | 13 | 0 | 15 | 0 |

- **mid_fanout** (kill on first `WORKER r0 … COMMIT`): 100% of episodes
  across all conditions had a *genuine partial* fan-out at kill time (a
  strict subset of the 3 dispatched branches committed; never 0, never
  all). Baseline duplicated in 30/30 — recovery re-dispatched unsettled
  branches with no claim log to consult. wal skipped via committed claims
  and reconciled the rest; 0 duplicates, 0 missing.
- **retry_backoff** (kill during the 1s backoff sleep): baseline duplicated
  in 18/18 — the two in-flight branches' effects were committed but
  unrecorded, so recovery re-executed them. wal reconciled the uncommitted
  retry claim and completed exactly once.
- **post_branch** (kill after the round-1 branch decision, before any tool
  call): 0 duplicates everywhere, as designed — nothing had committed yet.
  This is the liveness check: recovery must *resume and finish* the
  decided branch rather than stall. 12/12 baseline episodes completed with
  0 missing effects.

Baseline duplicate-count distribution: 47 episodes with 2 duplicates, 1
with 1, 12 with 0 (the post_branch episodes).

## The deterministic-keys nuance (v1 vs v2)

In v1, deterministic keys failed at 0.2333 because post-recovery plan
shifts re-derived different key identities (Theorem 1, case ii). In v2
they hold at 0.0000 — because branch identities here are *structural*
(round, branch, effect) and stable across recovery by construction; no
re-derivation stress is applied to them. This sharpens the paper's claim
rather than weakening it: **keys fail exactly when post-recovery
recomputation re-derives different identities**; the WAL makes recovery
independent of that recomputation in both regimes. (Honest note: v2's
`p_reword`/`p_plan_shift` knobs are plumbed but inert — there is no
plan-string to reword in a branch-structural scenario.)

## Overhead

Claim-log write latency (wal only, fsync per CLAIM/COMMIT record, n=798):
p50 **20.3 ms**, p99 **63.4 ms**, max 205 ms. Against multi-second LLM tool
calls this is the same ~1% tax measured in `OVERHEAD.md`; v2 adds no new
per-effect cost, only more claims per episode (branch fan-out multiplies
the claim count, not the per-claim price).

## What's real vs simulated (reviewer-facing honesty)

- Real: LangGraph StateGraph, conditional routing, Send fan-out to a
  compiled subgraph, reducer fan-in, retry loop with real backoff sleep,
  real SIGKILL, real non-idempotent tools (HTTP + file), fsync'd claim
  log, epoch fencing, ledger-based semantic scoring.
- Simulated: the supervisor/planner decisions (scripted from seed — the
  fault class is harness-side, so this is scoping, not a gap); the
  transient tool failure that triggers the retry path (the backoff and
  retry are real; the failure injection is chaos-instrumentation, exactly
  like the crash schedule).
- One crash per episode; workers are threads in one process (crash-stop
  model holds — recovery starts only after SIGKILL).

## Bugs found and fixed during the build (method note)

1. Recovery initially marked a branch done when *any* of its effects was
   committed — fixed to require *all* effects' claims committed (partial
   fan-out must not settle the branch).
2. A read-modify-write race on the branch-state file under Send fan-out
   lost worker completion records — fixed with one atomic file per settled
   branch (append-only discipline, same reason the claim log is append-only).
3. LangGraph silently drops node outputs whose keys aren't declared in the
   state's TypedDict — the escalate chain's keys are now declared. (This
   produced 24 wal recovery-process failures in a first full run; ledger
   scoring was unaffected, but the run was discarded and repeated cleanly.)

## Verdict

The protocol composes with branching, parallel fan-out, delegation, and
retry — the exact structures the "toy loop" objection names. v2 reproduces
v1's ordering (wal ≈ deterministic > baseline) with a harsher fault
(partial fan-out completion): wal 0.0000 duplicates / exactly-once 1.0000
over 60 episodes with 0 recovery failures. Combined with v1, the empirical
package now covers linear, branching, and parallel agent shapes.
