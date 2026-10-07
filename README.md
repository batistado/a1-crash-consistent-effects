# A1 — Crash-consistent checkpointing for exactly-once agent effects

**Hypothesis.** Agent harnesses checkpoint *trajectories*, not *effect
commitments*. A process crash landing in the window between a tool-effect
commit and the harness checkpoint write causes the resumed agent to re-fire
the tool — a duplicate side effect (the "double refund" window). Idempotency
keys alone cannot close this window in general: content-hash keys break when
the recovered agent rewords arguments on retry, and deterministic
`(workflow_id, step_index, action)` keys break when recovery replanning
shifts step indices. A **write-ahead effect-claim log** (log the claim+key
*before* invoking the tool), with checkpoints fenced by the log and a fencing
epoch against stale writers, makes recovery reconcile-first and achieves
exactly-once.

This is fault-tolerance/systems work — benign chaos-style fault injection
(process crash mid-workflow), in the tradition of HPC checkpoint/restart
studies. There is no adversary and no attack simulation.

**Novelty (second-pass verification: PASS, 2026-10-07).**
Full report: `~/workspace/research_notes/agent-systems-research-ideas-20261007-0317/a1-overlap-verification.md`.
- **LIMBO** (arXiv:2609.29095): idempotency keys cut duplicates 28%→4%, but all
  12 fault modes are injected *at the service boundary*; full text contains
  zero mentions of "crash"/"write-ahead". The harness-crash window is untested.
- **ACRFence** (arXiv:2603.20625): checkpoint-restore duplicates, but
  adversarial framing (rollback attacks) and replay-or-fork mitigation —
  different problem, different mechanism. Nearest neighbor; cite, don't fear.
- **AgentRewind** (arXiv:2608.14380): backward undo of context/workspace;
  explicitly cannot undo external effects. Different direction.
- Prior WAL-for-agents formulations exist only as engineering folklore
  (GitHub roadmaps, design docs, blog posts) — no paper, no measurement.
- Target venue: **IEEE TPDS (Q1)** — crash consistency, exactly-once
  processing, and fencing are its native vocabulary.

## Experiment plan (cheapest first)

1. `src/sandbox.py` — scripted agents run 4–8-step workflows (read-only +
   effectful steps: `issue_refund` / `send_email` / `update_record`) against
   mocked tools. Tools are atomic idempotent receivers and record every
   committed effect in an append-only ledger (ground truth).
2. Fault injection: harness-process crash at a random effectful step; the
   crash lands **in-window** (after tool commit, before checkpoint write)
   75% of the time, else at safe points. In-memory state is discarded; the
   agent resumes from the last durable checkpoint.
3. Conditions (1500 episodes each):
   - (i) baseline: resume-from-checkpoint, no keys;
   - (ii-a) + content-hash idempotency keys;
   - (ii-b) + deterministic `(workflow_id, step_index, action)` keys;
   - (iii) + write-ahead effect-claim log, log-fenced checkpoints, fencing epoch.
4. Recovery replanning is nondeterministic (reworded args 50%, plan shift 30%),
   modeling LLM re-synthesis after restore.
5. Metrics → `results.json`: duplicate-effect rate, exactly-once rate, mean
   duplicates/episode, crash-landing fractions, zombie-probe fencing count.

Run: `bash run.sh` → `results.json`.

**Expected result.** Baseline duplicates at ~the in-window crash rate;
content-hash keys still duplicate on reworded retries; deterministic keys
still duplicate on shifted plans; the write-ahead log reconciles from the
log with original keys and reaches ~100% exactly-once. The headline for the
paper: *keys alone are fragile to how the retry re-derives the key; the log
makes recovery independent of the agent's re-derivation.*

## Status

- [x] Scaffold written (sandbox, run.sh, DESIGN.md)
- [x] ORX project registered
- [ ] Baseline run, 1500 episodes/condition (`results.json`)
- [ ] LLM-in-the-loop validation (STUB — needs separate spend approval; see DESIGN.md)
