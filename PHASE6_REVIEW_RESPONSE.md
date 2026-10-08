# A1 Phase 6 — Response to the Second Private Review

**Date:** 2026-10-08 | **Spend:** $0 API (all scripted) | **Status:** COMPLETE, awaiting Mohammed's review (no commit/push per instructions)

The second private review (2026-10-07) found the revision "a meaningful
improvement" but held the TPDS submission on three major blockers.
Each is addressed below with the exact change.

---

## Blocker 1 — Theorem 1's universal step was invalid

**Reviewer:** "Mutable inputs do not necessarily produce mutable outputs.
A function can canonicalize wording or ignore changing plan positions
while preserving the business-operation identifier. The missing condition
is that the key function actually changes across an admissible retry of
the same logical effect."

**Changes (manuscript §5, FORMAL_MODEL.md §3):**
- Theorem 1 now carries the explicit **non-invariance condition**: it
  applies only when two admissible attempts of the *same* logical effect
  produce *different* keys *and* the recovery replan actually changes
  the mutable inputs, with neither key previously used for another
  operation. The proof states the load-bearing point directly: mutable
  inputs alone do not break a derivation — a canonicalizing derivation
  never satisfies k′ ≠ k and is outside the theorem.
- The reviewer's defensible statement is implemented nearly verbatim:
  "If two admissible attempts of the same logical effect produce
  different keys, and neither key was previously used for another
  operation, an atomic receiver that deduplicates only by key can
  commit both attempts."
- **Key collisions between different effects are treated separately**
  (erroneous suppression → missing work), not folded into the duplicate
  argument.
- **E2a reframed as collision→omission** (0.77 dup/ep + 0.77 missing/ep;
  a collision→omission witness with accompanying duplicates) and **E2b
  as re-derivation→duplication** (92 excess commits, 0 missing; the pure
  duplication witness). They are different failure modes, reported
  separately — not one proof.
- The **"necessity proof" contribution heading is REMOVED** (now "A
  mechanism with a scoped necessity argument", per Mohammed's voice
  decision). The Corollary is replaced by a **scoped remark**: durable
  write-ahead identity information is the necessary ingredient *under
  the stated recovery-information model*; the log is a sufficient
  mechanism. Propagated to introduction ("fragile whenever the
  re-derivation actually changes") and conclusion.

## Blocker 2 — The logical identity definition was not implemented

**Reviewer:** "Definition 2 now uses (action, target, occurrence) ...
However: Algorithm 1 still checks (action, target). Table 2 does not
include an occurrence or complete logical-identity field. L4 still
describes (action, target) as the skip identity."

**Changes:**
- **Table 2** (claim-log record format): added the `occurrence` field;
  the logical identity is now stated as
  (action, target, occurrence) with a pointer to Definition 2.
- **Algorithm 1, line 7**: the post-recovery skip check is now on
  (action, target, occurrence).
- **L4**: skip-logic keys on (action, target, occurrence).
- **Positioning table** (Table 1) and **parallel-execution** paragraph:
  same triple.
- **Occurrence provenance** (new paragraph, §4): the harness assigns
  occurrence at claim time as a per-(action,target) sequence counter,
  stored durably in the claim record — it survives crashes exactly like
  the key. On recovery the retry names the occurrence it intends; a
  retry that cannot is an underspecified deployment identity (L4).
- **Key–identity invariant** (new Definition, §5): (i) every logical
  identity has exactly one durable key; (ii) all equivalent attempts
  reuse that key; (iii) distinct accepted identities receive distinct
  keys. Stated explicitly; connects the receiver's key-dedup to the
  theorem's identity-uniqueness.
- **Scope restrictions in the theorem assumptions**: (A6) disjoint
  effect ownership across concurrent workers; (A7) single recovery
  writer per crash. Theorems 2 (at-most-once) and 3 (eventual
  commitment) now assume (A1)–(A7).
- **Implementation updated**: `claim_log.py` (`append_claim` takes
  `occurrence`, `find_by_identity(action, target, occurrence)`, new
  `next_occurrence` counter); `agent_graph.py` (v1) and
  `agent_graph_v2.py` (v2, escalation + worker claim nodes) thread
  occurrence through.
- **New tests** (`langgraph_port/e6_identity_tests.py`,
  `results_e6_identity.json`): (a) suppression of equivalent retries —
  same logical identity incl. occurrence retried after simulated crash
  → exactly 1 commit, retry skipped, durable key reused — **PASS**;
  (b) two distinct authorized effects sharing (action, target) with
  different occurrences → both execute, 2 commits, distinct keys —
  **PASS**; plus a demonstration that the old (action,target)-only
  logic would have collapsed them — **PASS**.

## Blocker 3 — Experiments need methodological detail

**Reviewer:** "E1 is reported without a clear description of the native
workflow, checkpoint configuration, task boundaries, or key persistence.
E2 lacks a sufficiently explicit account of the transformations and how
the WAL recognizes the original identity. E4 reports 102 rejected calls
without showing whether they carry original keys, fresh keys, or newly
created claims."

**Changes (new §6.5 "Boundary experiments: methods and results", new
Table 8):**
- Compact results table: for E1/E2a/E2b/E3/E4/E5 — baseline,
  identity/key rules, injected fault, episode count, duplicate-episode
  count, missing-effect rate, completion.
- **E1**: native workflow (LangGraph SqliteSaver, no claim log, no
  manual recovery node), checkpoint configuration (framework superstep
  checkpoints via re-invoke with None input + thread id), task
  boundaries (graph-node supersteps), key persistence (checkpointer's
  own durable state), matched crash schedule/receiver. 60/60.
- **E2**: E2a's branch-rotation and E2b's invertible paraphrase spelled
  out; the WAL's recognition mechanism described
  (`find_by_identity` on the durable (action,target,occurrence) record,
  canonicalized lookup in E2b, original-key replay).
- **E4**: full representative trace (episode 0) showing the fresh
  commit, the correctly suppressed same-key recovery replay, and the
  zombie's fresh-key stale-epoch commit; **overlapping generations
  identified as a separate fault model** from crash-stop (also
  reconciled in §7's ablation intro).
- **E5**: "no measurable claim-log overhead" **replaced** with the
  honest wording — measured +0.38s, 95% CI [-0.08, +0.83], inconclusive
  about a difference, does not establish negligible overhead. **CI
  method specified**: 95% CIs on paired per-episode differences, mean ±
  1.96×SE, n=20, seed-matched pairing verified (0/60 plan-seed
  mismatches; recomputed from `results_e5p_*.json`).

## Related-work corrections

- **LogAct**: corrected to its stated single-agent safety/fault-tolerance
  focus; distinguished via our atomic receiver contract + harness-crash
  recovery guarantee (which LogAct neither specifies nor measures).
- **Temporal**: now accounts for LLM invocations as Activities outside
  the deterministic replay path with durably recorded results; explains
  what the mechanism adds (the harness-side commit→checkpoint window,
  at tool-effect granularity).
- **LIMBO**: Table 1 "no exact-once proof" → "does not establish the
  harness-crash recovery guarantee (Prop. 2 gives conditional
  exactly-once for same-key reuse)".

## Integration / PDF fixes

- p2 contribution list: "1.000 exactly-once in every campaign" →
  scoped (all campaigns except gpt-4o-mini loose 66/70; tight: 70/70).
- Table 1 receiver row: "returns original result on duplicate" →
  "returns `duplicate_suppressed` status only" (matches the design).
- At-most-once proof Case 3: split into 3a (call arrived → atomic
  commit) and 3b (dispatched-but-uncommitted → first arrival on
  replay); call arrival ≠ commitment.
- "Theorem 2a" → "Theorem 2" (manuscript numbering).
- §9 (Limitations): added the promised **original-result recovery**
  and **concurrent recoveries** discussions (were absent).
- 180/214: limitations now say "214/214 decisions (180 episodes)".
- Figure 2: staggered the 1/2/3 labels (were overlapping).
- Table 7 (ablation): restored the missing `\caption`.
- Table 6 (crashpoints): clarified distributions matched across
  *campaigns* not *conditions*; cross-condition comparisons unpaired.
- New boundary table placed with its methods discussion.

## Self re-review verdict

All three blockers addressed; every reviewer-required change has a
matching edit above. PDF: 14 pages, **0 LaTeX errors**, 0 unresolved
references. New tests: 3/3 PASS. $0 API spend. Ready for Mohammed's
review → resubmit decision.
