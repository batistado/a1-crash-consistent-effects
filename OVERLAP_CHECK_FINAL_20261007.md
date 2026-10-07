# A1 Final Overlap / Novelty Re-check — 2026-10-07

**Purpose:** last literature gate before IEEE TPDS manuscript drafting.
**Method:** fresh web + arXiv searches, 2026-10-07, prioritizing publications after 2026-06
(the previous deep check). Queries covered: exactly-once + agents/LLM tool use;
crash consistency / write-ahead logging for agent frameworks (LangGraph, CrewAI,
AutoGen, OpenAI Agents SDK); idempotency keys for agent tool calls; saga pattern;
checkpoint/recovery with external side effects; durable execution comparisons.

**A1's claim under test:** benign crash in the window between a non-idempotent
tool-effect commit and the harness checkpoint write → recovery re-fires the effect
(duplicates). Fix: write-ahead effect-claim log (durable original claims/keys,
fsync'd) + reconciliation-first recovery + log-fenced checkpoints + epoch fencing
→ measured 0 duplicates / exactly-once 1.000, plus idempotency-key fragility analysis
(content-hash keys break on reworded retries; deterministic keys break on plan shift).

## Verdicts

### NEW candidates (post-2026-06)

| Candidate | Verdict | One-line reason |
|---|---|---|
| Khan, *Resume Means Resume* (arXiv:2608.03836, Aug 2026) | **ADJACENT — must-cite** | Closest paper yet: TLA+/TLAPS machine-checked resume contract; measures LangGraph re-executing durably recorded work after real SIGKILL. But contribution is a conformance *contract* + REMIT reference sequencer, not a WAL mechanism; never isolates the commit→checkpoint window or key fragility. Independent confirmation of our baseline fault. |
| Zheng et al., *When Can Agents Safely Checkpoint, Fork, Restore, and Merge?* (arXiv:2608.22928, Aug 2026) | **ADJACENT — must-cite** | Formal exact-checking of execution edits (Lean); notes unsafe edits "authorize the same tool action twice." Different solution: decision procedure for edit safety, not a crash-consistency mechanism. |
| *Safe to Resume? Breaking Execution Continuity via Rollback* (arXiv:2608.29381, Aug 2026) | **ADJACENT — must-cite** | Five rollback failure modes incl. "unrecorded external effects"; demonstrates duplicate payment on LangGraph. Adversarial framing (attacks), like ACRFence — different threat model from our benign crash fault. |
| LogAct (arXiv:2604.07988, Apr 2026) | **ADJACENT — must-cite** | Frames agent fault tolerance as write-ahead logging over a shared log — but for pre-execution oversight/voting and introspection, not exactly-once under crash. Never addresses the post-commit crash window. |
| Crab (arXiv:2604.28138, Apr 2026) | **ADJACENT (borderline CLEAR)** | Semantics-aware C/R for agent *sandboxes* (eBPF, OS-level); about local-state checkpoint efficiency, explicitly not external effects. |
| Mnemosyne (arXiv:2607.00269, Jul 2026) | **CLEAR** | Transaction processing for validating/repairing AI-generated workflows; different problem (untrusted proposals vs crash recovery). |
| Belayer (arXiv:2608.14635, Aug 2026) | **CLEAR** | Fault tolerance for LLM agentic *RL training* (rollout engines, containers); different domain. |
| Yan, *Fault-Tolerant Sandboxing* (arXiv:2512.12806, 2025) | **CLEAR** | Transactional filesystem snapshots for coding agents; local FS atomicity, not external effects. |
| AgentCheck (arXiv:2607.11098), ReliabilityBench (arXiv:2601.06112) | **CLEAR** | Benchmarks / eval infrastructure; no mechanism. |
| Qin et al., trace-tampering (arXiv:2609.30266, Sep 2026) | **CLEAR** | Security (agents deleting own traces); different problem. |

### Engineering folklore (no paper, no measurement — not threats; validate problem relevance)

- **CONTINUUM** (GitHub cyrax321/continuum): "ledger for external effects" — closest non-paper neighbor; no publication. Watch item.
- **avatar-engine** "committed intent step" (GitHub): re-dispatches with the same key after crash; WAL-adjacent, no paper/measurement.
- **dev.to "Do agents survive a crash…" (Sep 2026)**: measures position/content-hash/no-key strategies + LangGraph SIGKILL; blog post, never isolates the commit→checkpoint window.
- **Databricks mason docs**: explicitly acknowledges "external side effects are still at-least-once… work performed between the last checkpoint and a crash can run again." Confirms the fault; offers no fix.
- Multiple 2026 blog/skill docs independently converge on "log intent before acting" — folklore consensus that the problem is real; none publish measurements.

### Previously established nearest neighbors (confirmed still closest; not re-flagged)

- **LIMBO** (arXiv:2609.29095): idempotency keys cut duplicates 28%→4%; zero mentions of crash/write-ahead. ADJACENT.
- **ACRFence** (arXiv:2603.20625): adversarial semantic-rollback framing, replay-or-fork mitigation. ADJACENT.
- **AgentRewind** (arXiv:2608.14380): backward undo of context/workspace; explicitly cannot undo external effects. ADJACENT.
- Formal-methods impossibility paper on the checkpoint crash window: distributed-systems only, no agents/LLMs. ADJACENT.

## Overall: ✅ PASS

**No OVERLAP found.** No publication combines: (1) the benign commit→checkpoint crash window as the fault, (2) a write-ahead effect-claim log with reconciliation-first recovery, log-fenced checkpoints, and epoch fencing as the fix, (3) measured 0 duplicates / exactly-once 1.000, (4) idempotency-key fragility under rewording/plan-shift. The active 2026 literature clusters around adjacent facets — adversarial rollback (ACRFence, Safe-to-Resume), formal contracts/checking (Khan, Zheng), sandbox C/R (Crab, Belayer), oversight (LogAct) — all different problems or different solutions.

## New must-cites (full citations for the manuscript)

1. Sajjad Khan, *Resume Means Resume: A Machine-Checked Conformance Contract for Checkpoint, Interrupt, and Resume Semantics in Workflow Persistence Layers*, arXiv:2608.03836 [cs.LG], Aug 2026. https://arxiv.org/abs/2608.03836
2. Yusheng Zheng, Xiaoyu Song, Yanpeng Hu, Lebin Cheng, Yuxi Huang, Wei Zhang, *When Can Agents Safely Checkpoint, Fork, Restore, and Merge? Exact Checking for Execution Edits*, arXiv:2608.22928, Aug 2026. https://arxiv.org/abs/2608.22928
3. *Safe to Resume? Breaking Execution Continuity of Agent Execution via Rollback*, arXiv:2608.29381, Aug 2026. https://arxiv.org/abs/2608.29381 (via mirror; verify canonical arXiv URL at cite time)
4. Mahesh Balakrishnan et al., *LogAct: Enabling Agentic Reliability via Shared Logs*, arXiv:2604.07988 [cs.DC], Apr 2026. https://arxiv.org/abs/2604.07988

Positioning note for related work: Khan independently measures LangGraph re-executing durably recorded work after SIGKILL — cite as independent confirmation of the baseline fault our sandbox reproduces (0.80 duplicate rate). Frame A1 as the *mechanism + measurement* complement to the contract/checking line (Khan, Zheng): they specify what resume must mean; we show how to achieve exactly-once for the commit→checkpoint window and measure it.
