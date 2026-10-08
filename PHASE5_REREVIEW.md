# A1 Phase 5 — Self Re-Review vs. Reviewer Feedback (2026-10-08)

Walk of the six major concerns + reporting corrections against the revised
manuscript (main.tex, 11pp, 0 LaTeX errors) and FORMAL_MODEL.md.
Verdict scale: ADDRESSED / PARTIALLY / OPEN.

## Major concern 1 — Theorem 1 overclaims → ADDRESSED
- Theorem renamed "Retry-time key fragility", domain narrowed to derivations
  from *mutable* retry-time inputs (rewordable args, shiftable positions).
- New Scope remark: durable business-operation IDs (RIFL-style, payment IDs)
  are explicitly outside the theorem — the reviewer's counterexample answered.
- Corollary retitled "Durable identity information"; 2.2(b) adopted: the
  *information* is necessary, the append-only log is a *sufficient* mechanism
  (L7 in both files). Conclusion softened consistently ("minimal requirement",
  not "minimal structure").
- E2a/E2b cited as empirical witnesses (46/60 breaks each); v2/E1 stable-
  identity ties framed as the boundary illustration.

## Major concern 2 — Theorem 2 conflates safety/completion → ADDRESSED
- Split into 2a (at-most-once/safety), 2b (eventual commitment under P1–P3),
  2c remark (workflow completion is policy-dependent; 66/70 labeled an
  empirical rate under the gpt-4o-mini policy, not a liveness proof).
- Logical effect identity defined (stability/discrimination/retry-equivalence;
  default (action,target,occurrence)); stated as a deployment modeling
  assumption, not a theorem.
- Proof inconsistency fixed: six-case split at every durability boundary;
  Case 4 repairs the Commit-durable/checkpoint-not-advanced sub-case.
- Abstract, contributions, conclusion, §6 all use the safety/completion split.

## Major concern 3 — Strong baseline gap → ADDRESSED
- E1: native persistence (SqliteSaver + deterministic keys) ties WAL 60/60 —
  reported as the boundary result, not hidden.
- E2a/E2b: identity shift breaks deterministic keys (46/60 dup episodes each,
  plus lost effects in E2a); WAL holds 60/60 both. This is now the paper's
  central empirical claim, and Theorem 1's narrowed domain predicts it.
- Temporal comparison corrected via the RIFL/ARIES/durable-execution rewrite.

## Major concern 4 — Fencing causal evidence → ADDRESSED
- E4: 102/102 offending calls are class b (surviving-zombie fresh keys at
  stale epoch); 0 class a (same-key recommit correctly suppressed). Cited in
  the proof's stale-writers case and §6.

## Major concern 5 — Related work → ADDRESSED
- LogAct characterization corrected (concedes crash recovery + old-driver
  fencing; re-grounds distinction in shared-bus vs per-harness).
- ACRFence overlap named explicitly; LIMBO 4% attribution narrowed to the
  service boundary; paper renamed to Li's "Where Does Exactly-Once Live?"
- RIFL (SOSP'15), ARIES (TODS'92), Sagas (SIGMOD'87) added with precise
  positioning; 4 bib entries corrected (no more "Anonymous").
- 10-row comparison table added (fault model × records × identity × receiver
  × fencing × guarantee × evaluation).

## Major concern 6 — Protocol spec gaps → ADDRESSED
- 3.1: epoch acquisition/ownership/atomicity specified; honest boundary:
  single-recovery-writer assumed, CAS-at-T specified as the fix.
- 3.2: duplicate responses are status-only (honest gap: result-return is
  specified future work, paper must not claim otherwise). The 1.3 RIFL
  paragraph was corrected at merge to remove the false "original-result
  return" claim.
- 3.3: torn-tail discipline documented; silent-skip and no-checksum gaps named.
- 3.4: parallel frontier specified (per-branch done-files, log-fenced
  recomputation); honest gap: concurrent equivalent claims not serialized —
  paper scopes to disjoint ownership.
- 5-item gap register in the Limitations section; net guarantee stated as:
  exactly-once under crash-stop + single recovery writer + disjoint parallel
  effect ownership + status-only idempotency.

## Reporting corrections → ALL ADDRESSED
- 140 vs 210, 214 vs 180, duplicate-rate definitions, 20.3ms definition,
  $0.114 spend correction, uncertainty bounds (4.87%/0.20%), Algorithm 1
  line refs, float specifiers, table captions, visual pass (0 errors).

## Remaining honest limitations (in the paper, not hidden)
- Paired end-to-end latency CLOSED (E5p): wal vs deterministic +0.38s
  (95% CI [-0.08,+0.83], n=20, n.s.); wal vs native -1.92s
  (95% CI [-2.96,-0.88]) — claim log adds no overhead vs keys, beats native
  resume. Recovery time: wal 5.30s vs det 5.43s vs native 6.75s (dominated by
  workflow re-execution, not reconciliation). All 60: 0 dups, 60/60 eo.
- Throughput: E3c (688/636/310 ops/s; p99 1055ms at K=16 — server serializes).
- Claim-log find_by_identity is O(n) (850ms @10k) — indexing is follow-up work.
- 2.2(b) decision taken per agent recommendation; Mohammed can flip to (a)
  (4 specs would revert).

## Overall verdict
All six major concerns are addressed with honest scoping. The paper's central
contribution is now the boundary characterization the reviewer suggested:
"durable write-ahead identity information is necessary; deterministic keys
suffice under stable identities and fail under identity shift; the claim log
is the evaluated sufficient mechanism." Ready for Mohammed's review; the
remaining gate is his 2.2(a)/(b) decision and a final read of the PDF.
