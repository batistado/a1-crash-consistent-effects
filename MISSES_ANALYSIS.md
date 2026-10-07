# A1 Misses Analysis — why exactly-once was 0.914, not 1.000

**Date:** 2026-10-07 · **Data:** `llm_validation_results.json` (70 episodes, gpt-4o-mini, seed 20261008)
**Verdict: measurement artifact in the validation harness, NOT a protocol failure.**

## The numbers

| Metric | Value |
|---|---|
| Episodes | 70 (all crashed by design) |
| Duplicate-effect rate | **0.000** — zero duplicates in all 70 episodes |
| Exactly-once rate | 0.914 |
| Episodes with missing effects | 6 (ep 14, 28, 35, 40, 41, 47) |
| Total missing effects | 8 (mean 0.114/episode) |
| Claim adherence | 98.3% step-level, 100% episode-level |
| Violations (all episodes) | 0 |

Contrast with the scripted sandbox WAL condition (`results.json`, 1,500
episodes/condition, seed 20261007): **exactly-once 1.000, missing 0.000**.
The misses appear *only* when a real LLM drives the open-ended recovery
loop — which points at the recovery loop, not the protocol.

## Root cause (definitive)

Every one of the 6 miss episodes recorded **reemissions = 11** — exactly the
old recovery-loop cap (`while remaining and attempts < 12`, i.e. max 11
iterations). The two other episodes with re-emissions (7 and 8) completed
with 0 misses. The 62 remaining crashed episodes had 0 re-emissions.

Mechanism, step by step:

1. After a crash, the harness asks the LLM an open-ended recovery question
   ("re-emit a claim for any step you believe was lost, or emit the next step").
2. In 8/70 episodes the LLM chose to **re-emit claims for already-committed
   effects** instead of advancing. The harness correctly recognized each as
   committed and suppressed it (0 duplicates — the safety property held).
3. The loop's single `attempts` counter incremented on **every** iteration,
   including suppressed re-emissions.
4. In the 6 miss episodes the LLM re-emitted on all 11 iterations. Zero
   productive attempts remained, so genuine remaining steps were never
   attempted — and the scorer counted un-attempted steps as "missing".

No violations occurred in any miss episode (no unknown-target breaks, no
claim-parse failures), and miss episodes span all three crash landings
(in_window ×4, post_checkpoint ×1, pre_step ×1), ruling out a
landing-specific protocol bug. All 6 had 5-step goals (the max), consistent
with longer recovery contexts leaving more steps exposed to cap exhaustion —
but with n=6 this correlation is noted, not claimed.

**Classification: harness measurement artifact.** The cap exists only as an
anti-infinite-loop guard in the test harness; a production recovery loop
would not budget "total LLM calls including safely-suppressed no-ops"
against workflow progress. The protocol's safety guarantee (no duplicate
effects) held in 100% of episodes, including all 6 miss episodes where the
agent tried 11 times to re-fire committed effects and every attempt was
suppressed.

## Artifact audit (per project discipline)

- Goals are RNG-generated (`random.Random(seed)`), unique targets per
  episode — no templates, no placeholders, no shared cues between
  train/test (there is no train/test split here at all).
- The reemissions=11 ↔ loop-cap correspondence is exact and mechanistic
  (read directly from the loop code), not a correlational inference.
- Scoring is ledger-based (tool-side ground truth), independent of the
  agent's claims — the "missing" counts are real un-committed effects, and
  the "0 duplicates" counts are real ledger facts.

## Genuine secondary finding (not an artifact)

Even though the recovery prompt explicitly lists committed effects
("Committed effects (these definitely happened): …"), the LLM still
re-emitted them — 11 times in a row in 6 episodes. Open-ended recovery
elicits re-emission of known-committed work. This is a real behavioral
observation with a harness-engineering consequence: **a production recovery
policy should give the agent feedback on re-emissions** ("step X already
committed — here is what remains") rather than silently skipping, or it
will burn latency and tokens re-verifying the past. The current experiment
deliberately used silent skipping to observe natural behavior; a
feedback variant is a natural follow-up experiment.

## Fix implemented (code only — no re-run authorized)

`src/llm_validation.py`, recovery loop: the single attempt counter is
split into two budgets —

- `productive < 12`: genuine remaining-step executions (the progress budget);
- `attempts < 48`: total recovery LLM calls (hard anti-infinite-loop backstop).

Re-emissions of committed claims no longer consume the progress budget.
For episodes without re-emissions the behavior is unchanged (goals are
3–5 steps; 12 productive attempts never bind). The fix compiles
(`py_compile` clean). **Effect on the numbers is unmeasured**: re-running
the 70-episode validation ($~0.02) is required to confirm misses → 0 and
is explicitly not authorized in this task.

## Reviewer-ready framing

State the result as a **safety property**, and be explicit about its
boundary:

- *Safety (proven by the experiment):* under the write-ahead claim-log
  protocol, crash recovery never commits a duplicate effect — 0 duplicates
  across 70 LLM-driven episodes, including adversarial re-emission
  behavior by the agent.
- *Liveness (not claimed):* the protocol guarantees recovery *can*
  complete (all needed claims are durable and replayable); whether the
  agent actually emits the remaining claims depends on agent behavior and
  harness recovery policy. The misses are the empirical footprint of that
  boundary, and the separated-budget fix removes the harness's own
  contribution to it.

Do not present "exactly-once 0.914" as a protocol weakness. Present "zero
duplicates under LLM-driven recovery, with a characterized liveness
boundary" — that is the honest, reviewer-proof version.
