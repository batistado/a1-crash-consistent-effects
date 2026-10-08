# A1 Phase 7 — Response to Third Private Review (2026-10-08)

One focused revision before TPDS; no new experiment campaign (per reviewer).
$0 API. PDF: 14pp, 0 LaTeX errors, 0 unresolved references.

## Reviewer point 1 — Key–identity invariant preservation (pp. 4–7, Definition 3)

- **Added create-or-reuse claim creation** (§4, "Claim creation is
  create-or-reuse"): before appending a Claim, H looks up the full
  (action,target,occurrence) triple in L; a durable Claim reuses its
  key (the post-crash retry path); otherwise a fresh unused key is
  minted and the Claim is appended durably *before* any tool call.
  The normal-path step 1 now runs create-or-reuse (was: bare
  "appends Claim").
- **Invariant-preservation argument added**: the lookup-then-append
  ordering means a crash between lookup and append can leave at most
  a durable claim whose key a later attempt will *reuse* — never two
  keys bound to one identity — because claim discipline forbids any
  tool call without a durable claim, so a key that never reached L
  could never have reached T. The occurrence counter is a pure
  function of the durable claims (count per (action,target) pair),
  so no separate counter state can desynchronize across a crash.
- **Guarantee stated as CONDITIONAL**: Theorem 2a (at-most-once)
  now reads "for any crash time and any post-recovery agent
  behavior *that assigns the correct logical identity (occurrence)
  to each attempt*"; mislabeling the occurrence (calling the
  original refund "occurrence 1") presents a new identity the log
  cannot link — stated as the boundary, not a protocol failure.
  The proof's agent-behavior-independence paragraph is qualified
  the same way. FORMAL_MODEL.md updated identically.
- **Trace/test added (E7)**: `langgraph_port/e7_two_refunds_retries.py`
  → `results_e7_refunds.json`. Two separately-authorized refunds to
  the same target commit (2 commits, 2 distinct keys); crash;
  retries of each hit the reuse path and are suppressed (0 new
  commits); a third authorized refund commits as a new identity
  (3 commits total). Invariant audit: one key per identity,
  distinct keys per distinct identity. PASS. Referenced in §4.

## Reviewer point 2 — E2 attribution (p. 9, Table 7)

- E2 paragraph now states explicitly: "E2 evaluates the *combined*
  design — canonicalized identity lookup plus durable key reuse —
  against hashing mutable text; it does not isolate the marginal
  contribution of the log itself, and we do not attribute the
  entire gap to the log alone."
- E1 kept prominent as the boundary: "The E1 result (native
  persistence ties the WAL at 60/60) remains the boundary: where
  stable identities survive recovery, keys alone suffice and no
  new record is needed."

## Reviewer point 3 — Proof/scope cleanup (pp. 5–7)

- **Theorem 1 proof ending** now retains the non-invariance
  condition: "...so — *when the retry-time derivation actually
  changes across an admissible retry* (the theorem's non-invariance
  condition) — no keys-only protocol can rule out the k′ ≠ k case
  in advance." (main.tex + FORMAL_MODEL.md.)
- **L7 aligned with Remark 2**: L7 now reads "Under the
  recovery-information model of §4 (Remark 2), the theorems
  establish the necessity of durable write-ahead identity
  *information* ... Necessity claims in this paper refer to the
  information *under that model*, never the schema, and never
  universally — consistent with Remark 2's scoped modeling claim."
- **Case 3a (arrived-but-not-yet-committed)**: replaced "the
  effect committed exactly on arrival" with the linearization-point
  formulation — (A1) atomicity supplies a linearization point
  *within* the call's processing; either it has linearized
  (replay suppressed) or not (replay commits); exactly one commit
  either way because the key is deduplicated atomically at T.
  Case 3b (dispatched, never arrived) unchanged.
- **"Previous version" paragraph removed** from the Case 4 proof
  and moved here (belongs in the response, not the submitted
  proof): the prior draft asserted Commit(s) ∉ L throughout W(s);
  since t_mark < t_ckpt, the sub-interval [t_mark, t_ckpt) ⊂ W(s)
  already has the Commit durable. The old conclusion held — the
  receiver suppresses by key either way — but the case analysis
  was unsound as written; the Case 3a/3b/4 split repairs it.

## Reporting/layout fixes

- **E5/Table 7**: fault column now "none (paired timing; episodes
  include crash + recovery)"; E5 text states both measured
  intervals — end-to-end wall clock (crash through recovery
  completion) and the instrumented recovery-subprocess interval
  within the same episodes.
- **E4**: §6.4 intro now notes "E4 is the noted exception, a
  sandbox re-run of the no_fencing condition rather than the v2
  harness."
- **Zombie model**: "survives its kill signal" replaced with the
  precise simulation description — with probability 0.5 the
  pre-crash process instance is *not* killed; it survives into the
  post-recovery generation and retries its in-flight step with its
  stale epoch, re-deriving the call as a stale at-least-once agent
  would (fresh content-hash key over possibly reworded args — a
  keyspace the new generation never saw). E4 trace text aligned.
- **Figure 2**: call/recovery labels repositioned (2: call above
  the arrow at pos 0.62; 3: Commit below at pos 0.78;
  reconcile-first above the dashed segment) to clear the boxes.
- **Table 1**: identity cell shortened with \allowbreak in the
  math so the expression no longer spills into the
  receiver-assumptions column.
- **Closest formal neighbor named**: the unnamed "formal-methods
  treatment ... impossibility-style result" is replaced with an
  identifiable citation — Khan's machine-checked (TLA+/TLAPS)
  conformance contract for checkpoint, interrupt, and resume
  semantics (arXiv:2608.03836), distinguished as contract
  (specifies what resume must mean) vs. our mechanism +
  measurement.

## TPDS page cap (reviewer request)

Checked the official IEEE Computer Society TPDS author page
(computer.org, current): regular papers are **12 double-column
pages**; submissions may run **up to 18 pages** subject to
Mandatory Overlength Page Charges (MOPC) after final layout.
Page limits include references and author biographies.
**Verdict**: the 14-page manuscript is submittable as-is but
would incur MOPC. If Mohammed wants to avoid the charges, ~2
pages of tightening would be needed (candidates: compress the
§6.5 methods table, move E7/E6 traces to an appendix).

## Self re-review verdict

All four third-review items ADDRESSED and verified in the built
PDF (text extraction checks on the 14-page PDF, 0 LaTeX errors).
Nothing committed or pushed — awaiting Mohammed's review.
