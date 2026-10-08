# A1 Phase 1 Revisions — Draft (2026-10-07)

All proposed changes as exact old-text → new-text replacements for `manuscript/main.tex`.
Do NOT apply directly: two sibling agents are drafting Phases 2 (theory) and 3 (protocol spec) in parallel.
Checklist items 1.1–1.10. All citation details verified by web search 2026-10-07 (see §A).

**Convention:** each item gives the verbatim OLD text (with location), then the NEW text.
`\cite` keys are kept stable to avoid churn; only entries change.

---

## 1.1 — LogAct characterization corrected

**Location:** §2.3 "Logs for agents", paragraph 1.

**OLD:**
```latex
LogAct~\cite{logact2026} frames agent fault tolerance as
write-ahead logging over a shared log, but for pre-execution
oversight, voting, and introspection---never the post-commit
crash window or exactly-once under crash. Prior write-ahead
formulations for agent effect safety exist only as engineering
folklore (roadmaps, design docs, blog posts): no paper, no
measurement. A formal-methods treatment of the checkpoint crash
window exists in the distributed-systems literature as an
impossibility-style result, but without agents, LLMs, tools that
keep their own records, or a mechanism; we cite it as the closest
formal neighbor and distinguish our constructive, measured
contribution.
```

**NEW:**
```latex
LogAct~\cite{logact2026} is the closest published neighbor in
spirit: it structures agents as state machines playing a shared,
append-only AgentBus and explicitly discusses crash recovery via
the bus as a write-ahead log, including fencing of stale (old-driver)
writers after a crash. Its focus, however, is a \emph{shared}
multi-agent bus with pre-execution voting, semantic (LLM-driven)
recovery, and introspection---not the single-harness
commit$\to$checkpoint window or exactly-once effect semantics
under crash, which it does not measure. Our claim log is a
per-harness write-ahead \emph{effect-claim} log paired with
log-fenced checkpoints and reconciliation-first recovery; where
LogAct's bus mediates among deconstructed agent roles, our log
mediates between one crash-prone harness and its tools. A
formal-methods treatment of the checkpoint crash window exists in
the distributed-systems literature as an impossibility-style
result, but without agents, LLMs, tools that keep their own
records, or a mechanism; we cite it as the closest formal
neighbor and distinguish our constructive, measured
contribution.
```

**Rationale:** the prior text ("never the post-commit crash window") was inaccurate; LogAct discusses crash recovery and old-driver fencing. The new text concedes this and re-grounds the distinction in shared-bus-vs-per-harness-log and measured exactly-once.

---

## 1.2 — ACRFence overlap acknowledged; LIMBO 4% attribution narrowed

**Location:** §2.2 "Crash and rollback in agent frameworks", paragraph beginning "\emph{Safe to Resume?}".

**OLD:**
```latex
\emph{Safe to Resume?}
~\cite{safutoresume2026} documents five rollback failure modes
including unrecorded external effects with a duplicate-payment
demonstration on LangGraph, but under an adversarial framing
(attacks), like ACRFence~\cite{acrfence2026}, which studies
rollback attacks with replay-or-fork mitigation---a different
threat model from our benign crash fault. Our fault model is
deliberately benign (crash-stop, chaos/HPC checkpoint-restart
tradition); there is no adversary in this paper. AgentRewind
~\cite{agentrewind2026} rewinds context and workspace state but
explicitly cannot undo external effects: the opposite direction
from ours.
```

**NEW:**
```latex
\emph{Safe to Resume?}
~\cite{safutoresume2026} documents five rollback failure modes
including unrecorded external effects with a duplicate-payment
demonstration on LangGraph, under an adversarial framing.
ACRFence~\cite{acrfence2026} is the closest adjacent mechanism:
it \emph{records irreversible tool effects} and enforces
replay-or-fork semantics upon restore, which overlaps with our
durable effect records in purpose if not in form. The
differences are the threat model---semantic rollback
\emph{attacks} (Action Replay, Authority Resurrection) versus
our benign crash-stop fault---and the mechanism: ACRFence
constrains what a \emph{restored} agent may re-issue, while our
write-ahead claim log plus reconciliation-first recovery and
epoch fencing make re-issuance unnecessary in the first place.
Our fault model is deliberately benign (crash-stop, chaos/HPC
checkpoint-restart tradition); there is no adversary in this
paper. AgentRewind~\cite{agentrewind2026} records aligned
checkpoints of agent context and controlled environment for
long-horizon recovery, but explicitly cannot undo external
effects: the opposite direction from ours.
```

**Location:** §2.1 "Idempotency keys for agent tools", final two sentences.

**OLD:**
```latex
We adopt LIMBO's
tool-contract idealization (atomic check-and-commit) as shared
ground, and our Theorem~1 explains \emph{why} LIMBO's residual 4\%
exists: it is the re-derivation fragility that keys-alone cannot
eliminate.
```

**NEW:**
```latex
We adopt the same
tool-contract idealization (atomic check-and-commit) as shared
ground. Its residual 4\% lives at the \emph{service} boundary
(late commits, in-flight ambiguity across its twelve fault
modes), a different fault class from our harness-side
commit$\to$checkpoint window; we do not claim to explain it.
What transfers is the lesson: wherever recovery correctness
depends on re-deriving an identity after the failure, some
residual remains, and only durable records close it.
```

**Rationale:** (a) ACRFence's durable recording of irreversible effects was understated---the new text names the overlap explicitly before distinguishing threat model and mechanism. (b) The prior text attributed LIMBO's residual 4% to our Theorem 1; the residual is service-boundary, ours is harness-side. Narrowed as the reviewer required. Note: the paper's actual title is "Where Does Exactly-Once Live?..." (see 1.4); the text should stop calling the paper "LIMBO" (Limbo is its sandbox). A global replace of "LIMBO" → "Li~\cite{limbo2026}" in prose is recommended; the subsection title becomes "Idempotency keys for agent tools" (unchanged) with first mention "Li's \emph{Where Does Exactly-Once Live?}~\cite{limbo2026} (whose sandbox is named Limbo)".

---

## 1.3 — RIFL + classical WAL / durable-execution / saga citations

**Location:** §2.4 "Durable execution and sagas", paragraph 1.

**OLD:**
```latex
The systems lineage is the durable-execution literature
(Temporal, DBOS-style): exactly-once workflow execution via
durable logs and replay. Classical durable execution assumes a
single writer with well-defined transaction boundaries and---
critically---no post-crash identity re-synthesis: the replayed
code re-derives the same operations deterministically. Our
adaptation---semantic claim identity, log-fenced checkpoints,
and epoch fencing at the harness/tool boundary, under LLM
re-synthesis nondeterminism---is the non-trivial part, and the
measured gap it closes (0.000 vs.\ 0.21--0.77) is the
contribution. The saga pattern literature addresses multi-step
transaction compensation (semantic atomicity across services),
a different correctness property from exactly-once of individual
effects; our protocol composes with saga-style compensation
(the claim log is a natural saga journal) but does not require
it.
```

**NEW:**
```latex
The systems lineage is write-ahead logging and durable
execution. The canonical WAL treatment is ARIES~\cite{aries1992}:
never mutate state without first durably recording the intent,
so recovery can reconcile---the discipline our claim log adapts.
Classical WAL assumes a writer that never re-synthesizes its own
operation identity after a crash; the log record and the retry
trivially coincide. RIFL~\cite{rifl2015} is the closest
classical analogue to our receiver contract: it converts
at-least-once RPCs to exactly-once by durably recording
completed-call results and returning the original result on
retry, migrating that metadata with the data across
reconfiguration. Our tool-side idempotent receiver with
original-result return (\S\ref{sec:design}, Phase~3 item~3.2)
is the same idea at the harness/tool boundary; what is new is
the \emph{harness-side} half of the problem---the recovered
agent is an LLM that re-plans, rewords, and re-indexes, so the
retry may never present the recorded identity at all. No
receiver-side mechanism alone (RIFL included) can suppress a
retry it cannot recognize; the claim log's
\textsc{find\_by\_identity} reconciliation exists precisely to
re-attach the original identity before the tool is consulted.
Modern durable execution (Temporal, DBOS-style) gives
exactly-once workflow execution via durable logs and replay but
likewise assumes deterministic re-derivation on replay---no
post-crash identity re-synthesis. Our adaptation---semantic
claim identity, log-fenced checkpoints, and epoch fencing at
the harness/tool boundary, under LLM re-synthesis
nondeterminism---is the non-trivial part, and the measured gap
it closes (0.000 vs.\ 0.21--0.77) is the contribution. The saga
pattern~\cite{sagas1987} addresses multi-step transaction
compensation (semantic atomicity across services), a different
correctness property from exactly-once of individual effects;
our protocol composes with saga-style compensation (the claim
log is a natural saga journal) but does not require it.
```

**Rationale:** adds the three required citations with precise positioning: ARIES as the WAL discipline source, RIFL as the receiver-side analogue (and its limit: unrecognizable retries), Sagas as the compensation lineage. This also sets up the Phase 3 item 3.2 (duplicate-call result return) as "the RIFL idea at the harness/tool boundary."

---

## 1.4 — Bibliography metadata corrections

Keep all `\cite` keys stable. Replace the following entries verbatim.

**OLD:**
```latex
\bibitem{limbo2026}
Anonymous, ``LIMBO: Idempotency keys for agentic tool use,''
arXiv:2609.29095, 2026.

\bibitem{acrfence2026}
Anonymous, ``ACRFence: Mitigating semantic rollback attacks in
agent systems,'' arXiv:2603.20625, 2026.

\bibitem{agentrewind2026}
Anonymous, ``AgentRewind: Backward undo for agent context and
workspace,'' arXiv:2608.14380, 2026.
```
**NEW:**
```latex
\bibitem{limbo2026}
J.~Li, ``Where does exactly-once live? Model, harness, and
tool-contract effects on duplicate side effects in LLM agents,''
arXiv:2609.29095, Sep.\ 2026.

\bibitem{acrfence2026}
Y.~Zheng, Y.~Yang, W.~Zhang, and A.~Quinn, ``ACRFence:
Preventing semantic rollback attacks in agent
checkpoint-restore,'' arXiv:2603.20625, Mar.\ 2026.

\bibitem{agentrewind2026}
Y.~Zhuang, K.~Chen, Y.~Duan, S.~Zheng, J.~Li, and X.-Y.~Zhang,
``AgentRewind: Recoverable execution for long-horizon LLM
agents,'' arXiv:2608.14380, 2026.
```

**OLD:**
```latex
\bibitem{safutoresume2026}
Anonymous, ``Safe to resume? Breaking execution continuity of
agent execution via rollback,'' arXiv:2608.29381, Aug.\ 2026.
```
**NEW:**
```latex
\bibitem{safutoresume2026}
G.~Wu, D.~Li, K.~Jiang, J.~Niu, C.~Wang, and Y.~Zhang, ``Safe to
resume? Breaking execution continuity of agent execution via
rollback,'' arXiv:2608.29381, Aug.\ 2026.
```

**ADD** (after `\bibitem{langgraph2026}`, before `\end{thebibliography}`):
```latex
\bibitem{rifl2015}
C.~Lee, S.~J.~Park, A.~Kejriwal, S.~Matsushita, and
J.~Ousterhout, ``Implementing linearizability at large scale
and low latency,'' in \emph{Proc.\ 25th ACM Symp.\ Operating
Systems Principles (SOSP'15)}, Monterey, CA, 2015, pp.\ 71--86.

\bibitem{aries1992}
C.~Mohan, D.~Haderle, B.~Lindsay, H.~Pirahesh, and P.~Schwarz,
``ARIES: A transaction recovery method supporting
fine-granularity locking and partial rollbacks using
write-ahead logging,'' \emph{ACM Trans.\ Database Syst.},
vol.~17, no.~1, pp.\ 94--162, Mar.\ 1992.

\bibitem{sagas1987}
H.~Garcia-Molina and K.~Salem, ``Sagas,'' in \emph{Proc.\ ACM
SIGMOD Int.\ Conf.\ Management of Data}, San Francisco, CA,
1987, pp.\ 249--259.
```

**Verification notes (2026-10-07 web search):** Li's paper title/author/venue confirmed via arXiv:2609.29095 (Limbo is the sandbox name, not the paper title). ACRFence title/authors confirmed via arXiv:2603.20625 (CoDAIM workshop 2026). AgentRewind title/authors confirmed via arXiv:2608.14380. Safe-to-Resume authors confirmed via arXiv:2608.29381. RIFL authors/title/venue/pages confirmed (SOSP'15, 71--86). ARIES confirmed (TODS 17(1), 94--162). Sagas confirmed (SIGMOD'87, 249--259). The existing `khan2026resume`, `zheng2026checkpoint`, `logact2026` entries were already correct and are unchanged.

---

## 1.5 — Related-work comparison table

**Location:** new table at the end of §2 (after the "In sum" paragraph, before §3). Proposed LaTeX:

```latex
\begin{table*}[t]
\centering
\caption{Positioning: fault model, durable records, identity handling,
receiver assumptions, fencing, guarantee, and evaluation across adjacent work.
``Harness-side'' = the commit$\to$checkpoint window $W(s)$; ``service-side'' =
the dispatch$\to$commit visibility window.}
\label{tab:positioning}
\begin{tabular}{p{2.1cm}p{2.0cm}p{2.2cm}p{2.2cm}p{1.8cm}p{2.0cm}p{2.2cm}}
\toprule
Work & Fault model & Durable records & Identity handling & Receiver assumptions & Fencing & Guarantee & Evaluation \\
\midrule
This paper &
Benign crash-stop, harness-side $W(s)$ &
Per-harness write-ahead effect-claim log; log-fenced checkpoints &
Semantic $(\mathit{action},\mathit{target})$ reconciliation; original keys replayed, never re-derived &
Idempotent, atomic check-and-commit; returns original result on duplicate &
Epoch fencing vs.\ stale pre-crash writers &
Exactly-once per durable claim identity (safety); 0 duplicates measured &
1,500 eps/cond sandbox; 210 LLM eps; 60 eps/cond LangGraph + real SIGKILL; ablations; E1--E4 boundary experiments \\
\midrule
Li~\cite{limbo2026} (``Limbo'' sandbox) &
Service-side: timeouts, late commits, redelivery; benign &
Ledger of committed effects (grading oracle), per-service idempotency-key sets &
Keys attached by harness guard; agent re-synthesis out of scope &
Optional idempotency keys; eventually consistent / missing read paths &
None &
Measured: keys cut duplicates 28\%$\to$4\%; no exact-once proof &
25,930 eps; 9 models; 3 harnesses; 12 fault modes; 15 recovery conditions \\
\midrule
ACRFence~\cite{acrfence2026} &
\emph{Adversarial} rollback (Action Replay, Authority Resurrection) &
Record of irreversible tool effects &
Re-synthesized requests treated as new by servers (the attack) &
Server-side replay-or-fork enforcement &
Implicit in replay-or-fork &
Mitigation of semantic rollback attacks &
PoC experiments \\
\midrule
LogAct~\cite{logact2026} &
Crash-stop (agent or environment), benign &
Shared append-only AgentBus (WAL discipline); old-driver fencing &
State-machine replay from bus; semantic (LLM) recovery &
Voters approve pre-execution; executors typed &
Old-driver fencing on the bus &
Consistent recovery; attack blocking (3\% benign-utility cost) &
Benchmarks: recovery correctness, token savings, attack blocking \\
\midrule
AgentRewind~\cite{agentrewind2026} &
Errors propagating through context/environment &
Aligned checkpoints of agent context + controlled environment &
Resume with prior-attempt information &
Controlled environment only &
None &
Improved task success / checklist progress &
MettleBench long-horizon tasks \\
\midrule
Safe to Resume?~\cite{safutoresume2026} &
\emph{Adversarial} rollback; 5 failure modes incl.\ unrecorded external effects &
Varies by framework (the gap under study) &
Nondeterministic replay characterized &
Framework-dependent &
None (failure mode) &
None---documents failures; double-payment demo &
5 frameworks; 3 end-to-end attacks \\
\midrule
Khan~\cite{khan2026resume} &
Crash-stop resume &
Workflow persistence layer &
N/A (contract level) &
N/A &
N/A &
Machine-checked (TLA+/TLAPS) resume contract &
LangGraph re-execution measurement \\
\midrule
RIFL~\cite{rifl2015} &
Server crash, benign &
Durable completed-RPC result records, migrated with data &
Client-supplied request IDs; retry recognized by ID &
Returns saved result on duplicate; lease-GC'd metadata &
N/A (no stale writers) &
Linearizability (exactly-once RPC) &
RAMCloud: $<$4\% overhead \\
\midrule
ARIES~\cite{aries1992} &
System crash, benign &
WAL; dirty-page table; checkpoints &
LSN-identified log records; no re-synthesis &
Page-level redo/undo &
N/A &
Atomicity + durability (analysis/redo/undo) &
Analytical; systems at IBM \\
\midrule
Sagas~\cite{sagas1987} &
Step failure, benign &
Saga log; compensating transactions &
Saga/step IDs; no re-synthesis &
Compensating actions defined per step &
N/A &
Semantic atomicity (all-or-compensated) &
Analytical \\
\bottomrule
\end{tabular}
\end{table*}
```

**Rationale:** the reviewer asked for a structured comparison on exactly these axes. Rows distinguish our benign harness-side window from service-side (Li), adversarial (ACRFence, Safe to Resume), shared-bus (LogAct), and classical (RIFL/ARIES/Sagas) work.

---

## 1.6 — Safety vs.\ completion split (abstract, contributions, conclusion, §6)

The manuscript conflates \emph{safety} (no duplicate commits — proven in every campaign: 0 duplicates across sandbox, LLM validation, ablations, LangGraph v1/v2, E1--E4) with \emph{completion/liveness} (workflow finishes with all effects exactly once — 66/70 for gpt-4o-mini under the loose recovery prompt; 70/70 under the tight prompt and for gpt-4.1-mini). The 4 misses were model re-emission loops (liveness pathology), never safety violations. Phase 2 will split Theorem 2 formally; Phase 1 fixes the prose claims.

### 1.6a — Abstract

**OLD:**
```latex
Across a scripted sandbox (1,500
episodes/condition), two-model LLM validation (140 episodes),
component ablations, and a production-shaped LangGraph deployment with
real \texttt{SIGKILL} fault injection---including a real-LLM supervisor
under uniform and mixed routing distributions---the protocol achieves
0.000 duplicate-effect rate and 1.000 exactly-once rate where the
baseline duplicates at 0.77--0.83 and idempotency keys at 0.21--0.37.
The claim log costs p50 20.3\,ms per step---roughly a 1\% tax against
multi-second LLM tool calls.
```

**NEW:**
```latex
Across a scripted sandbox (1,500
episodes/condition), two-model LLM validation (140 episodes),
component ablations, and a production-shaped LangGraph deployment with
real \texttt{SIGKILL} fault injection---including a real-LLM supervisor
under uniform and mixed routing distributions---the protocol commits
\emph{zero duplicate effects} in every campaign (one-sided exact 95\%
upper bounds: 4.87\% at $n{=}60$, 0.20\% at $n{=}1{,}500$), where the
baseline duplicates at 0.77--0.83 and idempotency keys at 0.21--0.37.
Workflow completion (every accepted effect committed exactly once)
reaches 1.000 in the sandbox, the LangGraph campaigns, and LLM
validation with gpt-4.1-mini (70/70) and with a tightened recovery
prompt for gpt-4o-mini (70/70); under the loose prompt gpt-4o-mini
completes 66/70, the 4 misses being prompt-fixable model
re-emission loops, never duplicate commits. Claim-log write latency
is p50 20.3\,ms per step (fsync'd Claim/Commit records).
```

### 1.6b — Contributions, item (2)

**OLD:**
```latex
We prove (Theorem~1) that \emph{any}
idempotency-key derivation computed at retry time from retry-time
inputs is insufficient in general under unconstrained LLM
re-synthesis---the log is necessary, not merely convenient---and
(Theorem~2) that the protocol guarantees exactly-once for
arbitrary crash times and arbitrary post-recovery agent behavior.
```

**NEW:**
```latex
We prove (Theorem~1, narrowed in \S\ref{sec:formal}) that
idempotency-key derivations computed at retry time from mutable
argument text or unstable plan positions cannot guarantee
duplicate suppression across all admissible recovery
replans---the log is necessary for that class, not merely
convenient---and (Theorem~2) that the protocol guarantees
at-most-once commitment per durable claim identity
(\emph{safety}) for arbitrary crash times and arbitrary
post-recovery agent behavior, with eventual commitment of
accepted claims under stated progress assumptions
(\emph{liveness}); workflow completion additionally depends on
the planning policy, as the 66/70 loose-prompt result shows.
```

**Note to Phase 2 agent:** the formal Theorem 1/2 statements and proofs in §5 are yours; the prose above is drafted to match the intended narrowed statements (checklist 2.1--2.4).

### 1.6c — Conclusion

**OLD:**
```latex
Idempotency keys narrow the gap but cannot close it in
general---we prove that any retry-time key derivation is
insufficient under unconstrained LLM re-synthesis, and measure
the residual at 0.21--0.37. The write-ahead effect-claim log
closes it: durable claims before invocation, log-fenced
checkpoints, reconciliation-first recovery, and epoch fencing
achieve 0.000 duplicates at 1.000 exactly-once across sandbox,
two-model LLM validation, component ablation, and
production-shaped LangGraph campaigns with real
\texttt{SIGKILL} injection, at $\sim$1\% latency tax. The log is
not an optimization; for LLM agents, it is the minimal durable
structure that makes exactly-once possible.
```

**NEW:**
```latex
Idempotency keys narrow the gap but cannot close it in
general---we prove that retry-time key derivations from mutable
argument text or unstable plan positions are insufficient across
all admissible recovery replans, and measure the residual at
0.21--0.37. The write-ahead effect-claim log closes the
\emph{safety} gap: durable claims before invocation, log-fenced
checkpoints, reconciliation-first recovery, and epoch fencing
commit zero duplicate effects across sandbox, two-model LLM
validation, component ablation, and production-shaped LangGraph
campaigns with real \texttt{SIGKILL} injection, at measured
claim-log write latency of p50 20.3\,ms per step. Workflow
\emph{completion} reaches 1.000 everywhere except gpt-4o-mini
under the loose recovery prompt (66/70; prompt-fixable
re-emission loops, tight prompt: 70/70)---a liveness property of
the planning policy, not of the commit protocol. The log is
not an optimization; for LLM agents, it is the minimal durable
structure that makes duplicate-free recovery possible.
```

### 1.6d — §6 (Evaluation) framing

**Location:** §6 intro paragraph ("Our evaluation answers four questions..."). Append after "Total API spend..." sentence:

**ADD:**
```latex
Throughout, we report \emph{safety} (duplicate-effect rate: ledger
commits beyond the first per semantic effect, per episode) separately
from \emph{completion} (exactly-once rate: every accepted effect
committed exactly once and the workflow finished). Safety is a property
of the protocol and holds in every campaign; completion additionally
depends on the recovery planning policy (\S\ref{sec:limitations}).
```

**Rationale:** the Q3 section already states "The safety result is prompt-independent; the liveness misses are prompt-fixable" — the new framing sentence makes the split global so the abstract/conclusion numbers can't be misread.

---

## 1.7 — Count reconciliation

### 1.7a — 140 vs.\ 210 LLM-validation episodes

**Location:** abstract ("two-model LLM validation (140 episodes)") and §1 contributions ("two-model LLM-driven validation (140 episodes)").

The manuscript is correct that the \emph{two-model} validation is 140 episodes (70 gpt-4o-mini + 70 gpt-4.1-mini, verified in `llm_validation_results.json` / `llm_validation_results_gpt41mini.json`). The reviewer's "210" = 140 + the 70-episode tight-prompt ablation (`llm_validation_results_tightprompt.json`). Fix by making the accounting explicit wherever the total appears.

**OLD** (abstract + §1, two occurrences):
```latex
two-model LLM validation (140 episodes)
```
**NEW:**
```latex
two-model LLM validation (140 episodes: 70 per model), plus a
70-episode tight-prompt ablation (210 LLM episodes total)
```
(Adjust surrounding grammar per occurrence; in the abstract the parenthetical becomes "(140 episodes: 70 per model; 210 including the tight-prompt ablation)".)

### 1.7b — 214 decisions vs.\ 180 episodes

**Location:** §6.4 (v2 LLM supervisor paragraphs).

Ground truth (verified 2026-10-07 from `decisions.jsonl` files): each LLM campaign runs 180 episodes (60/condition × 3). The supervisor emits one round-1 routing decision per generation; 34 post-branch episodes decide in \emph{both} the fresh and recovery generations (cross-generation consistency 34/34), giving 180 + 34 = \textbf{214 total round-1 decisions} per campaign. Uniform: 214/214 \texttt{fan\_out}. Mixed: 135 \texttt{escalate} / 79 \texttt{fan\_out}, 0 fallbacks.

**OLD:**
```latex
The uniform campaign
(temperature 0) produced a degenerate 214/214
\texttt{fan\_out} split---the prompt showed identical evidence
every episode, so fan-out was the only rational answer at any
temperature. After a prompt fix (seeded per-episode evidence
profiles, deterministic across fresh/recovery generations via a
domain-separated RNG, plus a cost-aware decision rule: fan-out
costs 6 more non-idempotent effects and delays resolution),
the mixed campaign produced a genuine 135-\texttt{escalate} /
79-\texttt{fan\_out} split with 0 fallbacks (\$0.0117 total
spend): the protocol holds under a real mixed routing
distribution, not just a uniform one. Cross-generation
consistency was 34/34 on the post-branch episodes.
```

**NEW:**
```latex
Each LLM campaign runs 180 episodes (60/condition); the
supervisor emits one round-1 routing decision per generation,
and 34 post-branch episodes decide in both the fresh and the
recovery generation (cross-generation consistency 34/34),
for 214 total round-1 decisions per campaign. The uniform
campaign (temperature 0) produced a degenerate 214/214
\texttt{fan\_out} split---the prompt showed identical evidence
every episode, so fan-out was the only rational answer at any
temperature. After a prompt fix (seeded per-episode evidence
profiles, deterministic across fresh/recovery generations via a
domain-separated RNG, plus a cost-aware decision rule: fan-out
costs 6 more non-idempotent effects and delays resolution),
the mixed campaign produced a genuine 135-\texttt{escalate} /
79-\texttt{fan\_out} split with 0 fallbacks (\$0.0117 total
spend): the protocol holds under a real mixed routing
distribution, not just a uniform one.
```

**Rationale:** the numbers were already right; the missing piece was the \emph{definition} (decisions ≠ episodes). One sentence fixes it.

### 1.7c — Duplicate-rate definitions and denominators

**Location:** §6 intro (append to the 1.6d framing paragraph) — the threats-to-validity already defines the metric; promote it.

**ADD** (end of the 1.6d paragraph):
```latex
Denominators are episodes per condition unless stated; ``duplicate
rate'' is the fraction of episodes with $\geq$1 duplicate-effect
ledger commit, ``exactly-once rate'' the fraction of episodes with
every accepted effect committed exactly once and no missing effects.
```

### 1.7d — 20.3\,ms overhead definition

**Location:** §6.4 "\emph{Overhead.}" paragraph (see 1.10 for full replacement). The definition: per-step wall-clock latency of the claim-log write path — one fsync'd JSONL append per \textsc{Claim} record, one per \textsc{Commit} record, plus one fsync'd checkpoint-file write per step — measured with `perf_counter_ns` in `src/measure_overhead.py` (200 episodes × 4 steps, ~376 bytes/record). Reported as p50/p99 across all measured steps. This replaces any reading of "20.3\,ms" as end-to-end episode overhead.

### 1.7e — API spend correction

**Location:** §4 "Implementation notes" and §6 intro: "Total API spend across all LLM campaigns was under \$0.10."

Verified totals: LLM validation 3×70 eps = \$0.0298 + \$0.0465 + \$0.0188 = \$0.0951; v2 LLM campaigns \$0.0069 + \$0.0117 = \$0.0186. **Total ≈ \$0.114 — the "under \$0.10" claim is wrong.**

**OLD** (two occurrences):
```latex
Total API spend across all LLM campaigns was under \$0.10.
```
**NEW:**
```latex
Total API spend across all LLM campaigns was \$0.114
(\$0.095 for the three 70-episode validation runs, \$0.019 for
the two LangGraph supervisor campaigns).
```

---

## 1.8 — Uncertainty bounds

For zero observed events in $n$ trials, the one-sided exact 95% upper bound is $1 - 0.05^{1/n}$: **4.87% at $n{=}60$**, **0.20% at $n{=}1{,}500$**. (The 0/60 bound applies per-condition in the LangGraph campaigns; the 0/1,500 bound to the sandbox and ablation campaigns.)

**ADD** to Table~\ref{tab:sandbox} caption:
```latex
\caption{Sandbox: duplicate-effect and exactly-once rates
(1,500 episodes/condition). Zero observed duplicates corresponds
to a one-sided exact 95\% upper bound of 0.20\% on the true
duplicate rate.}
```

**ADD** to Table~\ref{tab:v2} caption:
```latex
\caption{LangGraph v2: duplicate / exactly-once rates
(60 episodes/condition). Zero observed duplicates corresponds
to a one-sided exact 95\% upper bound of 4.87\% per condition.}
```

**ADD** to Table~\ref{tab:ablation} caption (after the existing parenthetical):
```latex
; zero observed duplicates $\to$ one-sided exact 95\% upper bound 0.20\%.
```

---

## 1.9 — Algorithm 1 references and LaTeX artifacts

### 1.9a — Semantic-skip line reference

**Location:** §4.2, paragraph after Algorithm~\ref{alg:recover}: "The semantic skip in step~4 handles the LLM re-synthesis problem".

Counting the numbered lines of the `algorithmic` environment (1: epoch acquisition; 2: \textsc{for}; 3: replay call; 4: append \textsc{Commit}; 5: \textsc{end for}; 6: advance $C$; 7: resume + semantic skip), the semantic skip is **line 7**, not "step 4".

**OLD:**
```latex
The semantic skip in step~4 handles the LLM re-synthesis
problem: post-recovery steps are checked against $L$ by
$(\mathit{action}, \mathit{target})$ before any new claim
issues, so reworded or re-indexed retries of already-claimed
effects are skipped rather than re-executed.
```
**NEW:**
```latex
The semantic skip in line~7 of Algorithm~\ref{alg:recover}
handles the LLM re-synthesis problem: post-recovery steps are
checked against $L$ by $(\mathit{action}, \mathit{target})$
before any new claim issues, so reworded or re-indexed retries
of already-claimed effects are skipped rather than re-executed.
```

### 1.9b — Remaining artifacts (PDF visual pass required)

Source-level checks (2026-10-07) found: no literal `\S` text in `main.tex`; all six tables labeled and referenced in order (`tab:record`, `tab:sandbox`, `tab:llm`, `tab:v2`, `tab:crashpoints`, `tab:ablation`); only one LaTeX warning (`'h' float specifier changed to 'ht'`). The reviewer's "stranded headings" and "inconsistent table numbering" could not be confirmed from source — **action:** after Phases 1–3 are merged, do a full PDF visual pass checking (i) section headings not orphaned at page bottoms, (ii) table captions render as "TABLE I…" in order of appearance, (iii) no literal backslash sequences in text. Also fix the float specifier: `\begin{algorithm}[h]` → `\begin{algorithm}[t]` (and audit other `[h]` floats) to clear the warning.

---

## 1.10 — Overhead reporting (replace "~1%" with measured numbers)

**Location:** §6.4 "\emph{Overhead.}" paragraph.

**OLD:**
```latex
\emph{Overhead.} Claim-log write latency (fsync per
\textsc{Claim}/\textsc{Commit}, $n{=}798$--1038): p50 20.3\,ms,
p99 63.4\,ms (scripted v2); p50 16.4\,ms, p99 54.6\,ms (LLM
variant)---roughly a 1\% tax against multi-second LLM tool
calls. A standalone microbenchmark (200 episodes $\times$ 4
steps, 3 fsyncs/step unoptimized) measured mean 51.7\,ms/p99
103.5\,ms per step at $\sim$376 bytes/step. Fan-out multiplies
claim count, not per-claim cost; the LLM planner adds no
per-claim overhead.
```

**NEW:**
```latex
\emph{Overhead.} Claim-log write latency is the per-step
wall-clock cost of the write path: one fsync'd JSONL append per
\textsc{Claim} record, one per \textsc{Commit} record, plus one
fsync'd checkpoint-file write per step ($\sim$376
bytes/record), measured with \texttt{perf\_counter\_ns} in
\texttt{src/measure\_overhead.py} (200 episodes $\times$ 4
steps). Scripted v2 ($n{=}798$ steps): p50 20.3\,ms, p99
63.4\,ms; the E2b campaign re-measures p50 21.5\,ms, p99
62.7\,ms ($n{=}798$); LLM variant: p50 16.4\,ms, p99 54.6\,ms.
Against multi-second LLM tool calls this is on the order of 1\%,
but we report the absolute latencies because the ratio depends
on the tool-call profile. Log-scale microbenchmark E3b
(\texttt{src/e3b\_log\_scale.py}; 100/1{,}000/10{,}000 claims):
append p50 is flat at $\sim$0.03\,ms (O(1) append-only
discipline holds); \textsc{find\_by\_identity} is a linear scan
at 6.6\,ms $\to$ 16.8\,ms $\to$ 850\,ms---O($n$), an honest
scaling bottleneck: production use needs an index (follow-up
work), though all experiments here stay far below the knee.
Full log \texttt{load()} is 0.79\,s at 10{,}000 claims.
Fan-out (E3a: 2/4/8, 30 episodes each) shows 0.0000 duplicates
at every fan-out with no per-claim cost change---fan-out
multiplies claim count, not per-claim cost; the LLM planner adds
no per-claim overhead. Tool-server throughput (E3c,
\texttt{e3c\_loadtest.py}): 688 ops/s at p50 1.3\,ms (K=1),
636 ops/s at p50 5.4\,ms (K=4), 310 ops/s at p50 11.2\,ms with
p99 1{,}055\,ms (K=16)---the single-threaded HTTP tool server
serializes at high concurrency and would need replacing for
production; it does not affect the crash-consistency results.
```

**Honest gap (flag, do not fabricate):** the reviewer asked for paired end-to-end latency (wal vs.\ baseline on identical episodes), throughput under crash injection, and recovery time as separate metrics. **None of these were measured**: the harness records per-condition aggregate rates, not per-episode wall-clock pairs, and recovery time is not instrumented separately from episode time. The revision must not claim them. Options for the authors: (a) add a small paired-timing run to Phase 4 (cheap, scripted), or (b) state the gap explicitly in Limitations. Recommended: (a) — a 60-episode paired wall-clock comparison is a few minutes of compute.

**Also update** the abstract's "roughly a 1\% tax" (replaced in 1.6a) and the conclusion's "$\sim$1\% latency tax" (replaced in 1.6c) — both already handled above.

---

## Appendix A — Verification log (2026-10-07)

| Claim | Source | Result |
|---|---|---|
| LogAct discusses crash recovery + old-driver fencing | arXiv:2604.07988 abstract + secondary summaries ("agent using the AgentBus as a WAL to recover from a crash"; "recovery agents to pick up after a crash") | CONFIRMED — manuscript's "never" was wrong |
| Li paper title/author | arXiv:2609.29095 | "Where Does Exactly-Once Live?...", Jiapeng Li, Sep 2026 — manuscript title/author wrong |
| ACRFence title/authors | arXiv:2603.20625 | "Preventing Semantic Rollback Attacks in Agent Checkpoint-Restore", Zheng/Yang/Zhang/Quinn, Mar 2026 — manuscript title/author wrong |
| AgentRewind title/authors | arXiv:2608.14380 | "Recoverable Execution for Long-Horizon LLM Agents", Zhuang et al. — manuscript title/author wrong |
| Safe to Resume authors | arXiv:2608.29381 | Wu/Li/Jiang/Niu/Wang/Zhang — manuscript "Anonymous" wrong |
| RIFL | SOSP'15 proceedings record | Lee/Park/Kejriwal/Matsushita/Ousterhout, pp. 71–86 — confirmed |
| ARIES | ACM TODS 17(1) | Mohan et al., pp. 94–162, Mar 1992 — confirmed |
| Sagas | ACM SIGMOD'87 | Garcia-Molina & Salem, pp. 249–259 — confirmed |
| 140/210 episodes | `llm_validation_results*.json` | 70+70+70 = 210; two-model = 140 — confirmed |
| 214 decisions / 180 eps | `decisions.jsonl` (both campaigns) | uniform 214 fan_out; mixed 135 esc / 79 fan_out; 214 = 180 + 34 dual-generation — confirmed |
| E2b overhead | `results_e2b_content.json` | p50 21.5ms / p99 62.7ms, n=798 — confirmed |
| E3b scale | `src/results_e3b_logscale.json` | append p50 ~0.028ms flat; find 6.6→16.8→850ms; load 0.79s@10k — confirmed |
| E3c throughput | `results_e3c_{k1,k4,k16}.json` | 688/636/310 ops/s; p99 1055ms@K=16 — confirmed |
| API spend | result JSONs + logs | $0.0951 + $0.0186 = **$0.1137** — "under $0.10" wrong |
| Algorithm line refs | `main.tex` lines 423–441 | semantic skip is line 7, not "step 4" — confirmed |
| Uncertainty bounds | $1-0.05^{1/n}$ | 4.87% (n=60), 0.20% (n=1500) — confirmed |

## Appendix B — Open items / handoff notes

1. **Phase 2 (theory) owns** the formal Theorem 1/2 statements in §5; the 1.6b prose is drafted to match the intended narrowed statements — verify consistency when merging.
2. **Phase 3 (protocol spec) owns** item 3.2 (duplicate-call original-result return); the 1.3 text cites it as "the RIFL idea at the harness/tool boundary" — coordinate.
3. **"LIMBO" → Li prose rename**: recommended global replace of the paper name in prose (the sandbox is "Limbo"; the paper is "Where Does Exactly-Once Live?"). Subsection title can stay.
4. **Paired end-to-end latency / recovery time**: not measured; recommend a small scripted paired-timing run or an explicit Limitations entry.
5. **PDF visual pass** still needed after merge (stranded headings, table caption order).
6. Nothing committed or pushed, per instructions. `manuscript/main.tex` untouched.
