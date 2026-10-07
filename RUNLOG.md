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
