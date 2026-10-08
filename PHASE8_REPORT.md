# A1 Phase 8b — Six Small Corrections + Khan Integration + Re-trim (2026-10-08)

**Task:** Apply the fourth private review's six small corrections, integrate Phase 8a's verified Khan corrections (verdict: CONFIRMED), and re-trim to ≤12 pages. $0 API. Nothing committed or pushed — Mohammed reviews first.

## Six corrections (each → change made)

1. **§5.4 L7 (p.7) — necessity wording.** Was: "the theorems establish the necessity of durable write-ahead identity information." Now: "Theorem~1 establishes conditional key fragility, and the model makes durable write-ahead identity information a requirement *within that model*—a scoped claim, never universal, and not uniqueness of the append-only log schema." Consistent with Remark 2.
2. **§8 Discussion (p.10) — identity-stability qualification.** The "recovery independent of which side of the boundary" and "composes with arbitrary agent cognition" claims are now qualified: "provided the recovered agent assigns the correct logical identity (occurrence) to each retry, as Theorem~2 requires" and "arbitrary agent cognition *that honors the identity contract*."
3. **At-most-once proof (p.7) — linearization.** Was: "(the replayed key is the first to arrive and commits)." Now: "(whichever valid attempt linearizes first commits—the replay need not be the first to arrive)."
4. **Table 7/8 E5 injected-fault cell.** Was: "none (paired timing; episodes include crash + recovery)." Now: "in-window crash (paired timing; episodes include crash + recovery)."
5. **Figure 2 (p.5) — redraw.** The "2: call($k$, epoch)" arrow previously crossed straight through the claim-log box (the reported overlap). Re-routed below the boxes: `(h.south) -- ++(0,-0.7cm) -| (t.south)` with the label above the wire, clear of all boxes and of the "stale epochs rejected" note.
6. **E3b (p.9) — fsync disclosure.** The ~0.03ms append p50 **includes** a per-record `fsync` (`ClaimLog.append_claim` fsyncs every record); the manuscript now says so and notes the p99 of 8–20ms is the fsync latency tail. (Verified in `src/e3b_log_scale.py` → `claim_log.py:41` `os.fsync`.)

## Khan integration — status: INTEGRATED FROM VERIFIED SOURCE (Phase 8a, CONFIRMED)

KHAN_VERIFICATION.md (Phase 8a) confirmed the reviewer's correction against Khan v3 (8 Aug 2026, 25pp): §VI has live-agent probes on five frameworks; §VII is REMIT, a reference resume sequencer with append-only effect ledger. Integrated the verified LaTeX-ready text:
- **§2.3:** full corrected paragraph — 39-cell fault matrix, five pinned frameworks, REMIT mechanism (⟨branch,task,effectId⟩ records tx with checkpoint, per-thread sequencer, Verus-verified core, PyPI), and the precise distinction: REMIT sequences at the checkpoint interface with in-harness dedup vs our pre-invocation claim with receiver-boundary reconciliation.
- **"Contract and mechanism" sentence:** replaced with "Where Khan's contract specifies what resume must mean and Remit demonstrates checkpoint-interface enforcement, we address the pre-invocation window and receiver-boundary reconciliation: complementary mechanisms at different points of the crash window."
- **Table 1 Khan row:** completed all 8 columns (effect ledger, branch keying, skip-iff-recorded + consume-claim gate, sequencer order, TLA+/TLAPS + Verus, 39-cell matrix + 5-framework live measurements).
- **§2.4 novelty claim:** re-scoped — "no prior work combines the benign commit→checkpoint crash window under a re-planning LLM agent, a write-ahead effect-claim log recorded *before* invocation (Remit's ledger records at checkpoint time), receiver-boundary reconciliation via original-key replay under fencing epochs (Remit dedups inside the harness)…"

Per the verification caution: no claim that Remit "cannot see" any window — the text sticks to the stated design difference throughout. No bib change needed (khan2026resume already cites arXiv:2608.03836).

## Re-trim: 13pp → 12pp

The Khan additions cost ~1 page. Recovered via: §2.3 paragraph tightened (facts kept), §2.4 novelty claim tightened, Table 1 Khan row cells shortened, L7 + Discussion paragraphs tightened ~3 lines. (An attempted `\bibsep` reduction broke the bibliography with 34 errors — reverted; the prose tightening sufficed.)

| Metric | Before (Phase 7+fixes) | After |
|---|---|---|
| Pages (pdfinfo) | 13 | **12** |
| LaTeX errors | 0 | 0 |
| Six corrections | — | all verified in built PDF |
| Khan passages | fallback (pending verification) | verified text integrated |

**Verdict:** PASS — all six corrections + verified Khan integration, 12pp TPDS-regular limit met, 0 errors, all reviewer-required content intact (verified via pdftotext: create-or-reuse, non-invariance, occurrence, 66/70, separately-authorized refunds, Table 8, E4 trace, E5 interval).
