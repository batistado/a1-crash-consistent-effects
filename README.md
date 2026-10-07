# A1 — Crash-consistent checkpointing for exactly-once agent effects

Agent harnesses checkpoint *trajectories*, not *effect commitments*. When a process crashes in the window between a tool-effect commit and the harness checkpoint write, the resumed agent re-fires the tool — a duplicate side effect (the "double refund" window). Idempotency keys alone cannot close this window in general: content-hash keys break when the recovered agent rewords arguments on retry, and deterministic `(workflow_id, step_index, action)` keys break when recovery replanning shifts step indices. The fix proposed here is a **write-ahead effect-claim log** — the claim and key are logged *before* the tool is invoked — with checkpoints fenced by the log and a fencing epoch against stale writers. Recovery then reconciles from the log first and achieves exactly-once.

This is fault-tolerance/systems work: benign chaos-style fault injection (process crash mid-workflow), in the tradition of HPC checkpoint/restart studies. There is no adversary and no attack simulation.

**Novelty (second-pass verification: PASS, 2026-10-07).**
Full report: `~/workspace/research_notes/agent-systems-research-ideas-20261007-0317/a1-overlap-verification.md`.
- **LIMBO** (arXiv:2609.29095): idempotency keys cut duplicates 28%→4%, but all 12 fault modes are injected at the service boundary; the full text contains zero mentions of "crash"/"write-ahead". The harness-crash window is untested.
- **ACRFence** (arXiv:2603.20625): checkpoint-restore duplicates, but with an adversarial framing (rollback attacks) and replay-or-fork mitigation — different problem, different mechanism. Nearest neighbor; cite, don't fear.
- **AgentRewind** (arXiv:2608.14380): backward undo of context/workspace; explicitly cannot undo external effects. Different direction.
- Prior WAL-for-agents formulations exist only as engineering folklore (GitHub roadmaps, design docs, blog posts) — no paper, no measurement.
- Target venue: **IEEE TPDS (Q1)** — crash consistency, exactly-once processing, and fencing are its native vocabulary.

## Experiment plan (cheapest first)

1. `src/sandbox.py` — scripted agents run 4–8-step workflows (read-only + effectful steps: `issue_refund` / `send_email` / `update_record`) against mocked tools. Tools are atomic idempotent receivers and record every committed effect in an append-only ledger (ground truth).
2. Fault injection: harness-process crash at a random effectful step; the crash lands in-window (after tool commit, before checkpoint write) 75% of the time, else at safe points. In-memory state is discarded; the agent resumes from the last durable checkpoint.
3. Conditions (1500 episodes each):
   - (i) baseline: resume-from-checkpoint, no keys;
   - (ii-a) + content-hash idempotency keys;
   - (ii-b) + deterministic `(workflow_id, step_index, action)` keys;
   - (iii) + write-ahead effect-claim log, log-fenced checkpoints, fencing epoch.
4. Recovery replanning is nondeterministic (reworded args 50%, plan shift 30%), modeling LLM re-synthesis after restore.
5. Metrics → `results.json`: duplicate-effect rate, exactly-once rate, mean duplicates/episode, crash-landing fractions, zombie-probe fencing count.

Run: `bash run.sh` → `results.json`.

**Expected result.** Baseline duplicates at roughly the in-window crash rate; content-hash keys still duplicate on reworded retries; deterministic keys still duplicate on shifted plans; the write-ahead log reconciles from the log with original keys and reaches ~100% exactly-once. The paper's headline: keys alone are fragile to how the retry re-derives the key; the log makes recovery independent of the agent's re-derivation.

## Status (2026-10-07)

- [x] Scaffold written (sandbox, run.sh, DESIGN.md)
- [x] ORX project registered
- [x] Baseline run, 1500 episodes/condition (`results.json`) — baseline dup 0.769, deterministic keys 0.211, WAL **0.000**
- [x] LLM-in-the-loop validation: gpt-4o-mini 70 eps (0 dups, 94.29% exactly-once), gpt-4.1-mini 70/70
- [x] Component ablations (fencing-off → 0.4927 dups; claim-log-off regresses), tight-prompt ablation, overhead (~52 ms/step)
- [x] LangGraph v1 production port — real StateGraph, real SIGKILL, 180 eps (`langgraph_port/LANGGRAPH_PORT.md`)
- [x] LangGraph v2 richer graph — branching, parallel fan-out/fan-in, retries; 60 eps/condition, WAL 0.000 dups / 1.000 exactly-once, baseline 0.80 dups (`langgraph_port/LANGGRAPH_PORT_V2.md`)
- [ ] Real-LLM supervisor v2 run (gpt-4o-mini planner, claim log kept from model; $5 cap) — in progress
- [ ] IEEEtran TPDS manuscript

## IEEE TPDS readiness checklist

Tracked here explicitly; audited 2026-10-07 against the actual files.

| # | Item | Status |
|---|---|---|
| 1 | Research quality gate (Q1 venue, genuine novelty, no published overlap, feasible eval, EB-1A caliber) | ✅ PASS |
| 2 | Novelty re-verification (3 independent checks; LIMBO/ACRFence/AgentRewind as must-cites) | ✅ PASS |
| 3 | Core evidence: 1,500 eps/condition, write-ahead log at 0 duplicates | ✅ |
| 4 | Component ablations (every piece load-bearing) | ✅ |
| 5 | Two-model LLM validation (single-vendor caveat → one honest limitations sentence) | ✅ |
| 6 | Production-shaped graph, real crashes (LangGraph v1 + v2) | ✅ |
| 7 | Real-LLM supervisor run | ⏳ in progress |
| 8 | IEEEtran manuscript | ⬜ not started — **critical path** |
| 9 | DESIGN_V2.md wording ("scripted planner" → LLM planner, once run 7 lands) | ⬜ |
| 10 | Humanize v2 + LLM reports | ⬜ |
| 11 | Final GitHub push of complete state | ⬜ |
| 12 | Pre-submission overlap re-check | ⬜ |

Verdict: evidence base complete; nothing submittable until items 7–8 land. See `RUNLOG.md` for the append-only experiment history.
