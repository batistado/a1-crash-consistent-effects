# A1 — Crash-consistent checkpointing: run log

Append-only. Every run gets one entry: date, what changed, config, result,
spend, verdict. Newest at the bottom. Times in PDT unless noted.

## 2026-10-07 — Scripted sandbox (ORX 4ef4d7e0f5fe4ddda409fbd686fd9453)
- 1,500 episodes/condition, $0. Crash injected after effect commit, before checkpoint.
- Duplicate-effect rates: baseline 0.7687, content-hash keys 0.3667,
  deterministic keys 0.2113, **WAL/claim-log 0.0000** (exactly-once 1.0000).
- Verdict: keys alone are fragile to key re-derivation after recovery; the
  write-ahead claim log removes that dependence. (`results.json`)

## 2026-10-07 — LLM validation smoke test
- gpt-4o-mini, 2 episodes, 18 calls, ~$0.0012.
- 0 duplicates, exactly-once 1.0, claim adherence 88.9% step / 100% episode.
- Verdict: harness works end to end; cleared for full run.

## 2026-10-07 — Full LLM validation v1
- gpt-4o-mini, 70 episodes, 352 calls, $0.0214 (within the one-time ~$50 exception).
- **0 duplicates** across all crash types. Claim adherence 98.3% step / 100% episode.
- Exactly-once 91.43% (64/70): 6 episodes had 1–2 missing (never-fired) effects.
- Verdict: safety holds; misses need diagnosis before they can be claimed.

## 2026-10-07 — Misses investigation
- All 6 miss episodes showed reemissions=11 = the recovery loop's attempt cap.
- Root cause: **harness measurement artifact** — a single attempt counter was
  consumed by correctly-suppressed re-emissions of already-committed claims,
  starving genuine remaining-step attempts. Not a protocol flaw.
- Fix implemented in `src/llm_validation.py`: split counters —
  productive work gets its own budget (`productive < 12`), total calls keep a
  backstop (`attempts < 48`). (`MISSES_ANALYSIS.md`)

## 2026-10-07 — TPDS formalization draft
- `FORMAL_MODEL.md`: checkpoint-window fault class (distinct from LIMBO),
  keys-alone insufficiency proof sketch, WAL safety/completeness properties,
  honest limits L1–L6, "engineering transfer" rebuttal.

## 2026-10-06 ~22:18 PDT — Validation re-run, attempt 1
- Same 70 episodes, same seed 20261008 (clean before/after); old results backed
  up to `llm_validation_results_v1_prefix.json`; launched detached (setsid nohup).
- **Died silently at 27/70**, no traceback. Lesson: detached launch alone does
  not guarantee survival; check liveness, don't assume.

## 2026-10-06 ~22:30 PDT — Validation re-run, attempt 2 (completed 22:39)
- Same config as attempt 1. 70 episodes, 470 calls, **$0.0298**.
- **0 duplicates.** Exactly-once **66/70 = 94.29%** (was 64/70 = 91.43%).
- Claim adherence 99.57% step / 100% episode (was 98.3%).
- 5 missing effects in 4 episodes — all model-looping pathology: gpt-4o-mini
  re-emitted already-committed claims ~47 times until the 48-attempt backstop
  fired. Before/after signature check: v1 misses all showed reemissions=11
  (artifact); v2 misses show 46–47 (genuine model behavior). Artifact is gone.
- Verdict: measurement bug fixed and verified; residual misses are a
  characterizable model pathology — reportable as a limitation/future-work item
  (re-emission-aware recovery prompting), not a protocol flaw.

## 2026-10-06 ~22:47 PDT — TPDS push: prompt ablation + overhead (DISPATCHED)
- Mohammed approved the next two TPDS steps.
- (1) Recovery-prompt ablation: 70-episode re-run with a tighter recovery
  prompt (explicit remaining-steps list handed to the model) to test whether
  the 4 residual miss episodes (re-emission loops) are prompt-fixable.
  Hypothesis: misses drop toward zero, turning the limitation into a result.
  Est. $0.03-0.06, hard cap $1.
- (2) Claim-log overhead: filesystem-backed (fsync'd) log latency per step
  (mean/p99 ms) + bytes/step, ~200 synthetic episodes, $0 API cost.
  Answers the reviewer's "what does the log cost?" question.
- Outputs: llm_validation_results_tightprompt.json, TIGHTPROMPT_ABLATION.md,
  OVERHEAD.md, plus RUNLOG entries.

## 2026-10-07 ~05:50 UTC — Claim-log overhead measurement
- `src/measure_overhead.py`: 200 synthetic episodes x 4 steps; durable
  append-only JSONL log (fsync per CLAIM/COMMIT) + fsync'd checkpoint write
  per step, vs in-memory baseline. $0 API cost. Env: btrfs VM disk.
- Per-step durable total: mean 51.7 ms / p99 103.5 ms; ~376 bytes/step.
  In-memory baseline: 0.0017 ms (durability dominates, not Python).
- Verdict: ~1% latency tax against 4-8 s LLM-driven steps — the safety
  guarantee is essentially free at agentic timescales. Conservative
  unoptimized number (3 fsyncs/step; COMMIT+checkpoint foldable to 2).
  (`OVERHEAD.md`, `overhead_raw.json`)

## 2026-10-07 ~05:54 UTC — Recovery-prompt ablation (tight prompt)
- `src/llm_validation_tightprompt.py`: only `ask_claim_recovery` changed —
  model gets the explicit remaining-steps list and is told to emit the next
  remaining claim, not re-emit committed ones. 70 eps, seed 20261008 (same
  crash schedule), gpt-4o-mini. Ran detached (setsid nohup), completed clean.
- **0 duplicates, 0 missing, exactly-once 70/70 = 100%** (baseline: 66/70).
  Re-emissions 196 -> 18; claim adherence 100%/100%; spend **$0.0188**
  (baseline $0.0298 — no more 47-call loops).
- Verdict: residual misses are prompt-fixable; safety is prompt-independent.
  Paper result: recovery prompts should enumerate remaining claims.
  (`TIGHTPROMPT_ABLATION.md`, `llm_validation_results_tightprompt.json`)

## 2026-10-07 ~06:07 UTC — Component ablation (scripted, $0)
- `src/component_ablation.py`: 1,500 episodes/condition, seed 20261009, $0.
  Faults: checkpoint-window crash (75/15/10) + writer-zombie (P=0.5: pre-crash
  process survives, retries in-flight step with stale epoch after recovery).
- Duplicate-effect rates: **full 0.0000** (exactly-once 1.0000),
  no-fencing 0.4927 (Δ +0.49), no-log 0.2333 (Δ +0.23, reproduces (ii-b)
  0.2113), neither 0.8767 (= baseline 0.7687 window component + zombie 0.125).
- Zombie probes: ~750/1500 fenced wherever fencing is on (full, no-log),
  0 fenced / ~740 committed as duplicates wherever removed.
- Verdict: **both components load-bearing, against disjoint failure modes**
  — log defeats key re-derivation, fence defeats stale generations; neither
  subsumes the other. (`COMPONENT_ABLATION.md`, `component_ablation_results.json`)

## 2026-10-06 ~23:20 PDT — TPDS push: second-model LLM validation (gpt-4.1-mini)
- `src/llm_validation_gpt41mini.py`: byte-identical copy of the tight-prompt
  harness except MODEL/RESULTS/pricing/docstring. 70 eps, seed 20261008 (same
  crash schedule), temp 0.7, productive<12 / attempts<48, tight prompt.
  Ran detached (setsid nohup); liveness checked via log+ps; completed clean.
- **0 duplicates, 0 missing, exactly-once 70/70 = 100%.** Claim adherence
  100%/100%. Zero re-emissions (vs 18 in one gpt-4o-mini episode), zero
  plan shifts/rewords/order deviations. 278 calls, **$0.0465**.
- Honest caveat: distinct model but same family/vendor (no non-OpenAI
  connector on this VM; Jev is decision-only, not a text driver).
  Safety result transfers by construction (WAL+fencing), liveness confirmed
  on both models; not cross-lab generalization.
- Verdict: safety generalizes beyond the first model; gpt-4.1-mini cooperated
  even better with the tight prompt. (`SECOND_MODEL_VALIDATION.md`,
  `llm_validation_results_gpt41mini.json`)

## 2026-10-07 ~07:00 UTC — TPDS push PHASE 2: LangGraph production port
- `langgraph_port/` (pinned `langgraph==1.2.14`, venv): a REAL LangGraph
  StateGraph agent (nodes plan→claim→execute→commit→checkpoint + recover)
  with REAL side effects — HTTP POST to a separate-process stdlib tool
  server (atomic check-and-commit, per-workflow seen-keys, fencing epochs,
  durable ledger) and real file appends to a scratch dir (idempotent
  check-and-append + epoch fence). Durable fsync'd JSONL claim log (same
  record shape as `measure_overhead.py`), atomic log-fenced checkpoint,
  epoch+1 per recovery with fence-before-reconcile. Crash = real SIGKILL
  from an external watchdog that only observes progress markers; recovery =
  a new cold-start process. 180 episodes (60/condition), seed 20261010, $0.
- Duplicate-effect rates: **wal 0.0000** (exactly-once 1.0000, 60/60),
  baseline 0.8333 (50/60 in-window, all duplicated), deterministic keys
  0.2333 (≈ 0.75 × 0.3 shift rate). 60/60 SIGKILLs delivered, 0 missed, 0
  recovery failures; 180/180 zombie probes fenced (90 HTTP + 90 file).
  Reproduces the sandbox ordering/magnitudes (0.7687 / 0.2113 / 0.0000).
- Planner is scripted (documented scoping: cognition not under test; the
  LLM validations cover that side). LangGraph's own checkpointer
  deliberately unused (it checkpoints trajectories — the insufficient
  structure). "What's real vs simulated" + architecture in
  `LANGGRAPH_PORT.md`; setup/run/repro in `langgraph_port/README.md`;
  results in `langgraph_port/results_langgraph.json`.
- Incidents, both fixed in code: (1) driver silently reaped at det ep 40
  of the first full run — added incremental per-episode JSONL persistence
  + `rescore.py` (wal/baseline rescored from durable state, zombie probes
  re-executed); (2) first deterministic rerun was contaminated by the
  orphaned tool server still holding :8765 (its stale seen-keys
  idempotency-suppressed the new run's calls → bogus misses) — added
  tool-server identity verification on /health (refuse stale servers) and
  `--overwrite` fresh run dirs; deterministic re-ran clean.
- Verdict: the mechanism holds in a production-like deployment — the fault
  reproduces there too, and WAL+fencing eliminates it. The "not
  productionalized" reviewer objection is now answered by construction.

## 2026-10-07 ~00:30 PDT — Mohammed's feedback: port graph too naive → v2 dispatched
- Voice-call feedback from Mohammed: the LangGraph port's graph is a simple
  linear loop (plan→claim→execute→commit→checkpoint), not representative of
  a production-grade agentic system. Risk: reviewer follow-up "real agents
  branch, fan out, delegate — does the protocol survive those shapes?"
- Assessment given back: the current port answers the primary "not
  productionalized" objection (fault + mechanism are shape-independent), but
  the harder case is **partial fan-out** (multiple effects in flight, crash
  lands mid-way, some committed some not) — untouched by the linear loop.
- Dispatched v2 build (coordinator subagent, ~00:10 PDT): a
  "research-assistant" StateGraph with conditional routing via
  conditional_edges, parallel fan-out/fan-in via Send API (2–3 worker
  subgraphs, each non-idempotent file+HTTP effects), retry-on-failure node.
  Same WAL machinery (fsync'd JSONL claim log w/ per-branch claims, epoch
  fencing, log-fenced checkpoints). New crash points: mid-fan-out partial
  completion, post-branch-decision pre-tool, during retry backoff. ≥60
  episodes × (wal vs baseline).
- Mohammed ALSO approved (voice, same call): the v2 supervisor's routing
  decisions driven by a REAL LLM planner (gpt-4o-mini). Design constraint
  agreed: the model must NOT read the raw claim log — recovery stays
  deterministic; the planner gets reconciled remaining-work state (same as
  the tight-prompt validation). Safety comes from harness enforcement, not
  model cooperation. Cost <$1, under the one-time ~$50 A1 exception.
- Spend: $0 so far (v2 not yet complete).
- Deliverables when v2 lands: DESIGN_V2.md, LANGGRAPH_PORT_V2.md, RUNLOG
  entry with tables; existing linear-loop port kept intact.

## 2026-10-07 — LangGraph port v2 ("research-assistant") COMPLETE
- Built in `langgraph_port/`: `common_v2.py` (scenario), `agent_graph_v2.py`
  (StateGraph: supervisor w/ conditional_edges routing, Send fan-out to a
  compiled worker subgraph x3, reducer fan-in, retry w/ real 1s backoff,
  escalate chain), `agent_run_v2.py`, `crash_harness_v2.py`
  (predicate watchdog, real SIGKILL), `config_v2.json` (seed 20261011,
  tool server :8766). v1 linear-loop port untouched. Docs: `DESIGN_V2.md`,
  `LANGGRAPH_PORT_V2.md`; README gained a v2 section; requirements.txt
  unchanged (no new deps).
- Bugs fixed en route: (1) branch marked done on partial commit -> now
  requires ALL effects' claims committed; (2) read-modify-write race on
  branch-state under Send fan-out -> one atomic file per settled branch;
  (3) LangGraph drops node outputs with keys undeclared in the TypedDict
  -> escalate keys declared (first full run had 24 wal recovery-proc
  failures from this; discarded, re-ran clean).
- Results, 180 episodes (60/cond), real SIGKILL, 0 missed crashes,
  0 recovery failures, zombie fencing 60/60 both tool paths every cond:
  wal dup 0.0000 / exactly-once 1.0000; baseline dup 0.8000 (48/60) /
  exactly-once 0.2000; deterministic dup 0.0000 / exactly-once 1.0000.
  Crash breakdown: mid_fanout baseline 30/30 dup (100% genuine partial
  fan-out at kill), retry_backoff baseline 18/18 dup, post_branch 0 dup
  everywhere (liveness check, 0 missing). Deterministic holds in v2
  because branch identities are structural/stable — sharpens the v1
  finding: keys fail exactly when recovery re-derives identities.
- Overhead (wal, n=798 fsync'd claim records): p50 20.3ms, p99 63.4ms —
  same ~1% tax vs LLM tool calls; fan-out multiplies claim count, not
  per-claim cost.
- Spend: $0 (local compute, scripted planner).
- Verdict: PASS. Protocol composes with branching, parallel fan-out,
  delegation, retry — the "toy loop" objection is answered. Empirical
  package now covers linear (v1), branching + parallel (v2) shapes.
- NOTE (parent-approved follow-up, NOT done here): real LLM planner
  (gpt-4o-mini) for the v2 supervisor's routing decisions, model never
  reads the raw claim log. Awaits parent dispatch.

## 2026-10-07 ~01:29 PDT — Real-LLM-planner v2 run DISPATCHED (user approved)
- Mohammed's approval (voice): kick off the real-LLM supervisor variant;
  he framed it as the last planned experiment before manuscript writing.
- Config: same v2 "research assistant" graph, gpt-4o-mini drives supervisor
  routing; LLM never sees the raw claim log (deterministic reconciliation
  first). wal arm is the must-have; 60 episodes; same crash points.
- Also: update stale DESIGN_V2.md ("scripted planner" prose).
- Hard stop: $5 OpenAI (within the $10 cap).
- Expected deliverables: LANGGRAPH_PORT_V2_LLM.md + RUNLOG entry.

## 2026-10-07 ~01:45 PDT — Final Q1-readiness audit (TPDS) — subagent audit, $0 API
- What checked: (1) 5-point research quality gate vs standing bar; (2)
  submission-readiness: LLM-run artifacts, stale prose, humanization
  coverage, GitHub state, manuscript, formal model — all verified against
  files on disk, not memory.
- Gate: 1) TPDS Q1 target PASS (verified Q1, native fit); 2) no published
  overlap PASS conditional on pre-submission re-check (3 passes 2026-10-07;
  LIMBO/2608.00501/ACRFence identified as must-cite neighbors, not scoops);
  3) genuine novelty PASS; 4) evaluation sufficient PASS (results.json
  1500eps/cond, 2-model LLM validation, LangGraph v1+v2 real SIGKILL, all
  reproducible from src/); 5) EB-1A-caliber impact PASS.
- Readiness: LLM-run report LANGGRAPH_PORT_V2_LLM.md MISSING (no LLM-run
  logs on disk — run status unconfirmed); DESIGN_V2.md "scripted planner"
  prose accurate for completed v2, update pending LLM run; humanization
  gap: langgraph_port/LANGGRAPH_PORT_V2.md was skipped (did not exist
  during pass) — needs humanizing; GitHub: local has 16 modified + 2
  untracked paths uncommitted since 7f3cd00, no remote configured locally,
  remote missing v2 results JSONs/runs/ledgers (size limits); manuscript:
  NO IEEEtran draft exists (formal core + 8 empirical reports exist as
  raw material); FORMAL_MODEL.md exists, consistent with v2 (predates the
  deterministic-keys boundary refinement — note for manuscript).
- Spend: $0. Verdict: NOT submittable today. After LLM run + manuscript,
  remaining: humanize v2/LLM reports, commit+push final state, update
  DESIGN_V2.md, pre-submission overlap re-check. Evidence base complete.

## 2026-10-07 ~02:35 PDT — Real-LLM-planner v2 run COMPLETE (last planned A1 experiment)
- Config: v2 "research assistant" graph, `--planner llm` (gpt-4o-mini,
  temp 0, decides round-1 route only; never sees the raw claim log —
  deterministic recover_node reconciliation runs first in both
  generations). 180 eps (60/condition), seed 20261011, real SIGKILL,
  crash points mid_fanout/post_branch/retry_backoff, tool server :8767.
- Result: headline-identical to scripted v2 in all 3 conditions —
  wal 0.0000 dups / 1.0000 exactly-once (60/60), baseline 0.80 dups
  (48/60) / 0.20 exactly-once, deterministic keys 0.0000 / 1.0000.
  0 missed crashes, 0 recovery failures, zombie probes fenced 60/60
  (HTTP+file) per condition. 0 missing effects anywhere.
- Behavior: LLM chose fan_out 214/214 (0 escalations, 0 fallbacks);
  fresh/recover generations agreed 34/34 on post_branch episodes.
  Honest limitation: escalate path unexercised in this run (validated in
  scripted v2 at ~40%); model systematically more fan-out-leaning than
  scripted 60/40.
- Bugs (both fixed, run restarted clean): (1) LLM decision persisted to
  scenario.json but in-memory LangGraph state kept the scripted
  placeholder — dispatch fanned out stale ["esc"]; caught at ep 3 via
  impossible wal duplicates; (2) `planner` undeclared in AgentStateV2 so
  LangGraph silently dropped it (smoke test caught: 0 model calls).
- Spend: $0.0069 OpenAI (214 calls; 0.14% of the $5 campaign cap).
- Deliverables: langgraph_port/LANGGRAPH_PORT_V2_LLM.md (full report +
  scripted-vs-LLM comparison); DESIGN_V2.md updated (planner variants
  section; stale "scripted planner" prose replaced).
- Verdict: PASS — protocol is planner-agnostic in practice, not just
  theory. Empirical package complete (sandbox 1500eps/cond, 2-model LLM
  validation, ablations, LangGraph v1, v2 scripted, v2 real-LLM).
  Next: push v2+LLM reports to GitHub, then IEEEtran manuscript draft.

## 2026-10-07 — Real-LLM supervisor MIXED-distribution follow-up LAUNCHED
- Why: the temp-0 LLM run (180/180 fan_out, 0 escalate) tested the protocol
  under a uniform route distribution only. This run samples the same prompt
  and scenario at temperature=1.0 so the model's genuine route mix is tested.
- What changed: llm_planner.TEMPERATURE now reads LLM_PLANNER_TEMP env
  (default 0.0); run launched with LLM_PLANNER_TEMP=1.0. Same seed 20261011
  (identical episodes/crash points — only the routing distribution differs),
  run-tag v2_llm_mixed, tool server :8768, $5 cap.
- Outputs: results_langgraph_v2_llm_mixed.json(.jsonl); log
  logs/crash_v2_llm_mixed.log (detached, stderr captured).
- Verdict: RUNNING.

## 2026-10-07 — A1 LLM prompt fix (root-caused, validated, relaunched)
- Diagnosis: the temp=1.0 mixed run was killed at 30/60 (wal) — every decision still fan_out. Root cause was NOT temperature: the prompt showed the model IDENTICAL evidence every episode (3 branches, 1 finding each, branch IDs only) with "escalate only if evidence appears sufficient." With nothing varying, fan_out is the only rational answer; sampling noise can't create a genuine mix.
- Fix (llm_planner.py): (1) seeded per-episode evidence profiles via evidence_summary(plan_seed) — unanimous corroboration / divergent findings / 2-of-3 split, deterministic in plan_seed with domain-separated RNG so fresh and recover generations judge identical evidence; model still never sees the claim log. (2) Added the missing cost dimension to the decision rule: fan_out costs 6 more non-idempotent effects + delays resolution; escalate concludes now. Without costs there is no decision, only a default — this makes it a genuine supervisory judgment, not a manufactured split.
- Validation (6 API calls, ~$0.001): temp=0 argmax now cleanly separates — strong evidence → escalate (3/3), weak evidence → fan_out (3/3). First attempt (evidence only, old decision rule) still returned fan_out 4/4 — the cost dimension was the load-bearing change.
- Relaunched: full 180-episode mixed campaign (60/condition × wal/baseline/deterministic), LLM_PLANNER_TEMP=1.0, seed 20261011, --overwrite (old-prompt partial results discarded as invalid for the mix question). Spend guard $4.50, campaign cap $5.

## 2026-10-07 — A1 mixed-route campaign COMPLETE (fixed prompt, temp=1.0)
- **Config:** 180 episodes (60/condition × wal/baseline/deterministic), gpt-4o-mini supervisor, LLM_PLANNER_TEMP=1.0, seed 20261011, run-tag v2_llm_mixed. Fixed prompt: seeded per-episode evidence profiles + cost-aware decision rule.
- **Route mix (the point of the rerun):** 135 escalate / 79 fan_out across 214 round-1 decisions, 0 fallbacks — a genuine model-driven mixed distribution (was 180/0 fan_out under the old prompt).
- **Results:** wal dup 0.000 / exactly-once 1.000 (60/60); baseline dup 0.800 / eo 0.200; deterministic dup 0.000 / eo 1.000. Zero missing effects.
- **Spend:** $0.0117, 214 LLM calls (cap $5).
- **Verdict:** PASS. The protocol holds exactly-once under a genuine mixed supervisor route distribution, not just a uniform one. This closes the uniform-distribution limitation from the temp-0 run. Next: update DESIGN_V2.md + real-LLM report, push to GitHub, draft manuscript.

## 2026-10-07 ~11:26 PDT — Final pre-submission overlap/novelty re-check COMPLETE (requested by Mohammed)
- Method: fresh web + arXiv searches 2026-10-07, prioritizing publications after 2026-06 (4th overlap pass today). Queries: exactly-once + agents/LLM tool use; crash consistency / WAL for agent frameworks (LangGraph, CrewAI, AutoGen, OpenAI Agents SDK); idempotency keys; saga pattern; checkpoint/recovery with external side effects; durable execution.
- Verdict: PASS — no overlap. No publication combines the benign commit→checkpoint crash window + write-ahead effect-claim log with reconciliation-first recovery + measured 0 duplicates / exactly-once 1.000 + idempotency-key fragility analysis.
- 4 new must-cites for the manuscript: Khan "Resume Means Resume" (arXiv:2608.03836), Zheng et al. "When Can Agents Safely Checkpoint..." (arXiv:2608.22928), "Safe to Resume?" (arXiv:2608.29381), LogAct (arXiv:2604.07988). Khan independently confirms our baseline fault (LangGraph re-executes durably recorded work after SIGKILL) — cite as independent confirmation.
- Watch items (not threats): CONTINUUM GitHub ledger, avatar-engine "committed intent step", Databricks mason docs acknowledging at-least-once external effects.
- Report: OVERLAP_CHECK_FINAL_20261007.md. TPDS checklist item 12 (pre-submission overlap re-check) DONE. Remaining: manuscript draft (parked per Mohammed — B1 first), report humanizing.

## 2026-10-07 ~18:30 PDT — External reviewer feedback received on A1 manuscript draft
- Source: research reviewer LLM, private pre-submission assessment of the 17-page draft (did not inspect private code/data).
- Verdict: NOT READY for TPDS — claims exceed evidence; needs substantive revision, but empirical foundation is useful.
- 6 major concerns saved verbatim-ish at REVIEWER_FEEDBACK_20261007.md:
  1. Theorem 1 overclaims — proves 2 key schemes fail, not universal insufficiency; claim-log necessity unproven (durable op table could suffice). Fix: narrow to identity-unstable derivations or prove the information requirement.
  2. Theorem 2 conflates safety (no duplicates — proven) with completion/liveness (66/70 — not proven); semantic identity underspecified (two legit refunds to same recipient). Fix: split at-most-once vs eventual-commitment vs workflow completion; define logical effect identity.
  3. LangGraph v2 ties WAL with deterministic keys (0.0000/1.0000 both) — no incremental benefit shown; no native-persistence baseline; Temporal comparison too restrictive. Fix: native-persistence baseline + identity-change-across-recovery case (where deterministic keys should break) + scale measurements.
  4. Fencing ablation (~49% dups without fencing) lacks causal mechanism — same-key retries should already be suppressed by idempotent receiver; need offending trace with claim identity/key/epoch/receiver decision.
  5. Related-work errors: LogAct DOES discuss crash recovery (§3.2) — our dismissal inaccurate; ACRFence overlap understated; LIMBO 4% attribution overstated; missing RIFL (SOSP 2015) + classical WAL/durable-execution/sagas citations; "Anonymous" for public authors + wrong titles in refs [1],[2],[3],[6].
  6. Protocol spec gaps: epoch atomicity, duplicate-call result return, partial JSONL writes, parallel checkpoint frontier, proof inconsistency (Commit exists in-window but proof assumes absent).
- Reporting corrections: safety vs completion in abstract/conclusion; campaign counts (140 vs 210); 214/214 vs 180/180 decisions; duplicate-rate definitions; 20.3ms overhead definition; Algorithm 1 step/line refs; LaTeX artifacts; uncertainty bounds (0/60 → 4.87%, 0/1,500 → 0.20%).
- Suggested central contribution: "a crash-recovery protocol that preserves tool-operation identities across agent replanning, with explicit receiver assumptions and fault-injection evaluation."
- Revision plan: REVISION_PLAN_20261007.md (checklist). Order: (1) related-work + bibliography fixes, (2) safety/completion split in claims + uncertainty bounds, (3) theorem repairs, (4) protocol spec completion, (5) new experiments (native baseline, identity-shift case, scale), (6) re-review before TPDS.
- Spend: $0. Next: work the checklist; B1 manuscript PDF building in parallel.

## 2026-10-07 ~18:50 PDT — A1 Phase 4 E4 fencing trace COMPLETE
- Instrumented re-run of sandbox no_fencing (200 eps, seed 20261010, $0).
- Result: 102/200 episodes with duplicates (0.51, cf. 0.4927 at n=1500).
- Classification of offending calls: 102/102 = type (b) fresh-key zombie commits; 0 type (a) same-key retries.
- Worked trace: fresh commits (action,target) with det: key epoch 0; zombie retries with ch: key (fresh content-hash over reworded args) at stale epoch 0<1; accepted (no fence) → semantic duplicate.
- Verdict: PASS. Causal mechanism confirmed — the ~49% is surviving writers creating fresh keys the idempotent receiver cannot suppress (unseen keyspace); delayed same-key retries are correctly suppressed. Answers reviewer §4.
- Output: results_e4_fencing_trace.json. Driver: src/e4_fencing_trace.py.

## 2026-10-07 ~18:55 PDT — A1 Phase 4 E3b claim-log length scaling COMPLETE
- Microbenchmark: append N claims + N commits, N in {100, 1000, 10000}; $0.
- Append latency p50 flat at 0.028–0.029ms (append-only O(1) holds).
- find_by_identity: 6.6ms (n=100) → 16.8ms (n=1k) → 850ms (n=10k). Linear scan degrades sharply.
- Verdict: PASS with honest caveat. At experimental scale (<100 claims) lookup is <7ms; the O(n) scan is the scaling bottleneck (850ms at 10k). Report + note indexing as follow-up.
- Output: results_e3b_logscale.json. Driver: src/e3b_logscale.py.

## 2026-10-07 ~18:45 PDT — A1 Phase 4 campaigns LAUNCHED (E1/E2a/E2b/E3a)
- E1 native-persistence baseline (SqliteSaver checkpointer, 60 eps, port 8766).
- E2a identity-shift positional (det_shift/wal/baseline, 60 ea, port 8767).
- E2b identity-shift content (det_content/wal + reword_recovery, 60 ea, port 8768).
- E3a fan-out scaling (wal, n_branches 2/4/8, 30 ea, ports 8771-8773).
- All scripted, $0 API. Early signal: det_shift already duplicating (mid_fanout).
- Design doc: PHASE4_EXPERIMENT_DESIGNS.md.

## 2026-10-07 ~19:10 PDT — A1 Phase 4 E1 native-persistence baseline COMPLETE
- Config: 60 episodes, `native` condition — v2 graph compiled with LangGraph's own SqliteSaver checkpointer (file-backed checkpoints.db, survives SIGKILL); deterministic positional keys (durable operation identities); NO claim log; recovery = fresh process + same thread_id + `graph.invoke(None, config)` (framework-native resume). Matched crash schedule (mid_fanout 0.5 / post_branch 0.25 / retry_backoff 0.25), seed 20261011, scripted planner, $0 API.
- Result: duplicate-episode rate 0.0000, exactly-once 1.0000 (60/60), 0 missing effects. By crash window: mid_fanout 26/26, post_branch 18/18, retry_backoff 16/16 — all clean. 0 crash_missed, 0 recover failures; zombie probes fenced 60/60 both sides. Checkpointer verified real (51 checkpoints / 193 writes in checkpoints.db for a sample episode).
- Reference: existing v2 wal 0.0000/1.0000, deterministic 0.0000/1.0000, baseline 0.7833/0.2167 (60 eps each).
- Verdict: PASS (boundary result, as predicted in the design doc). Native persistence + stable deterministic keys ties the WAL — the WAL shows no incremental benefit when identities are stable. The WAL's value is isolated to identity-unstable recovery (E2) + explicit auditability. Paper claim updates to the boundary characterization; honest §6.3 revision: acknowledge native works here; WAL wins on robustness. Per-episode wall latency p50 24.6s / p99 60.4s (checkpointer resume + crash/recovery cycles; slower than manual replay — report as measured).
- Output: langgraph_port/results_e1_native.json(.jsonl). Drivers: langgraph_port/agent_graph_v2_native.py, agent_run_v2_native.py.

## 2026-10-08 ~02:30 PDT — A1 Phase 4 E3a fan-out scaling COMPLETE
- WAL condition, N_BRANCHES 2/4/8, 30 eps each, matched crash schedule.
- Result: n=2: 30/30 EO, 0 dups; n=4: 30/30 EO, 0 dups; n=8: 30/30 EO, 0 dups.
- Verdict: PASS. WAL holds exactly-once as fan-out grows 2→8. (Early n=2 miss issue was an A1_N_BRANCHES env-var propagation bug in my launch script, not a WAL problem — fixed by explicit export + verification.)
- Output: results_e3a_n2/n4/n8.json. $0.

## 2026-10-08 ~02:30 PDT — A1 Phase 4 E2 identity-shift COMPLETE
- E2a positional (branch rotation): det_shift 46 dups / 46 miss / 14-60 EO (BREAKS); wal 0 dups / 60-60 EO (HOLDS).
- E2b content (target rewording): det_content 92 dups / 0 miss / 14-60 EO (BREAKS); wal 0 dups / 60-60 EO (HOLDS, via canonicalized lookup).
- Mechanism verified: same logical effect commits twice with different keys (positional b1->b0; content-hash ch:3de5->ch:ab7f on reworded target).
- Verdict: PASS. The boundary characterization holds: deterministic keys break when recovery replanning shifts positions or rewords args; WAL claim records preserve identities. This is the paper's new central insight per reviewer §4.
- Output: results_e2a_shift.json, results_e2b_content.json. $0 (deterministic paraphrase, no LLM).

## 2026-10-07 ~19:30 PDT — A1 Phase 4 E2b content identity-shift COMPLETE
- Config: 120 episodes (det_content + wal, 60 each), recovery rewords targets via fixed invertible paraphrase (`finding-r0-b0` → `finding_r0_b0_rpl`); keys are content hashes; scoring canonicalizes committed targets through the inverse map (committed in crash_harness_v2.py). Seed 20261011, scripted, $0 API.
- Result det_content: dup-episode rate 0.7667 (46/60), exactly-once 0.2333, mean 1.53 dups/ep, 0 missing. By window: mid_fanout 35/35 dup, retry_backoff 11/12, post_branch 0/13. Mechanism (verified in ledger): fresh commits (action,target) with content-hash key; recovery replays the unsettled branch under the reworded target → fresh hash → unseen key → receiver commits → semantic duplicate.
- Result wal (same campaign): 0.0000 dup / 1.0000 exactly-once (60/60), 0 missing — claim lookup canonicalizes the reworded target, reuses the ORIGINAL key → duplicate_suppressed.
- Verdict: PASS. Content-hash identities break when recovery rephrases arguments; the WAL's identity-preserving claim log holds. Directly answers reviewer §3 ("identities change across recovery").
- Output: langgraph_port/results_e2b_content.json(.jsonl).

## 2026-10-07 ~19:35 PDT — A1 Phase 4 E2a positional identity-shift COMPLETE
- Config: 180 episodes (det_shift + wal + baseline, 60 each). Recovery replanning rotates dispatch positions (todo[1:]+todo[:1]); replayed workers re-derive positional keys from shifted indices. Seed 20261011, scripted, $0 API.
- Result det_shift: dup-episode rate 0.7667 (46/60), exactly-once 0.2333, mean 0.77 dups/ep AND mean 0.77 missing/ep. By window: mid_fanout 26/26 (dup+miss), retry_backoff 20/20, post_branch 0/14.
- Mechanism (traced in ledgers/progress.log): the committed-but-unmarked branch's replay re-derives an UNSEEN key (its new position's key was never used — that position's original branch hadn't committed) → receiver commits → semantic duplicate. Second failure mode: replays whose new positions collide with ALREADY-COMMITTED keys of other branches are wrongly suppressed → those effects are LOST (missing=1). Both are genuine consequences of unstable positional identities: duplicates via unseen re-derivation, lost effects via cross-operation key collision.
- Result wal (same campaign): 0.0000 dup / 1.0000 exactly-once (60/60) — find_by_identity reuses the original key regardless of position.
- Result baseline: 0.80/0.20 (consistent with v2 baseline 0.7833).
- Verdict: PASS. Positional identities break under replanning; WAL holds. This is the experiment the reviewer asked for ("identities change across recovery").
- Output: langgraph_port/results_e2a_shift.json(.jsonl).

## 2026-10-08 ~02:45 PDT — A1 Phase 4 E3c concurrent load COMPLETE
- Direct tool-server load test, K concurrent clients x 50 fence+commit ops.
- K=1: 689 ops/s, p50 1.3ms, p99 2.4ms. K=4: 636 ops/s, p50 5.4ms, p99 15.9ms. K=16: 310 ops/s, p50 11.2ms, p99 1055ms.
- Verdict: PASS with caveat. Server handles low concurrency (K<=4) with modest degradation; at K=16 throughput halves and p99 explodes (single-threaded HTTP server + file I/O serialization). Production needs a concurrent server; experimental scale unaffected.
- Output: results_e3c_k1/k4/k16.json. Driver: langgraph_port/e3c_loadtest.py. $0.

## 2026-10-07 ~19:45 PDT — A1 Phase 3 protocol-spec draft COMPLETE ($0)
- Drafted PHASE3_REVISIONS.md from the implementation (claim_log.py, tool_server.py, file_tool.py, checkpoint_store.py, common.py, agent_graph_v2.py recover/w_claim/dispatch/worker_sub nodes, agent_graph.py v1). No manuscript or source edits (sibling agents on Phases 1–2; no code changes without approval). No commit/push.
- 3.1 Epochs: fresh writes epoch 0 (atomic_write_json); recovery does read+1 → atomic local write → POST /fence (server max-monotonic, durable epochs.json) → FileTool.set_epoch. Local write precedes fence POST (crash between = safe, wasteful). HONEST GAP: read-increment-write not atomic across concurrent recoveries — relies on crash-stop + single-recovery-writer; spec fix = CAS at the tool server (durable arbiter).
- 3.2 Duplicate result return: server/file tool return status-only `duplicate_suppressed` (no result payload); harness propagates status only. HONEST GAP: original results not returned; spec fix = result-carrying suppressions + harness result cache.
- 3.3 Partial JSONL: per-record open/write/fsync/close; load() skips torn tail, raises on torn non-tail. Torn Commit is safe (replay + idempotent suppression). HONEST GAPS: torn-tail skip is silent (add counter); no per-record checksums (don't overclaim).
- 3.4 Parallel: Send fan-out, fan-in via branch_results reducer (full state NOT returned — InvalidUpdateError avoidance); per-branch atomic done-files (no RMW race); log-fenced frontier recomputation (branch settled iff ALL effects committed; gaps legal). HONEST GAP: concurrent equivalent claims not serialized — check-then-append on identity has no lock, receiver dedups by key not identity; harness avoids it via disjoint ownership; spec fix = claim CAS on identity or identity-aware receiver dedup.
- Deliverable: self-contained spec (Part A) + exact old→new manuscript replacements (Part B) + gap register (Part C, 5 gaps with code locations and specified fixes).
- Spend: $0 (code reading + writing only). Verdict: PASS — spec complete and honest; ready for merge with Phases 1–2.

## 2026-10-08 ~00:00 UTC — A1 Phase 2 theory-repair drafts complete (2.1–2.5)
- Wrote PHASE2_REVISIONS.md (drafts only; FORMAL_MODEL.md and manuscript/main.tex NOT touched — Phases 1/3 siblings working in parallel).
- 2.1: Theorem 1 narrowed to retry-time derivations from mutable inputs ("Retry-time key fragility"); explicit scope remark excluding externally supplied stable business-op IDs; E2a (46/60 dup eps, 46 missing) and E2b (46/60 dup eps, 92 excess commits) as empirical witnesses; v2/E1 stable-identity ties as the boundary illustration; intro contribution + discussion paragraph replacements drafted.
- 2.2: recommends downgrading "log necessary" → "durable write-ahead identity record necessary; append-only log sufficient mechanism". FLAGGED NEEDS-MOHAMMED-DECISION: (a) keep strong necessity claim [not recommended — reviewer's op-table counterexample is valid] vs (b) adopt information-necessity/mechanism-sufficiency framing [recommended]. Drafts assume (b).
- 2.3: logical effect identity defined (stability/discrimination/retry-equivalence; id=(action,target,occurrence); misidentification breaks both directions; deployment modeling assumption).
- 2.4: Theorem 2 split into 2a at-most-once (safety), 2b eventual commitment of accepted claims under P1–P3 (conditional liveness), 2c workflow completion policy-dependent (66/70 = empirical rate, not liveness proof; 0 dups on all 70).
- 2.5: proof case analysis repaired — six cases split at every durability boundary; fixes the unsound assertion that COMMIT(s) ∉ L throughout W(s) (the [t_mark,t_ckpt) sub-interval has COMMIT durable); old conclusion preserved, reasoning now sound.
- Spend: $0 (writing only). Next: Mohammed resolves 2.2, then Phase 5 applies drafts in manuscript rewrite.

## 2026-10-07 ~20:00 PDT — A1 Phase 1 revisions DRAFTED (writing/related-work/reporting, items 1.1–1.10)
- **What:** Drafted all Phase 1 revisions as exact old-text → new-text replacements in PHASE1_REVISIONS.md (manuscript/main.tex NOT edited — sibling agents drafting Phases 2/3 in parallel).
- **1.1 LogAct:** corrected — LogAct DOES discuss crash recovery via AgentBus-as-WAL + old-driver fencing (verified arXiv:2604.07988); distinction re-grounded in shared-bus vs per-harness-claim-log.
- **1.2 ACRFence/LIMBO:** ACRFence overlap acknowledged (records irreversible tool effects; differs in threat model + mechanism); LIMBO 4% attribution narrowed (service-boundary residual, not explained by our theorem); prose rename LIMBO→Li recommended (Limbo is the sandbox).
- **1.3 Citations added:** RIFL (Lee et al., SOSP'15, verified), ARIES (Mohan et al., TODS 1992, verified), Sagas (Garcia-Molina & Salem, SIGMOD'87, verified); RIFL positioned as receiver-side analogue with stated limit.
- **1.4 Bib fixes:** corrected titles/authors for [limbo2026] (Jiapeng Li, "Where Does Exactly-Once Live?..."), [acrfence2026] (Zheng/Yang/Zhang/Quinn, "Preventing Semantic Rollback Attacks..."), [agentrewind2026] (Zhuang et al., "Recoverable Execution..."), [safutoresume2026] (Wu et al.); all verified via arXiv. Keys kept stable.
- **1.5 Comparison table:** drafted full LaTeX table* (fault model × durable records × identity × receiver × fencing × guarantee × evaluation) across 10 works.
- **1.6 Safety/completion split:** drafted for abstract, contributions(2), conclusion, §6 intro — safety (0 dups, every campaign) vs completion (1.000 except gpt-4o-mini loose 66/70, prompt-fixable).
- **1.7 Counts:** 140 = two-model (70+70); 210 = +tight-prompt 70 (verified JSONs); 214 decisions = 180 eps + 34 dual-generation (verified decisions.jsonl); duplicate-rate denominators defined; 20.3ms defined as per-step fsync'd write-path latency; **API spend corrected: "under $0.10" → $0.1137** (verified).
- **1.8 Uncertainty:** 0/60 → 4.87%, 0/1,500 → 0.20% (one-sided exact 95%) added to three table captions.
- **1.9 Algorithm:** "step~4" → "line~7" (verified); float-specifier warning fix; PDF visual pass flagged for stranded headings.
- **1.10 Overhead:** "~1% tax" replaced with measured numbers (E2b p50 21.5/p99 62.7ms; E3b append O(1) ~0.03ms, find O(n) 850ms@10k; E3c 688/636/310 ops/s, p99 1055ms@K=16); **honest gap flagged: paired end-to-end latency + recovery time were never measured** — recommend small paired-timing run or Limitations entry.
- **Spend:** $0 (writing + web verification only). **Verdict:** DRAFT COMPLETE — ready for merge review after Phases 2/3 land. Not committed/pushed per instructions.

## 2026-10-07 ~19:53 PDT — A1 phases 1–3 drafts checked in + pushed; Phase 5 launched
- Committed PHASE1_REVISIONS.md + PHASE2_REVISIONS.md + PHASE3_REVISIONS.md (+ RUNLOG/checklist) as 8b6d9e9; pushed to origin main, verified (remote = 8b6d9e9).
- Phase 5 (manuscript rewrite + re-review) dispatched: applies all revisions to main.tex/FORMAL_MODEL.md, 2.2 = option (b) per drafter recommendation (reversible), paired-timing measurement for the e2e-latency gap, PDF rebuild, honest self re-review vs reviewer feedback, then commit + push.
- Spend: $0 API.

## 2026-10-08 — A1 Phase 5: manuscript rewrite + re-review COMPLETE
- **Applied:** All Phase 1–3 revision drafts merged into manuscript/main.tex + FORMAL_MODEL.md. Every OLD block verified exact-match before replacement (34 Phase-1 pairs, 11 Phase-2 main.tex ops, 4 Phase-3 ops, 10 FORMAL_MODEL.md ops).
- **Merge consistency fixes (2):** (a) Phase 1's 1.3 RIFL paragraph de-claimed "original-result return" → status-only + future-work pointer, per Phase 3's honest finding that the implementation returns status only; (b) conclusion softened from "minimal durable structure" to 2.2(b) "minimal requirement ... sufficient mechanism" language. Phase 1's 1.6b superseded by Phase 2's 2.1f (same contributions item).
- **2.2 decision:** option (b) — "durable write-ahead identity *information* is necessary; the append-only log is a *sufficient* mechanism." All drafts assumed this. Mohammed can flip to (a) (4 specs revert).
- **Paired timing (E5p, NEW):** wal/native/deterministic × 20 eps, seed-matched pairing verified 0/60 mismatches. End-to-end: wal-det +0.38s (95% CI [-0.08,+0.83], n.s.); wal-native -1.92s (95% CI [-2.96,-0.88]). Recovery: wal 5.30s / det 5.43s / native 6.75s (dominated by re-execution). All 60: 0 dups, 60/60 eo. Added recover_s instrumentation to crash_harness_v2.py (additive only).
- **PDF:** 11pp, 0 LaTeX errors, tables 1–7 ordered, comparison table fixed to 8 cols, all citations resolve.
- **Self re-review:** all 6 major concerns ADDRESSED; reporting corrections complete; honest limitations documented (O(n) lookup, K=16 serialization, 2.2(b) flippable). Report: PHASE5_REREVIEW.md.
- **Spend:** $0 API (all scripted). **Verdict:** PASS — ready for Mohammed's review; remaining gate is his 2.2(a)/(b) confirmation + PDF read.

## 2026-10-07 ~21:00 PDT — Second private review received (hold TPDS); Phase 6 authorized
- **Reviewer verdict:** meaningful improvement, but HOLD the TPDS submission. Earlier concerns substantively addressed; remaining blockers: (1) revised identity definition not integrated into the protocol, (2) necessity argument still overreaches, (3) new experiments need methodological detail.
- **Point 1 (Theorem 1 universal step invalid):** mutable inputs do not imply mutable outputs — a key function can canonicalize wording or ignore plan positions. Required: explicit non-invariance condition (key actually changes across an admissible retry of the same logical effect); distinguish duplicates from omissions (E2a = collision→omission, E2b = re-derivation→duplication); remove/prove the necessity corollary; propagate to intro + conclusion ("necessity proof" heading must go).
- **Point 2 (identity not implemented):** Definition 2 = (action, target, occurrence), but Algorithm 1, Table 2, L4 still use (action, target) — two legitimate same-target operations can be collapsed. Required: one identity everywhere (record format, lookup, normal + recovery paths, theorems); invariant connecting logical identity to keys (one durable key per identity, equivalent attempts reuse it, distinct identities get distinct keys); scope restrictions (disjoint ownership, single recovery writer) in theorem assumptions; new tests: suppression of equivalent retries AND distinct authorized effects sharing action+target.
- **Point 3 (experiments underdescribed):** E1/E2/E4 need reproducible setup (baseline, identity/key rules, injected fault, episode/duplicate/missing/completion counts); E4 representative trace; E5 interval [+0.38s, 95% CI -0.08..+0.83] is inconclusive — replace "no measurable overhead" with the honest interval + CI method; overlapping generations as separate fault model. Related-work fixes: LogAct (single-agent focus), Temporal (LLM calls in Activities), LIMBO Prop 2 (conditional exactly-once). Plus integration/PDF fixes (1.000 claim, receiver status vs result, call arrival vs commitment, Theorem 2a numbering, Section 9 gaps, 180/214, Figure 2 labels, Table 7 heading, table placement).
- **Mohammed's decisions (voice):** (a) necessity heading: remove + soften to scoped claim (not a full proof under a new model); (b) start Phase 6 covering all three points; RUNLOG + CHECKLIST updated and pushed first, Phase 6 runs in background via ORX.
- **Spend:** $0.00. **Status:** Phase 6 queued.

## 2026-10-08 — A1 Phase 6: second-review blockers addressed COMPLETE
- **Point 1 (Theorem 1):** added the explicit non-invariance condition (key must actually change across an admissible retry; mutable inputs alone insufficient); implemented the reviewer's defensible statement nearly verbatim; key collisions between different effects treated separately (erroneous suppression → missing work); E2a reframed as collision→omission (0.77 dup/ep + 0.77 missing/ep), E2b as re-derivation→duplication (92 excess commits, 0 missing). "Necessity proof" heading REMOVED (now "scoped necessity argument", per Mohammed); Corollary → scoped remark under the recovery-information model; propagated to intro + conclusion. (main.tex §5, FORMAL_MODEL.md §3)
- **Point 2 (identity consistency):** (action, target, occurrence) now used in Table 2 (occurrence field added), Algorithm 1 line 7, L4, positioning table, parallel-execution paragraph; occurrence provenance explained (per-(action,target) sequence counter at claim time, durable in the claim record); key↔identity invariant stated explicitly; (A6) disjoint ownership + (A7) single recovery writer added to Theorems 2–3 assumptions. Implementation: claim_log.py (occurrence param, next_occurrence), agent_graph.py + agent_graph_v2.py call sites. **New E6 tests: 3/3 PASS** — (a) equivalent-retry suppression (1 commit, retry skipped), (b) two distinct same-(action,target) effects both execute (2 commits, distinct keys), (c) old (action,target)-only logic demonstrably collapses them. (results_e6_identity.json)
- **Point 3 (methods + related work + PDF):** new §6.5 boundary-experiments methods subsection + Table 8 (E1/E2a/E2b/E3/E4/E5 with baseline, key rules, fault, episodes, duplicates, missing, completion); E1 native setup fully described; E2 transformations + WAL identity recognition spelled out; E4 representative trace included; overlapping generations identified as a separate fault model (§6.5 + §7); E5 honest wording (+0.38s, 95% CI [-0.08,+0.83], inconclusive — CI method: paired differences, mean±1.96SE, n=20, seed-match verified). Related work: LogAct (single-agent focus), Temporal (Activities), LIMBO Prop 2 fixed. PDF fixes: 1.000 claim scoped, Table 1 receiver status-only, Case 3a/3b arrival-vs-commitment, Theorem 2a→2, §9 original-result + concurrent-recovery discussions, 214/214, Figure 2 labels, Table 7 caption, Table 6 paired/unpaired clarification.
- **PDF:** 14pp (methods subsection added the requested detail), 0 LaTeX errors, 0 unresolved references.
- **Spend:** $0 API (all scripted). **Verdict:** PASS — all three blockers addressed; self re-review complete (PHASE6_REVIEW_RESPONSE.md). Awaiting Mohammed's review; NOT committed/pushed per instructions.
