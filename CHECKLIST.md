# A1 Checklist — the single living checklist (TPDS revision)

One file, updated in place. Newest status goes at the top of each section.
The append-only narrative lives in `RUNLOG.md`. Evidence files (results JSONs,
reports) are referenced, not duplicated here.

## Current status — 2026-10-07 ~19:53 PDT
- Phases 1–3 revision DRAFTS complete and PUSHED (8b6d9e9): PHASE1_REVISIONS.md (750 lines, incl. 4 corrected bib entries + 2 new discrepancies found: API spend $0.1137 not "under $0.10"; paired e2e latency never measured), PHASE2_REVISIONS.md (Theorem 1 narrowed, Theorem 2 split 2a/2b/2c, 2.2 → option (b) recommended), PHASE3_REVISIONS.md (protocol spec + 5-item honest gap register).
- Phase 5 (manuscript rewrite + re-review) RUNNING: applying all revisions to main.tex/FORMAL_MODEL.md, 2.2 decision = option (b), paired-timing measurement, PDF rebuild, self re-review vs reviewer feedback.
- Next: review Phase 5 output, then resubmit decision.


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
**Status: DRAFTED 2026-10-07** — all items drafted in PHASE1_REVISIONS.md (pushed 8b6d9e9); manuscript application in Phase 5 (running).
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
**Status: DRAFTED 2026-10-07** — all items drafted in PHASE2_REVISIONS.md (pushed 8b6d9e9); 2.2 decision = option (b); manuscript application in Phase 5 (running).
- [x] 2.1 Theorem 1: narrow to identity-unstable derivations, or prove the information requirement. Defensible: "Idempotency keys derived from mutable argument text or unstable plan positions cannot guarantee duplicate suppression across all admissible recovery replans."
- [x] 2.2 Claim-log necessity: prove necessary or describe as sufficient (durable op table could suffice)
- [x] 2.3 Theorem 2: define logical effect identity (distinguish legitimate repeats; recognize equivalent retries)
- [x] 2.4 Theorem 2: split (a) at-most-once per durable claim identity, (b) eventual commitment under progress assumptions, (c) workflow completion
- [x] 2.5 Fix proof inconsistency: split cases at Claim durability / tool commitment / Commit durability / checkpoint durability

## Phase 3 — Protocol specification
**Status: DRAFTED 2026-10-07** — all items drafted in PHASE3_REVISIONS.md (pushed 8b6d9e9, incl. 5-item honest gap register); manuscript application in Phase 5 (running).
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
- [ ] 5.1 Rewrite abstract/contributions/conclusion around the defensible central contribution
- [ ] 5.2 Full manuscript pass incorporating Phases 1–4; rebuild PDF
- [ ] 5.3 Second reviewer assessment before TPDS submission
