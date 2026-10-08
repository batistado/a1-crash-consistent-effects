# A1 Phase 4 — Reviewer-Requested Experiments: Results

**Date:** 2026-10-08 | **Spend:** $0 (all scripted/local) | **Status:** In progress

For each experiment: the reviewer's question, what we ran, the result, and what it means for the paper.

---

## E1 — Native-persistence baseline (reviewer §6.3)

**Question.** Does LangGraph's own checkpointer (SqliteSaver), with documented task boundaries + durable operation identities + the same receiver contract, match our WAL on duplicates/completion under matched crash schedules?

**Design.** Rebuilt the v2 agent graph on LangGraph's `SqliteSaver` checkpointer (no claim log, no manual recovery node). Fresh generation runs `invoke` with thread state; on SIGKILL the recovery re-`invoke`s with `None` input, letting the checkpointer resume from the last committed superstep. Durable identities: the native runner uses the same deterministic keys as the `det` condition. Same crash schedule (SIGKILL at retry_backoff/mid_fanout/post_branch) and same idempotent receiver contract.

**Result.** 60/60 exactly-once, 0 duplicates, 0 missing. Crash mix: 26 mid_fanout, 16 retry_backoff, 18 post_branch — all handled.

**Paper implication.** Native persistence MATCHES the WAL when recovery preserves identities (same deterministic keys, no replanning). The WAL's contribution is not "the only way to 0 duplicates" — it's the robust way when identities shift (E2) plus explicit auditability. §6.3 should acknowledge native works for the matched case; the WAL wins on robustness.

**Verdict vs reviewer ask:** PASS.

---

## E2 — Identity shift across recovery (reviewer §4; the critical one)

**Question.** What happens when operation identities change across the crash — i.e., recovery replanning rewords tool arguments or shifts branch positions so deterministic keys (content-hash AND positional) differ from the pre-crash ones, while the WAL's claim records preserve the original identities?

**Design.** Two sub-experiments:
- **E2a (positional shift):** recovery rotates branch dispatch positions (b0→b2, b1→b0, b2→b1), so positional deterministic keys change. Conditions: `det_shift` (positional keys), `wal`, `baseline`.
- **E2b (content shift):** recovery rewords tool targets via an invertible paraphrase (`finding-r0-b0` → `finding_r0_b0_rpl`); content-hash keys change. Scoring canonicalizes targets (reword-invariant business identity). Conditions: `det_content` (content-hash keys), `wal` (canonicalized lookup).

**Results.**
- E2a `det_shift`: 46 duplicates, 46 missing, 14/60 exactly-once (BREAKS). Mechanism verified: same logical effect `('record_finding','finding-r0-b1')` committed with key `...:r0:b1:e0` (fresh) then `...:r0:b0:e0` (recovery, branch rotated) → receiver sees new key → duplicate.
- E2b `det_content`: 92 duplicates, 0 missing, 14/60 exactly-once (BREAKS). Mechanism verified: `('record_finding','finding-r0-b1')` with `ch:3de5…` (fresh, original target) then `ch:ab7f…` (recovery, reworded target `finding_r0_b1_rpl`) → duplicate.
- `wal`: 0 duplicates, 0 missing, 60/60 exactly-once in BOTH (HOLDS; E2b via canonicalized lookup).

**Paper implication.** This is the boundary characterization: deterministic keys are stable only if the recovery replanning preserves the exact identity derivation (same positions, same argument strings). Any replanning that shifts positions or rewords arguments breaks them. The WAL's claim log is the mechanism that preserves identities across replanning. This directly answers the reviewer's "identities change across recovery" case.

**Verdict vs reviewer ask:** PASS.

---

## E3 — Scale measurements

**Question.** Does the ~1% overhead claim hold as fan-out, concurrency, and log length grow?

**Design.**
- **E3a:** fan-out N_BRANCHES ∈ {2, 4, 8}, wal condition, 30 eps each. Measures dup rate, completion, e2e latency, recovery time.
- **E3b:** claim-log microbenchmark, N ∈ {100, 1000, 10000} claims. Measures append p50/p99, `find_by_identity` latency, `load()` time.
- **E3c:** concurrent workflows (planned; pending E3a completion to avoid overload).

**Results.**
- E3b: append p50 flat at ~0.028ms (100→10k claims; append-only O(1) holds). `find_by_identity`: 6.6ms @100 → 16.8ms @1k → 850ms @10k (O(n) linear scan + full re-parse per lookup). `load()`: 0.79s @10k.
- E3a: fan-out 2/4/8 all 30/30 exactly-once, 0 duplicates, 0 missing. WAL scales cleanly.
- E3c: K=1: 689 ops/s, p50 1.3ms; K=4: 636 ops/s, p50 5.4ms; K=16: 310 ops/s, p50 11.2ms, p99 1055ms. Server serializes at high concurrency.

**Paper implication.** The ~1% overhead claim holds at experimental scale (claim append is O(1), <0.03ms; fan-out 2→8 no degradation; K≤4 modest impact). Two honest caveats: (1) `find_by_identity` is O(n), 850ms at 10k claims — needs an index for production; (2) the tool server (single-threaded HTTP) degrades at K=16 — needs a concurrent server for production. Neither blocks the paper (experiments stay well under these limits).

**Verdict vs reviewer ask:** PASS with caveats.

---

## E4 — Fencing trace analysis (reviewer §4)

**Question.** Show an offending trace: for each duplicate under no-fencing, log claim identity, key, epoch, and the receiver's decision; separate (a) delayed same-key requests from (b) surviving writers creating fresh keys.

**Design.** Instrumented re-run of the sandbox `no_fencing` condition (200 eps): tag each duplicate by whether the offending key was seen before (type a: same-key retry) or is fresh (type b: zombie new key).

**Result.** 102/200 episodes with duplicates (0.51). **102/102 offending calls were type (b) — surviving-zombie fresh keys; 0 were type (a).** Worked trace: fresh commits `(action,target)` with `det:` key at epoch 0; the zombie (killed mid-fanout, never observed the fence bump) retries with a fresh `ch:` key (content-hash over reworded args) at stale epoch 0 < 1; the receiver, seeing an unseen key and no epoch check, accepts → semantic duplicate. The recovery's same-key retry (type a) was correctly suppressed by the idempotent receiver in all cases.

**Paper implication.** The ~49% no-fencing duplicates are *not* a failure of idempotency — the receiver correctly suppresses delayed same-key retries. They are surviving writers minting fresh keys outside the fenced epoch, which no key-based deduplication can catch. This is the causal evidence the reviewer asked for, and it justifies fencing as load-bearing (not belt-and-braces).

**Verdict vs reviewer ask:** PASS.

---

## Spend

$0.00 total. All experiments scripted/local (deterministic rewording, no LLM calls).
(The $5 cap for LLM rewording was not needed — the invertible paraphrase is a faithful, deterministic stand-in, and the mechanism under test is key-identity, not paraphrase quality.)
