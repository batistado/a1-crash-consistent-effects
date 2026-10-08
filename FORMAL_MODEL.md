# A1 Formal Core — Crash-Consistent Checkpointing for Exactly-Once Agent Effects

Draft formal core for an IEEE TPDS submission. Systems-paper style: definitions, theorems, proof sketches, honest limits. Empirical numbers referenced are on disk (`results.json`: 1,500 episodes/condition; `llm_validation_results.json`: 70 episodes, gpt-4o-mini).

## 1. System model

**Principals.**

| Symbol | Meaning |
|---|---|
| H | Agent harness process. Crash-prone (crash-stop). Executes a workflow. |
| T | External tool / service. Durable across H crashes. |
| L | Write-ahead effect-claim log. Durable (survives H crash). |
| C | Checkpoint: last fully-recorded step index. Durable. |

A workflow is an ordered sequence of effectful steps W = (s_1, …, s_n). Each step s has a deterministic key k(s) fixed **at claim time** and arguments a(s).

**Tool contract (A1).** T is an *atomic idempotent receiver*: `T.call(k, e, args)` atomically checks whether k was seen and commits the effect iff not; it maintains a durable per-workflow key set and a per-workflow fencing epoch `max_epoch`. Calls bearing `e < max_epoch[wid]` are rejected. (Same idealization LIMBO uses for the tool contract.)

**Claim discipline (A5).** H never invokes T without a prior durable `CLAIM(wid, s, k(s), args, epoch)` in L. Harness-enforced: the harness refuses the tool call otherwise. (Measured adherence 98.3% step-level in LLM validation; violations degrade to *refused calls* — the safe direction.)

**Logical effect identity.** A logical effect identity is a function id: E → I from tool effects to an identity space, supplied per deployment, satisfying: (i) *stability* — id is invariant under argument rewording and plan repositioning (it captures business meaning, not surface form); (ii) *discrimination* — distinct business intents map to distinct identities even when (action, target) coincide (e.g., two separately authorized refunds to the same recipient differ by an occurrence/authorization component); (iii) *retry equivalence* — a post-recovery retry r of a claimed effect c is *equivalent* iff id(r) = id(c); equivalent retries must be suppressed, non-equivalent effects must both commit.

Default instantiation: id = (action, target, occurrence), where *occurrence* disambiguates legitimate repetitions. Misidentification breaks the protocol in either direction (over-suppression of distinct intents, or duplicate commits of equivalent retries); the identity function is therefore a deployment modeling assumption (cf. L4), not a theorem. All "exactly-once" claims in §4 are per *durable claim identity* under the deployment's id.

**Normal path** (effectful step s):
1. H appends `CLAIM(s)` to L. *(write-ahead)*
2. H invokes `T.call(k(s), epoch, args)`.
3. H appends `COMMIT(s)` to L, then advances C past s.
   C may advance past s **only if** `COMMIT(s) ∈ L` *(log-fenced checkpoint)*.

**Recovery path** (H restarts; only L, C, T survive):
1. `epoch ← epoch + 1`; register with T (fence acquisition).
2. *Reconcile-first:* for each `CLAIM(s)` without a matching `COMMIT` in L, re-invoke `T.call` with the claim's **original** key and the new epoch. T's idempotent receiver dedups if the pre-crash call committed, executes if it never arrived. Mark `COMMIT` on success.
3. Advance C past all COMMITted claims (log-fenced).
4. Resume the agent from C. Post-recovery steps are checked against L by *semantic claim identity* `(action, target, occurrence)` (Definition, §1) before any new claim is issued: reworded or re-indexed retries of already-claimed effects are skipped, not re-executed; legitimately distinct effects sharing an action and target (different occurrence) still execute.

**Key–identity invariant (explicit).** The protocol maintains: (i) every logical identity has exactly one durable key, fixed in its CLAIM record; (ii) all equivalent attempts of that identity reuse that key (reconciliation replays the original key from L; the skip lookup matches on the full (action, target, occurrence) triple); (iii) distinct accepted identities receive distinct keys. The receiver deduplicates by *key*; the theorems guarantee uniqueness by *logical identity*; this invariant connects the two — a duplicate key implies an equivalent attempt, and a distinct identity implies a distinct key.

**Scope restrictions (in the theorem assumptions).** (A6) Disjoint effect ownership across concurrent workers: two workers never concurrently claim the same logical identity (concurrent claims of the same identity are not serialized by the log). (A7) Single recovery writer per crash: epoch acquisition is atomic only via T's max-monotonic fence; two concurrent recoveries could share an epoch (see §5, L5).

## 2. Fault model

**The checkpoint window.** For step s, define the event times t_claim(s) < t_call(s) ≤ t_commit(s) < t_mark(s) < t_ckpt(s): claim logged, tool invoked, effect committed (the real world changes), COMMIT logged, checkpoint advanced. The protocol enforces this order.

> **Definition (Checkpoint window).** W(s) = (t_commit(s), t_ckpt(s)): the open interval between the tool-effect commit and the harness checkpoint write for step s.

**Fault.** Crash-stop failure of H at time t_c. All volatile state is discarded; L, C, T persist. Crash *landings* for the step in flight:

- **pre-step:** t_c < t_commit(s) — the effect never committed (safe);
- **in-window:** t_c ∈ W(s) — the effect committed but the harness does not know it (the fault under study);
- **post-checkpoint:** t_c ≥ t_ckpt(s) — commit recorded and checkpointed (safe).

**Distinction from LIMBO.** LIMBO's late-commit window is a service-boundary phenomenon: the interval between the agent's tool-call dispatch and the service's commit becoming visible — the uncertainty is **whether the service committed**. A1's checkpoint window is harness-side: the tool *has* committed (durable in the real world); the uncertainty is **whether the harness recorded it**. Different location (service boundary vs. harness/durable-state boundary), different uncertainty, different fix. LIMBO's published fault taxonomy (12 modes, read in full) is service-boundary throughout and contains zero mentions of crash or write-ahead — the checkpoint window is absent from it. (See `a1-overlap-verification*.md`.)

Benign crash faults only (chaos/HPC checkpoint-restart tradition); no Byzantine behavior; T itself does not crash.

## 3. Necessity: keys alone cannot suffice

> **Theorem 1 (Retry-time key fragility).** Let K be an idempotency-key derivation computed by the *recovered* agent at retry time. If two admissible attempts of the *same* logical effect produce *different* keys k ≠ k′ — because the derivation reads inputs that are mutable under re-synthesis (rewordable argument text, shiftable plan positions) *and* the recovery replan actually changes them — and neither key was previously used for another operation, then an atomic receiver that deduplicates only by key can commit both attempts. A keys-only retry protocol therefore cannot guarantee duplicate suppression across all admissible recovery replans under in-window crashes.

*Proof sketch.* Fix a step s committed in-window under k = K(pre-crash inputs). The non-invariance condition is load-bearing: mutable inputs alone do not break a derivation — a derivation that canonicalizes reworded text or ignores plan positions never satisfies k′ ≠ k and is outside the theorem. Two admissible recoveries exhibit the two failure modes when the derivation *does* change:

(i) *Content-hash keys*, K = H(action, args): the recovered agent rewords the arguments to
a′ ≠ a (admissible). The retry presents k′ = H(action, a′) ≠ k. T has never seen k′ → commits
again → **duplicate**. *Empirical witness (E2b):* recovery-side target rewording broke
deterministic content-hash keys on 46/60 episodes (92 excess commits, 0 missing effects,
14/60 exactly-once); the WAL held 60/60 via canonicalized identity lookup. E2b is the
pure re-derivation→duplication witness.

(ii) *Deterministic position keys*, K = (wid, i, action): the recovered agent rotates branch
indices on replan (admissible). The retried logical step carries i′ ≠ i, so the retry presents
k′ = (wid, i′, action) ≠ k → **duplicate**; separately, a shifted retry whose new key
collides with an already-committed key of a *different* operation is wrongly suppressed →
**lost effect** (erroneous suppression, not a duplicate). *Empirical witness (E2a):*
positional shift broke deterministic keys on 46/60 episodes with 0.77 duplicates and
0.77 missing effects per episode (14/60 exactly-once); the WAL held 60/60 via
`find_by_identity` key reuse. E2a is the collision→omission witness (with accompanying
duplicates) — a different failure mode from E2b, reported separately.

The failure is a property of the *class* — retry-time derivations whose outputs actually
change across an admissible replan — not of the two schemes. The harness cannot constrain
re-synthesis inputs after the crash, so no keys-only protocol can rule out the k′ ≠ k case
in advance. ∎

*Scope.* The theorem is silent on keys that are **not** retry-time derivations: durable
business-operation IDs assigned by the tool or domain and passed through unchanged
(e.g., RIFL-style unique IDs, payment transaction IDs) lie outside its domain and may suffice;
the theorem neither covers nor refutes them. This is exactly the boundary the evaluation maps:
under stable identities, deterministic keys tie the WAL (v2 LangGraph: 0.0000/1.0000 both;
E1 native persistence: 60/60); under identity shift they fail (E2a/E2b). The theorem
characterizes the failure side of that boundary.

*Scoped remark (durable identity information — not a universal necessity theorem).* Within
the recovery-information model of §2–§3 — where the recovered agent may re-synthesize any
retry-time input and no durable business identifier survives the crash outside the harness's
own records — the source of truth for effect identity must be fixed **before** the crash:
a durable write-ahead identity record binding the effect's logical identity to its key,
not re-derived after it. The *information* (a durable pre-commit identity record) is the
necessary ingredient *under this model*; the append-only claim log is our sufficient
mechanism (see L7). Where a stable domain identifier survives recovery (E1), keys alone
suffice and no new record is needed.

*Empirical counterpart.* Scripted sandbox, 1,500 episodes/condition, in-window crash fraction 0.75: duplicate-effect rates — baseline (no keys) 0.769, content-hash keys 0.367, deterministic keys 0.211, write-ahead claim log **0.000**. LangGraph production port with real SIGKILL: under *stable* identities deterministic keys tie the WAL (0.0000/1.0000, both; E1 native persistence likewise 60/60) — keys suffice there. Under *identity shift across recovery* (E2a positional, E2b content rewording), deterministic keys break on 46/60 episodes each while the WAL holds 60/60. The measured gap is the price of re-derivation fragility, paid exactly where Theorem 1 says it is due.

## 4. Correctness: the WAL protocol guarantees exactly-once

> **Theorem 2a (At-most-once commitment — safety).** Under (A1) atomic idempotent T, (A2) durable L and C, (A3) crash-stop H only, (A4) epoch fencing, (A5) claim discipline, (A6) disjoint effect ownership across concurrent workers, (A7) single recovery writer per crash — for **any** crash time t_c and **any** post-recovery agent behavior, no durable claim identity (per the deployment's id, §1) commits more than one tool effect.

**Theorem 2b (Eventual commitment of accepted claims — conditional liveness).** Under (A1)–(A7) plus progress assumptions (P1) T eventually processes every call it accepts, (P2) the harness eventually runs recovery to completion, (P3) fencing epochs are acquired atomically — every CLAIM durably accepted into L is eventually committed by T. Accepted claims are at-least-once; with 2a, exactly-once per claim identity.

**Theorem 2c (Workflow completion — policy-dependent).** The protocol does **not** guarantee the agent emits the remaining claims of a workflow; completion is a property of the planning/recovery policy, not the protocol. The measured 66/70 completion (94.29%, gpt-4o-mini; the 4 misses were model re-emission loops, a supervisor-policy behavior) is an empirical completion rate under a specific policy, not a liveness proof. Safety (2a) held on all 70 episodes including the 4 incomplete ones: 0 duplicates.
>
> *Proof sketch for 2b.* Reconciliation replays every CLAIM without a matching COMMIT using its original key (§1, recovery path step 2). By (P2) reconciliation runs to completion; each replayed call either finds its key at T (already committed — done) or commits it (P1); (P3) guarantees the replaying epoch owns the workflow so no conflicting writer interferes. Hence every accepted claim is eventually committed. ∎
> *2c is a non-theorem* (stated as a scope delimitation): no protocol acting below the planning layer can compel a planner to emit claims; the 66/70 measurement is reported as evidence about the *supervisor policy*, not the protocol.

*Proof sketch* — case analysis on the crash landing for each step s:

- *Case 1 — before CLAIM durable* (t_c < t_claim(s)). No durable trace; recovery treats s as never attempted; a fresh CLAIM with the claim-time key commits it once. Exactly once.
- *Case 2 — CLAIM durable, call never arrived* (t_c ∈ [t_claim(s), t_call(s))). Reconciliation replays with the original key; T has never seen it → commits. Exactly once.
- *Case 3 — effect committed, COMMIT not yet durable* (t_c ∈ [t_call(s), t_mark(s))). By (A1) atomicity the effect committed exactly when the call arrived. COMMIT(s) ∉ L. Reconciliation replays with the original key; T finds the key → `duplicate_suppressed`; then COMMIT is written and C advances (log-fenced). Exactly once. (This is the true in-window sub-case.)
- *Case 4 — COMMIT durable, checkpoint not yet advanced* (t_c ∈ [t_mark(s), t_ckpt(s))). COMMIT(s) ∈ L but C not advanced past s — **the sub-case the previous version mishandled** (it asserted COMMIT(s) ∉ L throughout W(s), but [t_mark, t_ckpt) ⊂ W(s)). Reconciliation finds the CLAIM+COMMIT pair and issues **no replay**; C advances past s (log-fenced). No duplicate, no loss. Exactly once.
- *Case 5 — post-checkpoint* (t_c ≥ t_ckpt(s)). COMMIT(s) ∈ L, C advanced. Reconciliation skips s; the agent resumes after C. Exactly once.
- *Stale writers.* Any in-flight pre-crash call arriving after recovery bears e < max_epoch → rejected by (A4). No zombie commits. (E4: 102/102 offending calls were this class; 0 same-key recommit attempts succeeded.)
- *Agent-behavior independence.* Reconciliation uses original keys from L — the agent is **never required to re-derive a key**. Post-recovery steps are checked against L by logical effect identity (Definition, §1) before new claims issue, so reworded/shifted retries of claimed effects are recognized as equivalent and skipped. The argument holds for arbitrary post-recovery behavior, including adversarial re-emission (observed: 11 consecutive re-emissions of committed effects, all suppressed, 0 duplicates over 70 LLM-driven episodes). ∎

*Remark (key determinism, sharpened).* The protocol requires keys to be deterministic only **at claim time** (so a pre-crash claim and any same-generation retry coincide). Post-crash *re-derivability* is irrelevant — the log supplies the key. This is the precise point where keys-alone fails and the WAL succeeds, and it is what Theorem 1 formalizes.

## 5. Assumptions and limits (stated honestly)

- **(L1) Tool idealization.** (A1) assumes atomic check-and-commit at T. Real tools with non-atomic or non-idempotent APIs need an adapter (e.g., a transactional outbox at the tool boundary); the theorem does not cover them. Same idealization as LIMBO's tool contract — cite it as shared ground, not as a weakness unique to this work.
- **(L2) Log durability.** (A2) is assumed, not proved. Log loss voids the guarantee — the standard WAL assumption, stated explicitly rather than buried.
- **(L3) Safety, conditional liveness, no workflow-completion guarantee.** Theorem 2a is a *safety* property (no duplicate commits per claim identity). Theorem 2b gives at-least-once of *claimed* effects only under explicit progress assumptions (P1–P3). Neither proves the agent will emit remaining claims — workflow completion depends on the planning/recovery policy (Theorem 2c; measured 66/70 under the gpt-4o-mini supervisor policy). (See `MISSES_ANALYSIS.md`: the observed "misses" were the test harness's own attempt cap, now fixed; the protocol itself imposes no liveness bound, but neither does it guarantee agent progress.)
- **(L4) Semantic identity is a modeling choice.** The skip-logic keys on `(action, target, occurrence)` as the stable business identity of an effect. Effects whose identity cannot be captured this way need a domain-specific identity function; misidentification breaks skipping in either direction. The paper must state the identity assumption per deployment.
- **(L5) Fault scope.** Crash-stop H only; no Byzantine harness, no tool-side crashes, single writer per workflow per epoch (fencing enforces this).
- **(L6) Claim discipline is enforced, not assumed.** (A5) held at 98.3% step-level in LLM validation because the harness *refuses* tool calls without valid claims — violations degrade to refused calls (missing, never duplicates). A deployment must preserve the refusal direction.

- **(L7) Mechanism vs. information.** The theorems establish necessity of *durable write-ahead identity information* (scoped remark, §3) *under the stated recovery-information model*, not uniqueness of the append-only log schema. A durable operation table (identity → status) written before each tool call would satisfy the same requirement; our JSONL claim log is the evaluated sufficient mechanism. Claims in the paper about "necessity" refer to the information under that model, never the schema, and never universally.

## 6. Positioning note (for the paper's intro / related work)

The expected reviewer objection — *"this is just write-ahead logging applied to agents"* — is answered in three moves, each grounded above:

1. **New fault class.** The checkpoint window (§2) is a harness-side crash-consistency gap absent from LIMBO's service-boundary taxonomy and, to our knowledge, from the crash-consistency literature as applied to agent harnesses. Classical WAL has no notion of it because classical writers do not re-synthesize their own transaction identity after a crash.
2. **Necessity of the information, not analogy.** Theorem 1 shows *durable write-ahead identity information* is required: keys derived at retry time from mutable inputs are insufficient across admissible replans — not just in practice, and not just for our two schemes (E2a/E2b are the empirical witnesses). The contribution is therefore the minimal durable structure that makes exactly-once possible under LLM re-synthesis nondeterminism — not "WAL applied to X". The append-only log is our sufficient mechanism; an equivalent durable operation table would satisfy the same requirement.
3. **Non-trivial adaptation.** Semantic claim identity + log-fenced checkpoints + epoch fencing at the harness/tool boundary is not textbook WAL, which assumes a single writer with well-defined transaction boundaries and no post-crash identity re-synthesis. The adaptation — and the measured gap it closes (0.000 vs 0.211–0.769) — is the contribution.

Cite LIMBO as methodological foundation (fault-injection evaluation, tool-contract idealization); ACRFence, AgentRewind, and the SagaLLM family as nearest neighbors solving different problems (per the overlap reports); the durable-execution literature (Temporal/DBOS-style) as the systems lineage this work extends into the agent-harness setting.
