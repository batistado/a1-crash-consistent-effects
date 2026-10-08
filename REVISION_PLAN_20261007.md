# A1 Revision Plan — Addressing Reviewer Feedback (2026-10-07)

Source: REVIEWER_FEEDBACK_20261007.md (research reviewer LLM, private pre-submission).
Target: IEEE TPDS. Provisional judgment: not ready; substantive revision needed.

## Phase 1 — Writing-only fixes (no new experiments)
*Goal: eliminate credibility damage; every claim matches evidence.*

- [ ] 1.1 Related work: rewrite LogAct characterization (it DOES discuss crash
      recovery §3.2 — current dismissal is inaccurate and must be corrected).
- [ ] 1.2 Related work: ACRFence — acknowledge recovery-mechanism overlap
      (crash-induced restore, effect logging, replay vs changed intent).
- [ ] 1.3 Related work: LIMBO — keep harness-crash distinction, drop the
      overstatement attributing its 4% residual to our theorem.
- [ ] 1.4 Bibliography: add RIFL (Lee et al., SOSP 2015); add foundational
      classical-WAL, durable-execution, sagas entries.
- [ ] 1.5 Bibliography metadata: fix refs [1],[2],[3] titles; replace
      "Anonymous" with public authors in [1],[2],[3],[6].
- [ ] 1.6 Comparison table: fault model × durable records × identity handling ×
      receiver assumptions × fencing × guarantee × evaluation — state the
      precise property our system adds (identity preservation across replanning).
- [ ] 1.7 Safety/completion split EVERYWHERE: abstract, contribution list,
      conclusion, §6 headers. "Zero observed duplicates" (safety, proven) vs
      "workflow completion" (liveness, 66/70 — reported with bounds, not folded
      into "exactly-once 1.000").
- [ ] 1.8 Uncertainty bounds: 0/60 → 4.87% one-sided 95% upper bound; 0/1,500 →
      0.20%. State these describe the experimental distribution.
- [ ] 1.9 Metric reconciliation: campaign counts (140 vs 210 episodes — give
      campaign-level totals, explain reuse/independence); 214/214 vs 180/180
      (episodes vs routing decisions); define both duplicate-rate measures and
      denominators; pin down what 20.3 ms includes (per-step vs write latency);
      fix Algorithm 1 step-4/line-7 reference; repair LaTeX artifacts
      (literal \S, table labels, stranded headings).
- [ ] 1.10 Overhead: replace "~1%" estimate with paired end-to-end latency,
      throughput, recovery time; account for multiple durable writes per step.

## Phase 2 — Theory repair
*Goal: theorems state only what is proven.*

- [ ] 2.1 Theorem 1: narrow to identity-unstable derivations, OR prove the
      information requirement (what persistent info is available at recovery,
      which histories are indistinguishable, why they demand different actions).
      Adopt the defensible statement: "Idempotency keys derived from mutable
      argument text or unstable plan positions cannot guarantee duplicate
      suppression across all admissible recovery replans."
- [ ] 2.2 Claim-log necessity: either prove the log's structure necessary or
      describe it as a sufficient implementation (durable op table / txn
      workflow state could also preserve identity info).
- [ ] 2.3 Theorem 2: define logical effect identity (must distinguish
      legitimate repeats — two authorized partial refunds — and recognize
      equivalent retries across rewording).
- [ ] 2.4 Theorem 2: split into (a) at-most-once per durable claim identity,
      (b) eventual commitment of accepted claims under explicit progress
      assumptions, (c) workflow completion (planning/recovery-policy dependent).
- [ ] 2.5 Fix proof inconsistency: checkpoint window includes post-t_mark /
      pre-t_ckpt where a Commit record already exists — split proof cases at
      Claim durability, tool commitment, Commit durability, checkpoint
      durability.

## Phase 3 — Protocol specification completion
*Goal: implementable from the paper alone.*

- [ ] 3.1 Epoch acquisition, ownership, atomic registration; how epoch is
      recovered and increased atomically.
- [ ] 3.2 Duplicate-call result return: does a duplicate return the original
      result (generated refund IDs/receipts needed downstream)?
- [ ] 3.3 Partially written JSONL records: detection and handling.
- [ ] 3.4 Parallel execution: checkpoint advancement preserving gaps and
      dependencies; serialization of concurrently emitted equivalent claims;
      parallel completion frontier.

## Phase 4 — New experiments
*Goal: demonstrate incremental benefit over strong baselines; nail the boundary.*

- [ ] 4.1 Native-persistence baseline: LangGraph's own checkpointer +
      documented task boundaries + durable operation identities + same receiver
      contract, under matched crash schedules and recovery policies.
- [ ] 4.2 Identity-shift case: the critical missing experiment — identities
      change across recovery (replanning rewords/shifts branches). Expect
      deterministic keys to break here while WAL holds. THIS is the paper's
      central insight (reviewer: Table 4's boundary "could become the paper's
      central insight").
- [ ] 4.3 Scale: fan-out sizes, concurrent workflows, recovery-log lengths
      (modest ranges — connects to distributed-runtime behavior for TPDS).
- [ ] 4.4 Fencing trace: produce the offending no-fencing trace (claim
      identity, key, epoch, receiver decision); separate delayed same-key
      requests from surviving writers creating fresh work; confirm the
      mechanism behind the ~49% duplicates.
- [ ] 4.5 Temporal comparison correction: acknowledge Activities for
      nondeterministic LLM calls; state precisely what durable execution
      handles vs what our setting adds (or drop the comparison).

## Phase 5 — Rewrite and re-review
- [ ] 5.1 Rewrite abstract/contributions/conclusion around the defensible
      central contribution: "a crash-recovery protocol that preserves
      tool-operation identities across agent replanning, with explicit receiver
      assumptions and fault-injection evaluation."
- [ ] 5.2 Full manuscript pass incorporating Phases 1–4; rebuild PDF.
- [ ] 5.3 Re-submit to reviewer LLM for second assessment before TPDS.

## Sequencing note
Phases 1–3 are writing/theory (days). Phase 4 is the long pole (design + run +
analyze new experiments). Phase 5 follows. B1 manuscript review proceeds in
parallel.
