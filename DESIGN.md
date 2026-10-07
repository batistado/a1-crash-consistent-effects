# A1 Design Document — Crash-consistent checkpointing for exactly-once agent effects

## 1. Hypothesis

Agent execution harnesses checkpoint *trajectories* (token prefixes, planner
state), not *effect commitments*. There exists a **checkpoint window**: the
interval between a tool-effect commit and the harness checkpoint write. A
harness-process crash landing in this window leaves durable state claiming
"step not done" while the real world has already felt the effect; the resumed
agent re-fires the tool, producing a duplicate side effect.

Idempotency keys — the standard fix — are insufficient *in general* because
the retry must present the *same* key, and a recovered LLM agent does not
reliably re-derive it:
- content-hash keys (`sha256(action, args)`) break when the agent rewords
  arguments on retry (observed in the wild; cf. engineering reports);
- deterministic position keys (`(workflow_id, step_index, action)`) break
  when recovery replanning changes plan structure (inserted diagnostic steps
  shift indices).

**Claim.** A write-ahead *effect-claim log* — durably logging `(claim, key)`
*before* invoking the tool, fencing checkpoint advance behind log commits,
and fencing stale writers with an epoch — makes recovery reconcile-first
(replay each uncommitted claim with its *original* key) and achieves
exactly-once regardless of how the recovered agent re-derives keys.

## 2. Protocol specification

**Roles.** Harness H (crash-prone), Tool T (atomic idempotent receiver:
check-key and commit-effect are atomic; durable across H crashes), durable
Log L, durable Checkpoint C.

**Normal path** (effectful step s with deterministic key k):
1. H appends `CLAIM(wid, s, k, args, epoch)` to L. *(write-ahead)*
2. H invokes `T.call(k, epoch, args)`.
   - T rejects if `epoch < max_epoch[wid]` (stale writer fencing).
   - T returns `duplicate_suppressed` if `k` seen; else commits effect,
     records `k`, returns `committed`.
3. H appends `COMMIT(s)` to L, then advances C past s.
   - C may only advance past steps with COMMITs in L *(log-fenced checkpoint)*.

**Recovery path** (H restarts; only L and C survive):
1. `epoch ← epoch + 1`.
2. Reconcile: for each `CLAIM` without a matching `COMMIT` in L, re-invoke
   `T.call` with the claim's **original** key and the new epoch. T's
   idempotent receiver dedups if the pre-crash call committed; executes if
   it never arrived. Mark COMMIT on success.
3. Advance C past all COMMITted claims.
4. Resume the agent from C; the agent's replanned steps are checked against
   L by semantic claim identity `(action, target)` before any new claim is
   issued, so reworded/shifted retries of already-claimed effects are
   skipped, not re-executed.

**Necessity argument (for the paper).** Keys alone push *all* of recovery
correctness into the key presented at retry time, which the harness cannot
control once the agent re-plans. The log moves the source of truth from the
agent's re-derivation to durable, pre-crash claims — the standard
write-ahead-logging argument, applied to the harness/tool boundary. The
checkpoint window is distinct from LIMBO's late-commit window: it is a
harness-side crash-consistency gap, not a service-boundary timing gap.

## 3. Fault model

- Benign crash faults only (chaos-style, HPC checkpoint/restart tradition).
- The fault under study: H process crash at a randomized effectful step, with
  landing distribution — 75% **in-window** (after T commit, before C write),
  15% post-checkpoint (safe), 10% pre-tool-call (safe).
- T is reliable and atomic (same idealization LIMBO uses for the tool
  contract); the study isolates harness-side crash consistency.
- Recovery replanning nondeterminism: P(reword args) = 0.5, P(plan shift) =
  0.3, modeling LLM re-synthesis after restore (cf. ACRFence's observation
  that restored LLMs re-synthesize subtly different requests).

## 4. Conditions and metrics

| Condition | Mechanism |
|---|---|
| (i) baseline | resume-from-checkpoint, no keys |
| (ii-a) | + content-hash idempotency keys |
| (ii-b) | + deterministic `(wid, step, action)` keys |
| (iii) | + write-ahead claim log, log-fenced checkpoints, fencing epoch |

1500 episodes/condition, seeded RNG (seed recorded in `results.json`).

Metrics per condition: **duplicate-effect rate** (episodes with ≥1 duplicate
committed effect), **exactly-once rate** (all intended effects committed
exactly once, none missing/duplicated), mean duplicates/episode. Also
recorded: crash-landing fractions (verifying the window is actually
exercised), and a zombie-probe count (stale-epoch calls the tool rejected)
for condition (iii).

Expected: (i) duplicates ≈ in-window rate (~0.75); (ii-a) ≈ 0.75 × 0.5
(~0.375, reworded retries); (ii-b) ≈ 0.75 × 0.3 (~0.225, shifted plans);
(iii) ≈ 0.0 with exactly-once ≈ 1.0.

**Deliberate scoping decision.** The tool's idempotency-key store is scoped
per workflow. Unscoped content-hash keys have a *second*, distinct failure
mode — cross-workflow collisions when two unrelated workflows issue
byte-identical (action, args) — which the sandbox initially reproduced as
spurious "missing" effects. That hazard is real (and worth a sentence in the
paper's related work), but it is not the failure mode under test, so keys
are workflow-scoped to isolate the reword/shift failure modes cleanly.

## 5. Overlap verdict (second-pass, 2026-10-07 — PASS)

Full report: `~/workspace/research_notes/agent-systems-research-ideas-20261007-0317/a1-overlap-verification.md`.

- **LIMBO** (arXiv:2609.29095, Microsoft): the landmark on exactly-once for
  agents. 12 fault modes, all *service-boundary*; idempotency keys cut
  duplicates 28%→4%. Full text: zero mentions of "crash"/"write-ahead".
  Does not cover harness-process crashes or the checkpoint window. Cite as
  foundation; A1 extends its "where should exactly-once live" framing to the
  harness side.
- **ACRFence** (arXiv:2603.20625): checkpoint-restore duplicates via
  *adversarial* rollback; replay-or-fork mitigation. Nearest neighbor in
  checkpoint-restore space; different threat model and mechanism. Cite
  prominently as complementary.
- **AgentRewind** (arXiv:2608.14380): backward undo for context/workspace;
  explicitly cannot undo external effects. Different direction.
- SagaLLM-family / Temporal / DBOS: compensation or workflow durability, not
  the crash-window duplicate gap for agent harnesses.
- Engineering folklore (agent-crashbench roadmap "intent journal", eidentic
  design doc, blog guides): closest formulations, but no paper and no
  measurement. The paper's contribution is the formalization + correctness
  argument + controlled measurement — acknowledge folklore as motivation.

## 6. Journal fit

**IEEE Transactions on Parallel and Distributed Systems (TPDS) — Q1**
(confirmed: OOIR #10/97 CS Theory & Methods, #33/252 Engineering E&E).
Crash consistency, exactly-once processing, write-ahead logging, and fencing
are TPDS's native vocabulary; the paper shape (protocol + correctness
argument + fault-injection evaluation) mirrors LIMBO's formal+empirical
style. Backup: ACM TOCS. If framed as harness reliability engineering:
IEEE TSE.

## 7. LLM-in-the-loop validation (STUB — needs separate spend approval)

The scripted sandbox proves the mechanism with zero API spend. The paper
also needs a small LLM validation: a real model (small/cheap tier) driving
the harness through the same protocol on a subset of episodes, confirming
(a) the agent actually emits and honors the claim-log discipline, and
(b) measured reword/shift rates on recovery resemble the simulated ones.
Do NOT run this until the user approves API spend. Stub location: a future
`src/llm_validation.py`.
