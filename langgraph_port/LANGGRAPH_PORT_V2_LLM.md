# A1 LangGraph Production Port v2 — Real-LLM Supervisor Results

The scripted-planner v2 run (`LANGGRAPH_PORT_V2.md`) established that the
crash-consistent checkpointing protocol survives a production-shaped agent
(branching supervisor, `Send` fan-out, retry with backoff, escalation):
wal 0.0000 duplicates / exactly-once 1.0000 over 60 episodes per condition.
The scripted planner was honest scoping — the fault class is harness-side —
but it leaves a reviewer question open: does anything change when the
routing decision is a genuine model judgment instead of a seeded coin flip?
This run answers it: the identical experiment, same seeds and crash points,
with the round-1 routing decision made by a real **gpt-4o-mini** planner.

**Setup:** 180 episodes (60/condition), seed 20261011, real `SIGKILL` per
episode via an external predicate watchdog, tool server on :8767
(v2 scripted used :8766; separate port to avoid any cross-run state).
One crash per episode: mid_fanout (p=0.5), post_branch (p=0.25),
retry_backoff (p=0.25). Completed 2026-10-07, ~28 min wall clock.

## The LLM planner: what it does and doesn't see

- The model decides **round-1 routing only** (`fan_out` vs `escalate`).
  Round 0 is structural (always fan_out) in both variants.
- It **never sees the raw claim log**. The constraint is architectural, not
  prompt-level: in the recovery generation, the deterministic
  `recover_node` (claim reconciliation, epoch fencing, branch-state
  recompute) runs *before* the supervisor node, and the model receives only
  the reconciled remaining work — settled branch IDs, round number,
  generation mode.
- The model is consulted in **both** generations: fresh (34 post_branch
  episodes, where the decision precedes the kill) and recover (all 180).
  The recovery generation's decision is authoritative for scoring.
- Decision parameters: temperature 0, max_tokens 20, 60s timeout, 3
  retries with backoff. Unparseable/persistent failure falls back to
  `fan_out` (the scripted majority class) and is logged as a fallback —
  0 fallbacks occurred.
- Every decision is persisted twice: `decisions.jsonl` (audit trail) and
  `scenario.json` (so the wal log-fenced branch-state recompute sees the
  *actual* route, not the scripted placeholder).
- Ground truth for scoring is built from the episode's **actual LLM
  decisions**, not the scripted scenario generator. A run is scored against
  what the model really decided. 0 episodes needed the scripted fallback.
- Campaign hard stop: **$5** OpenAI API (auth via the `custom.openai`
  connector surrogate; spend ledger per run dir, abort above $4.50).

## Headline results

| Condition | Episodes | Duplicate-effect rate | Exactly-once rate |
|---|---|---|---|
| wal (claim log + fencing) | 60 | **0.0000** | **1.0000** |
| baseline (no keys, no log) | 60 | 0.8000 (48/60) | 0.2000 |
| deterministic keys | 60 | **0.0000** | **1.0000** |

Crash-injection integrity: 0 missed crashes, 0 recovery failures in all
conditions. Zombie probes (stale-epoch calls post-recovery): fenced 60/60
(HTTP) and 60/60 (file) in every condition. Mid-fanout partial-completion
rate 1.000 in all conditions (genuine partial at kill time; never 0,
never all).

## Crash-point breakdown

| Condition | mid_fanout (n) | dup eps | retry_backoff (n) | dup eps | post_branch (n) | dup eps |
|---|---|---|---|---|---|---|
| wal | 33 | 0 | 20 | 0 | 7 | 0 |
| baseline | 30 | 30 | 18 | 18 | 12 | 0 |
| deterministic | 32 | 0 | 13 | 0 | 15 | 0 |

Identical crash distributions to the scripted run (same seeds) and
identical outcomes per crash point: mid_fanout and retry_backoff duplicate
in baseline (48/48 combined), 0 everywhere under wal/deterministic;
post_branch duplicates nowhere (nothing committed yet — the liveness
check: all 34 post_branch episodes across conditions resumed and finished
with 0 missing effects).

Baseline duplicate-count distribution: 48 episodes with 2 duplicates,
12 with 0 (scripted: 47×2, 1×1, 12×0 — the single-episode difference is
kill-timing thread noise in which branches had committed; route-independent).

## Scripted vs LLM planner

| Condition | Planner | Dup rate | Exactly-once | Misses (cause) |
|---|---|---|---|---|
| wal | scripted | 0.0000 | 1.0000 | 0 |
| wal | llm | **0.0000** | **1.0000** | 0 |
| baseline | scripted | 0.8000 | 0.2000 | 0 |
| baseline | llm | 0.8000 | 0.2000 | 0 |
| deterministic | scripted | 0.0000 | 1.0000 | 0 |
| deterministic | llm | **0.0000** | **1.0000** | 0 |

The headline numbers are **identical** in all three conditions. The
protocol's guarantees do not depend on who makes the routing decision —
which is exactly what the theory predicts (the fault class is
harness-side; routing is above the crash-consistency layer), and the point
of running the variant at all.

## Behavioral differences vs the scripted planner

- **Route distribution:** scripted drew round-1 fan_out at p=0.6 per the
  episode seed (~60/40). The LLM chose **fan_out 214/214 times — 0
  escalations** across 180 episodes, temperature 0, all replies clean
  single-token `fan_out`, 0 fallbacks. The model is systematically more
  fan-out-leaning than the scripted 60/40 split: with all round-0 branches
  settled, it always judged parallel continuation the right call.
- **Cross-generation consistency:** in the 34 post_branch episodes the
  fresh and recover generations each consulted the model independently;
  **34/34 agreed** (all fan_out). No recovery decision ever contradicted
  the pre-crash one.
- **Honest limitation:** because the model never escalated, this run did
  not exercise the escalate crash path. The escalate path's
  crash-consistency was validated in the scripted run (~40% of episodes);
  this run validates the protocol under a real model's routing judgment,
  which happened to never take that branch.
- **Latency:** per-decision median 0.76s, max 36.8s (one slow call, under
  the 60s timeout). Against multi-second tool calls this is noise; it does
  not change the overhead story below.

## API spend

**$0.0069** total — 214 gpt-4o-mini calls (212 prompt / 2 completion
tokens each), 0.14% of the $5 campaign cap. Per-run-dir `llm_spend.json`
ledgers all reconcile to the run total.

## Overhead

Claim-log write latency (wal only, fsync per CLAIM/COMMIT record, n=1038):
p50 **16.4 ms**, p99 **54.6 ms**, max 86.5 ms. Same ~1% tax vs multi-second
LLM tool calls as the scripted v2 (p50 20.3 ms / p99 63.4 ms) — the LLM
planner adds no per-claim cost.

## What's real vs simulated (reviewer-facing honesty)

- Real: everything in the v2 list (StateGraph, Send fan-out, retry with
  real backoff, real SIGKILL, non-idempotent tools, fsync'd claim log,
  epoch fencing, ledger scoring) **plus** a real gpt-4o-mini routing
  judgment per round 1 (214 judgments, all logged).
- Simulated: the round-0 structure, the transient failure that triggers
  the retry path (chaos-instrumentation, as in v2).
- The model plans routes only; it never sees the claim log. The
  reconciliation it plans *from* is deterministic.
- One crash per episode; workers are threads in one process (crash-stop
  model holds — recovery starts only after SIGKILL).

## Bugs found and fixed during the build (method note)

1. **Stale in-memory scenario after the LLM decision.** The decision was
   persisted to `scenario.json` on disk, but the LangGraph state's
   in-memory `scenario` still held the scripted placeholder route — so the
   supervisor decided `fan_out` while `dispatch_node` fanned out the
   stale `["esc"]` branch. Caught 3 episodes into the first full run
   (wal showed duplicates — impossible for the protocol, which is what
   made it suspicious); the run was killed, the fix applied
   (`supervisor_node` now returns the updated scenario into the state),
   and the campaign restarted cleanly with `--overwrite`. The 3 poisoned
   episodes were discarded, not scored.
2. `planner` was not declared in `AgentStateV2`, so LangGraph silently
   dropped it from the state and the LLM branch never triggered (caught in
   a 1-episode smoke test: 0 model calls, spend $0.0000). Same bug class as
   v2's #3 — LangGraph drops undeclared state keys without warning.

## Mixed-distribution follow-up (temperature 1.0, 2026-10-07)

The run above left one limitation: the model chose `fan_out` in all 180
episodes, so the protocol was validated under a uniform route distribution
only. A temperature-1.0 rerun was authorized to test it under a genuine mix —
but the first attempt (killed at 30/60) showed every decision still `fan_out`,
and the root cause was the prompt, not the temperature: it showed the model
identical evidence every episode (3 branches, 1 finding each, branch IDs
only), so `fan_out` was the only rational answer and sampling noise could
never create a real mix.

Fix (`llm_planner.py`): (1) seeded per-episode evidence profiles via
`evidence_summary(plan_seed)` — unanimous corroboration vs divergent findings
vs 2-of-3 split, deterministic in `plan_seed` with a domain-separated RNG so
the fresh and recover generations judge identical evidence; the model still
never sees the claim log. (2) A cost-aware decision rule: `fan_out` costs 6
more non-idempotent effects and delays incident resolution, `escalate`
concludes now — without costs there is no decision, only a default.
Validated before relaunching: at temperature 0 the model's argmax cleanly
separates (strong evidence → escalate 3/3, weak → fan_out 3/3).

Full campaign (180 episodes, 60/condition, same seed 20261011, temp 1.0):
**135 escalate / 79 fan_out across 214 round-1 decisions, 0 fallbacks** — a
genuine model-driven mixed distribution. Results: wal 0.0000 duplicates /
1.0000 exactly-once (60/60), baseline 0.8000 / 0.2000, deterministic keys
0.0000 / 1.0000, zero missing effects. Spend $0.0117. This is the primary
reported supervisor result.

## Verdict

The protocol is planner-agnostic in practice, not just in theory: with a
real gpt-4o-mini supervisor making routing judgments from reconciled state
(never seeing the claim log), wal holds 0.0000 duplicates / 1.0000
exactly-once, baseline reproduces its 0.80 duplicate rate, and deterministic
keys hold at 0.0000 — headline-identical to the scripted run, under both a
uniform route distribution (temp-0: 180/180 fan_out, $0.0069) and a genuine
mixed one (temp-1.0: 135 escalate / 79 fan_out, $0.0117). The empirical
package is complete: sandbox (1,500 eps/condition), LLM validation (2 models
× 70), component ablations, LangGraph v1, v2 scripted, v2 real-LLM supervisor
(uniform + mixed).
