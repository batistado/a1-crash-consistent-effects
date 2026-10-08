# A1 Checklist — the single living checklist (TPDS revision)

One file, updated in place. Newest status goes at the top of each section.
The append-only narrative lives in `RUNLOG.md`. Evidence files (results JSONs,
reports) are referenced, not duplicated here.

## Current status — 2026-10-08 ~01:30 PDT — ✅ manuscript APPROVED; integrity checks PASS; release in progress (NOT yet public)
- Mohammed APPROVED the final Phase 9 manuscript (12pp, 0 LaTeX errors, all reviews addressed).
- CORRECTION (2026-10-08 ~01:30 PDT): the 00:07 entry below overstated the state — Phase 9 was NOT pushed and neither GitHub nor HF was made public at that time. Actual state then: all local, awaiting pre-submission integrity checks.
- Pre-submission integrity checks COMPLETE: Paperpal similarity 1% (PASS); IEEE AI disclosure added to manuscript (wording approved by Mohammed), re-trimmed to 12pp, 0 LaTeX errors. Cache-busted final: manuscript/a1-phase9-ai-disclosure-12pp.pdf (verified: 12pp, acknowledgment present).
- In progress: commit + push Phase 9 → upload Phase 9 artifacts to HF → make GitHub + HF PUBLIC (verify each) → arXiv post (Mohammed's account; endorsement may be needed) → TPDS ScholarOne submission.
- Cover letter drafted (manuscript/cover-letter-tpds-draft.md); submission metadata ready (manuscript/submission-metadata.md); Word conversion ready (manuscript/a1-phase9-12pp.docx).

## Current status — 2026-10-08 — Phase 9 COMPLETE (fifth review addressed, 12pp, awaiting Mohammed)
- Fifth review (2026-10-07): substance ready; final typesetting pass only. All 5 items ADDRESSED 2026-10-08: Table 2 wrapped/constrained; Figure 2 redrawn (zero overlaps, verified on PNG); Figure 1 rescaled (no gutter bleed); artifact-availability paragraph restored; "three theorems". Incidental: 3 more spilling tables fixed (tab:llm/v2/crashpoints).
- Author list finalized per Mohammed: 5-author IEEEtran block (AUTHORS.md) with affiliation superscripts + emails; running head "Syed et al.".
- 13pp → 12pp via prose tightening only; 0 LaTeX errors; pp. 1, 4–6, 9–12 visually verified. Report: PHASE9_REPORT.md. Share copy: manuscript/a1-phase9-12pp.pdf. NOT committed/pushed (Mohammed reviews first).
- Next: Mohammed's review → push → TPDS submission.

## Previous status — 2026-10-08 — Phase 8b COMPLETE (fourth review addressed, 12pp, awaiting Mohammed)
- Fourth review (2026-10-07): best yet — short final pass, no new experiments. Phase 8 ran as 2 parallel workers: 8a Khan verification → CONFIRMED (reviewer right); 8b six small corrections + verified Khan integration + re-trim.
- 8b DONE 2026-10-08: all six corrections applied + verified in PDF (L7 scoped wording, §8 identity-contract qualification, linearizes-first, E5 in-window crash, Figure 2 redrawn, E3b fsync disclosed); Khan passages replaced with verified text (§2.3, Table 1 row, §2.4 novelty claim, contract/mechanism sentence); 13pp → 12pp, 0 LaTeX errors. Report: PHASE8_REPORT.md. NOT committed/pushed (Mohammed reviews first).
- Next: Mohammed's review → push → TPDS submission decision.

## Previous status — 2026-10-08 — Phase 7 COMPLETE (third review addressed, awaiting Mohammed)
- Third review (2026-10-07): genuinely new 14pp revision confirmed. All 4 remaining items ADDRESSED 2026-10-08: (1) create-or-reuse algorithm + invariant-preservation argument + conditional guarantee + E7 trace/test PASS (2 refunds + retries, 3 commits, invariant audit clean); (2) E2 as combined-design evaluation, E1 kept prominent; (3) proof/scope cleanup (Theorem 1 ending, L7 vs Remark 2, linearization-point Case 3a, previous-version paragraph → response file); (4) reporting/layout fixes (E5 timing, E4 sandbox note, zombie description, Figure 2, Table 1, Khan formal-neighbor citation, TPDS page cap: 12pp regular, up to 18pp with MOPC — 14pp submittable with charges).
- PDF: 14pp, 0 LaTeX errors, self re-review verified in built PDF. Report: PHASE7_REVIEW_RESPONSE.md. NOT committed/pushed (Mohammed reviews first).
- Next: Mohammed's review → resubmit decision.

## Previous status — 2026-10-07 ~22:20 PDT — Phase 7 QUEUED (third review: one focused revision before TPDS)
- Third private review (2026-10-07): genuinely new 14pp revision confirmed; most blockers resolved. Remaining: (1) create-or-reuse algorithm + invariant-preservation argument + conditional guarantee + two-refund trace/test; (2) E2 as combined-design evaluation, E1 kept prominent; (3) proof/scope cleanup (Theorem 1 ending, L7 vs Remark 2, arrived-but-uncommitted, drop "previous version" paragraph); (4) reporting/layout fixes (E5 timing, E4 sandbox note, zombie description, Figure 2, Table 1, formal-neighbor citation, TPDS page cap).
- Mohammed (voice): Phase 7 authorized on all points; RUNLOG checkpoint + checklist + GitHub push first.
- Next: Phase 7 agent work → PDF rebuild → resubmit decision.

## Previous status — 2026-10-07 ~21:05 PDT — Phase 6 COMPLETE (second review addressed, awaiting Mohammed)
- Second private review (2026-10-07): meaningful improvement, HOLD submission. All 3 blockers ADDRESSED 2026-10-08: (1) Theorem 1 non-invariance condition + E2a/E2b reframed as distinct failure modes + necessity heading REMOVED (scoped remark); (2) (action,target,occurrence) unified across Algorithm 1/Table 2/L4/theorems + key↔identity invariant + (A6)/(A7) + E6 tests 3/3 PASS; (3) §6.5 methods subsection + Table 8, E4 trace, honest E5 interval + CI method, related-work fixes (LogAct/Temporal/LIMBO), all PDF fixes. PDF: 14pp, 0 errors. Report: PHASE6_REVIEW_RESPONSE.md. NOT committed/pushed (Mohammed reviews first).
- Next: Mohammed's review → resubmit decision.

## Previous status — 2026-10-07 ~19:53 PDT
- Phases 1–3 revision DRAFTS complete and PUSHED (8b6d9e9): PHASE1_REVISIONS.md (750 lines, incl. 4 corrected bib entries + 2 new discrepancies found: API spend $0.1137 not "under $0.10"; paired e2e latency never measured), PHASE2_REVISIONS.md (Theorem 1 narrowed, Theorem 2 split 2a/2b/2c, 2.2 → option (b) recommended), PHASE3_REVISIONS.md (protocol spec + 5-item honest gap register).
- Phase 5 COMPLETE 2026-10-08: all revisions applied to main.tex + FORMAL_MODEL.md; 2.2 = option (b); paired-timing gap closed (wal vs det +0.38s n.s., wal vs native -1.92s); PDF rebuilt (11 pp, 0 errors); self re-review: all 6 concerns ADDRESSED. Pushed f401921.
- Next: Mohammed's review (2.2 confirmation + PDF read) → resubmit decision.


## Reviewer feedback summary (2026-10-07, research reviewer LLM, private pre-submission)
Verdict: NOT READY for TPDS — claims exceed evidence; empirical foundation useful.
1. Theorem 1 overclaims: proves 2 key schemes fail, not universal insufficiency; claim-log necessity unproven. → narrow to identity-unstable derivations or prove the information requirement.
2. Theorem 2 conflates safety (0 duplicates, proven) with completion (66/70, not proven); semantic identity underspecified. → split at-most-once / eventual-commitment / workflow-completion; define logical effect identity.
3. Strong-baseline gap: v2 deterministic keys tie WAL (0.0000/1.0000); no native-persistence baseline; Temporal comparison too restrictive. → E1 + E2 + scale (E3).
4. Fencing ablation needs causal mechanism (~49% dups without fencing). → E4 (done, mechanism = surviving-writer fresh keys).
5. Related-work errors: LogAct DOES discuss crash recovery (§3.2); ACRFence overlap understated; LIMBO 4% attribution overstated; missing RIFL (SOSP 2015) + classical WAL/durable-execution/sagas; "Anonymous" for public authors; wrong titles [1],[2],[3],[6]. → comparison table + bib fixes.
6. Protocol spec gaps: epoch atomicity, duplicate-call result return, partial JSONL writes, parallel checkpoint frontier, proof inconsistency (Commit exists in-window but proof assumes absent).
Reporting: safety/completion split everywhere; reconcile 140 vs 210 eps, 214 vs 180 decisions; define duplicate-rate denominators; pin down 20.3 ms overhead; uncertainty bounds (0/60 → 4.87%, 0/1,500 → 0.20%); fix Algorithm 1 refs + LaTeX artifacts.
Suggested central contribution: "a crash-recovery protocol that preserves tool-operation identities across agent replanning, with explicit receiver assumptions and fault-injection evaluation."

## Phase 1 — Writing / related-work / reporting fixes
**Status: APPLIED 2026-10-08** — all items merged into main.tex (Phase 5).
- [x] 1.1 LogAct characterization corrected (it discusses crash recovery §3.2)
- [x] 1.2 ACRFence overlap acknowledged; LIMBO 4% attribution narrowed
- [x] 1.3 Add RIFL (SOSP 2015) + classical WAL / durable-execution / sagas citations
- [x] 1.4 Bib metadata: fix titles [1],[2],[3]; replace "Anonymous" with public authors [1],[2],[3],[6]
- [x] 1.5 Comparison table: fault model × durable records × identity handling × receiver assumptions × fencing × guarantee × evaluation
- [x] 1.6 Safety/completion split in abstract, contributions, conclusion, §6
- [x] 1.7 Reconcile counts: 140 vs 210 eps; 214 decisions vs 180 eps; duplicate-rate definitions + denominators; 20.3 ms overhead definition
- [x] 1.8 Uncertainty bounds: 0/60 → 4.87%, 0/1,500 → 0.20% (one-sided 95%)
- [x] 1.9 Fix Algorithm 1 step/line refs; LaTeX artifacts (literal \S, table labels, stranded headings)
- [x] 1.10 Overhead: paired end-to-end latency, throughput, recovery time (replace "~1%" estimate)

## Phase 2 — Theory repair
**Status: APPLIED 2026-10-08** — all items merged into main.tex + FORMAL_MODEL.md (Phase 5). 2.2 = option (b).
- [x] 2.1 Theorem 1: narrow to identity-unstable derivations, or prove the information requirement. Defensible: "Idempotency keys derived from mutable argument text or unstable plan positions cannot guarantee duplicate suppression across all admissible recovery replans."
- [x] 2.2 Claim-log necessity: prove necessary or describe as sufficient (durable op table could suffice)
- [x] 2.3 Theorem 2: define logical effect identity (distinguish legitimate repeats; recognize equivalent retries)
- [x] 2.4 Theorem 2: split (a) at-most-once per durable claim identity, (b) eventual commitment under progress assumptions, (c) workflow completion
- [x] 2.5 Fix proof inconsistency: split cases at Claim durability / tool commitment / Commit durability / checkpoint durability

## Phase 3 — Protocol specification
**Status: APPLIED 2026-10-08** — all items merged into main.tex (Phase 5); 5-item gap register in Limitations.
- [x] 3.1 Epoch acquisition, ownership, atomic registration; epoch recovery/increase atomicity
- [x] 3.2 Duplicate-call result return (original results for downstream use)
- [x] 3.3 Partially written JSONL records: detection + handling
- [x] 3.4 Parallel execution: checkpoint frontier with gaps/dependencies; concurrent equivalent claims; parallel completion frontier

## Phase 4 — Experiments (designs condensed; full detail in git history)
- [x] E1 — Native-persistence baseline: LangGraph SqliteSaver + deterministic positional keys, no claim log, matched crash schedules, 60 eps. DONE 2026-10-07: dup 0.0000 / exactly-once 1.000. → paper claim becomes the boundary characterization. (`results_e1_native.json`)
- [x] E2a — Positional identity-shift (DONE 2026-10-07): det_shift 60 eps → dup-ep rate 0.7667 (46/60), eo 0.2333, mean 0.77 dup/ep + 0.77 missing/ep (mid_fanout 26/26, retry_backoff 20/20, post_branch 0/14); wal 60 eps → 0.0000/1.0000; baseline 0.80/0.20. Two failure modes: unseen re-derived keys → duplicates; colliding re-derived keys → lost effects. (`results_e2a_shift.json`)
- [x] E2b — Content identity-shift (DONE 2026-10-07): det_content 60 eps → dup-ep rate 0.7667 (46/60), eo 0.2333, 0 missing (mid_fanout 35/35, retry_backoff 11/12, post_branch 0/13); wal 60 eps → 0.0000/1.0000. Scoring canonicalizes reworded targets. (`results_e2b_content.json`)
- [x] E3 — Scale: E3a fan-out {2,4,8} × 30 eps wal DONE: 0.0000 dup / 1.0000 eo at all fan-outs. E3b log-length microbench DONE: append p50 ~0.03 ms flat (O(1)); find_by_identity 6.6 ms → 16.8 ms → 850 ms at 100/1k/10k claims (O(n) linear scan + full re-parse; indexing = follow-up). E3c concurrent workflows DONE 2026-10-08: K=1 689 ops/s p50 1.3 ms; K=4 636 ops/s p50 5.4 ms; K=16 310 ops/s p50 11.2 ms p99 1055 ms (single-threaded HTTP server serializes — concurrent server needed for production; experimental scale unaffected).
- [x] E4 — Fencing trace (DONE 2026-10-07): 200 eps no-fencing, 0.51 dup-episode rate, 102/102 class b (fresh-key zombie, epoch 0); 0 class a (same-key recommit). Mechanism confirmed. (`results_e4_fencing_trace.json`)
- Spend: $0 API (all scripted). Fault model: SIGKILL of own harness processes only.

## Phase 5 — Rewrite + re-review
**Status: COMPLETE 2026-10-08** — Phases 1–3 applied to main.tex + FORMAL_MODEL.md
(all OLD blocks verified exact-match; 2 consistency fixes at merge: 1.3 RIFL
paragraph de-claimed "original-result return" per Phase 3 honest gap; conclusion
softened to 2.2(b) "minimal requirement" language). 2.2 decision = option (b)
("durable write-ahead identity information necessary; append-only log sufficient").
PDF rebuilt: 11pp, 0 LaTeX errors, tables 1–7 ordered, comparison table fixed
(8 cols). E5 paired-timing run in progress (wal/native/deterministic, seed-matched
20 eps each; recover_s instrumented).
- [x] 5.1 Abstract/contributions/conclusion rewritten (safety/completion split; narrowed Thm 1/2)
- [x] 5.2 Full manuscript pass incorporating Phases 1–4; PDF rebuilt (11pp, 0 errors)
- [x] 5.3 Paired timing closed (E5p: wal-det +0.38s n.s.; wal-native -1.92s; recovery 5.3/5.4/6.8s) → paper §6.4
- [ ] 5.4 Mohammed's review: 2.2(a)/(b) confirmation + PDF read → then resubmit decision
