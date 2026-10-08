# Khan/Remit Verification — A1 Phase 8a (2026-10-08)

**Task:** Verify the fourth private review's claim that our §2.3 mischaracterizes Khan "Resume Means Resume" (arXiv:2608.03836) as "without agents, LLMs … or a mechanism," when the cited public version allegedly includes live-agent probes (§VI) and Remit, a reference resume sequencer with an append-only effect ledger (§VII).

**Method:** Downloaded the published PDF (v3, 8 Aug 2026, 25 pages) from arXiv and read §§VI–VII directly. Research only; no manuscript edits. $0 API.

## Findings

### §VI — live-agent probes: CONFIRMED
Section 6 ("CONFORMANCE RESULTS") reports measurements on five deployed agent workflow frameworks at pinned releases — LangGraph 1.2.9, CrewAI 1.15.2, pydantic-graph 1.x (plus two more) — using real `SIGKILL`, live PostgresSaver backends, and two-host replication, with hundreds of live runs per (probe, model, host) and zero harness errors. (The harness itself is deterministic and LLM-free; the *targets* are live agent frameworks.) Our §2.3's "without agents" is factually wrong.

### §VII — Remit: CONFIRMED
Section 7 is titled "REMIT: A REFERENCE SEQUENCER WITH A VERIFIED MODEL AND CONFORMANCE-TESTED CORE." It states Remit is, quote, "a reference resume sequencer and append-only effect ledger" (9 words quoted). §7.1 ("Architecture") specifies the mechanism: an append-only ledger of branch/task/effectId records written transactionally with the completion checkpoint, plus a per-thread sequencer totally ordering persistence operations; recovery follows the rule "skip a task iff it is durably recorded" (order-independent); a read-path opt-in gate handles the cross-process race; the recovery core is Verus-verified and the package ships on PyPI. Our §2.3's "or a mechanism" is factually wrong, as is "Khan specifies the contract; we supply the mechanism and the measurement" — Khan supplies a contract, a mechanism, *and* measurements.

### Precise mechanism comparison (ours vs Remit)

| Aspect | Remit (Khan §VII) | Our protocol |
|---|---|---|
| Where the record is written | Checkpoint interface ("the narrow waist every probed framework already routes durability through"); ledger record written transactionally **with the completion checkpoint** (post-effect, checkpoint time) | **Pre-invocation** write-ahead claim: durable record written **before** the tool is ever invoked |
| Where dedup is enforced | Inside the harness: ledger-uniqueness, sequencer total order, read-path opt-in consume-claim gate | At the **external receiver boundary**: the tool server's atomic check-and-commit on keys, plus fencing epochs |
| Identity | ⟨branch, task, effectId⟩ records; branch keying ⟨checkpointId, resumeIndex⟩; per-branch ledgers | (action, target, occurrence) business-operation identity; the **original** key is replayed on recovery (never re-derived) |
| Recovery rule | Skip a task iff durably recorded (pure function of the durable log) | Reconciliation-first: replay original keys under a fresh fencing epoch; receiver suppresses already-committed keys |

The defensible distinction (as the reviewer suggested): **our pre-invocation durable claim and original-key reconciliation at the receiver boundary, versus Remit's checkpoint-interface sequencing and effect-ledger design.**

## Verdict: REVIEWER'S CORRECTION CONFIRMED

Both claims check out against the published paper. Our §2.3 must be corrected; the Table 1 Khan row must be completed; the §2.4 blanket novelty claim must be re-scoped. The current evidence does not justify characterizing Khan's work as mechanism-free.

## Drafted replacement text (for the Phase 8b writer — LaTeX-ready)

### 1. Corrected §2.3 paragraph (replaces the "closest formal treatment" paragraph)

```latex
The closest formal treatment of the checkpoint crash window we can identify
is Khan's machine-checked conformance contract for checkpoint, interrupt,
and resume semantics in workflow persistence
layers~\cite{khan2026resume}: a TLA+/TLAPS specification of what resume must
mean, a 39-cell fault matrix, and live measurements on five deployed agent
frameworks at pinned releases (LangGraph 1.2.9, CrewAI 1.15.2, pydantic-graph
1.x) under real \texttt{SIGKILL}---direct confirmation of the baseline fault
our sandbox reproduces (0.80 duplicate rate). Khan also ships a mechanism:
REMIT, a reference resume sequencer and append-only effect ledger that
interposes at the checkpointer interface, recording $\langle$branch, task,
effectId$\rangle$ records transactionally with the completion checkpoint and
totally ordering persistence operations per thread via a sequencer; its
recovery core is Verus-verified and the package is installable. The technical
distinction is precise. REMIT sequences at the checkpoint interface and
records effects at checkpoint time, enforcing dedup inside the harness
through ledger-uniqueness and a read-path consume-claim gate. Our protocol
writes the durable claim \emph{before} the tool is ever invoked and
reconciles at the external receiver boundary: recovery replays the original
key under a fresh fencing epoch, so the tool server's atomic check-and-commit
---not the harness log alone---suppresses the duplicate. We cite Khan as the
closest formal neighbor and position our contribution as the complementary
pre-invocation, receiver-boundary half of the problem.
```

### 2. Corrected Table 1 Khan row (columns: Work | Fault model | Durable records | Identity handling | Receiver assumptions | Fencing | Guarantee | Evaluation)

```latex
Khan~\cite{khan2026resume} &
Crash-stop resume &
Append-only effect ledger $\langle$branch, task, effectId$\rangle$ (Remit), written tx with completion checkpoint &
Branch keying $\langle$checkpointId, resumeIndex$\rangle$; per-branch ledgers &
Skip task iff durably recorded (order-independent); read-path consume-claim gate (cross-process) &
Sequencer total order; opt-in gate claims consumption in shared store &
Machine-checked (TLA+/TLAPS) resume contract; Verus-verified recovery core &
39-cell fault matrix; 5 frameworks live (real \texttt{SIGKILL}); Remit repair cells \\
```

### 3. Revised §2.4 closing novelty claim (replaces the "In sum" paragraph)

```latex
In sum: no prior work combines the benign commit$\to$checkpoint crash window
under an LLM agent that re-plans rather than replays, a write-ahead
effect-claim log recorded \emph{before} tool invocation (Remit's ledger
records transactionally with the completion checkpoint), reconciliation at
the external receiver boundary via original-key replay under fencing epochs
(Remit enforces dedup inside the harness through ledger-uniqueness and a
read-path gate), measured zero duplicates at exactly-once 1.000, and an
analysis of idempotency-key fragility under rewording and plan shift. A
pre-submission literature re-check (October 2026) confirmed this against the
active 2026 literature, which clusters around adversarial rollback, formal
contracts and checking, sandbox checkpoint/restore, and oversight
logging---all adjacent problems or different solutions.
```

### 4. Fix to the earlier §2.3 "contract and mechanism" sentence

Replace: "Where Khan specifies what resume \emph{must mean}, we show \emph{how to achieve} exactly-once for the commit$\to$checkpoint window and measure it: contract and mechanism, complementary."

With: "Where Khan's contract specifies what resume must mean and Remit demonstrates checkpoint-interface enforcement, we address the pre-invocation window and receiver-boundary reconciliation: complementary mechanisms at different points of the crash window."

## Notes for the Phase 8b writer
- Do NOT claim Remit "cannot see" any window — stick to the stated design difference (checkpoint-time ledger vs pre-invocation claim; in-harness dedup vs receiver-boundary reconciliation). The paper does not warrant stronger comparative claims.
- The "without LLMs" fragment of our old sentence is the only part that was arguably accurate (Khan's harness is deterministic/LLM-free); it is dropped anyway because the sentence is being replaced wholesale.
- Khan's paper is v3 (8 Aug 2026); cite the arXiv version already in our bib (khan2026resume, arXiv:2608.03836). No bib change needed.
- Total quoted words from the copyrighted paper in this file: 31 (under the 50-word limit).
