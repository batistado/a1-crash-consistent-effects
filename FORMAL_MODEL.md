# A1 Formal Core — Crash-Consistent Checkpointing for Exactly-Once Agent Effects

Draft formal core for an IEEE TPDS submission. Systems-paper style:
definitions, theorems, proof sketches, honest limits. Empirical numbers
referenced are on disk (`results.json`: 1,500 episodes/condition;
`llm_validation_results.json`: 70 episodes, gpt-4o-mini).

## 1. System model

**Principals.**

| Symbol | Meaning |
|---|---|
| H | Agent harness process. Crash-prone (crash-stop). Executes a workflow. |
| T | External tool / service. Durable across H crashes. |
| L | Write-ahead effect-claim log. Durable (survives H crash). |
| C | Checkpoint: last fully-recorded step index. Durable. |

A workflow is an ordered sequence of effectful steps W = (s_1, …, s_n).
Each step s has a deterministic key k(s) fixed **at claim time** and
arguments a(s).

**Tool contract (A1).** T is an *atomic idempotent receiver*: `T.call(k, e,
args)` atomically checks whether k was seen and commits the effect iff not;
it maintains a durable per-workflow key set and a per-workflow fencing
epoch `max_epoch`. Calls bearing `e < max_epoch[wid]` are rejected. (Same
idealization LIMBO uses for the tool contract.)

**Claim discipline (A5).** H never invokes T without a prior durable
`CLAIM(wid, s, k(s), args, epoch)` in L. Harness-enforced: the harness
refuses the tool call otherwise. (Measured adherence 98.3% step-level in
LLM validation; violations degrade to *refused calls* — the safe direction.)

**Normal path** (effectful step s):
1. H appends `CLAIM(s)` to L. *(write-ahead)*
2. H invokes `T.call(k(s), epoch, args)`.
3. H appends `COMMIT(s)` to L, then advances C past s.
   C may advance past s **only if** `COMMIT(s) ∈ L` *(log-fenced checkpoint)*.

**Recovery path** (H restarts; only L, C, T survive):
1. `epoch ← epoch + 1`; register with T (fence acquisition).
2. *Reconcile-first:* for each `CLAIM(s)` without a matching `COMMIT` in L,
   re-invoke `T.call` with the claim's **original** key and the new epoch.
   T's idempotent receiver dedups if the pre-crash call committed, executes
   if it never arrived. Mark `COMMIT` on success.
3. Advance C past all COMMITted claims (log-fenced).
4. Resume the agent from C. Post-recovery steps are checked against L by
   *semantic claim identity* `(action, target)` before any new claim is
   issued: reworded or re-indexed retries of already-claimed effects are
   skipped, not re-executed.

## 2. Fault model

**The checkpoint window.** For step s, define the event times
t_claim(s) < t_call(s) ≤ t_commit(s) < t_mark(s) < t_ckpt(s):
claim logged, tool invoked, effect committed (the real world changes),
COMMIT logged, checkpoint advanced. The protocol enforces this order.

> **Definition (Checkpoint window).** W(s) = (t_commit(s), t_ckpt(s)):
> the open interval between the tool-effect commit and the harness
> checkpoint write for step s.

**Fault.** Crash-stop failure of H at time t_c. All volatile state is
discarded; L, C, T persist. Crash *landings* for the step in flight:

- **pre-step:** t_c < t_commit(s) — the effect never committed (safe);
- **in-window:** t_c ∈ W(s) — the effect committed but the harness does
  not know it (the fault under study);
- **post-checkpoint:** t_c ≥ t_ckpt(s) — commit recorded and checkpointed (safe).

**Distinction from LIMBO.** LIMBO's late-commit window is a
*service-boundary* phenomenon: the interval between the agent's tool-call
dispatch and the service's commit becoming visible — the uncertainty is
**whether the service committed**. A1's checkpoint window is
*harness-side*: the tool *has* committed (durable in the real world); the
uncertainty is **whether the harness recorded it**. Different location
(service boundary vs. harness/durable-state boundary), different
uncertainty, different fix. LIMBO's published fault taxonomy (12 modes,
read in full) is service-boundary throughout and contains zero mentions
of crash or write-ahead — the checkpoint window is absent from it. (See
`a1-overlap-verification*.md`.)

Benign crash faults only (chaos/HPC checkpoint-restart tradition); no
Byzantine behavior; T itself does not crash.

## 3. Necessity: keys alone cannot suffice

> **Theorem 1 (Keys-alone insufficiency).** Let K be any idempotency-key
> derivation computed by the *recovered* agent at retry time from
> retry-time inputs (argument text, plan position, or any function
> thereof). If post-recovery re-synthesis is unconstrained — the agent
> may reword arguments or restructure the plan — then a keys-only retry
> protocol cannot guarantee exactly-once under in-window crashes.

*Proof sketch.* Fix a step s with pre-crash args a, committed in-window
under key k = K(pre-crash inputs). Consider two admissible recoveries:

(i) *Content-hash keys*, K = H(action, args): the recovered agent
rewords the arguments to a′ ≠ a (admissible; observed reword rate 0.50
scripted, 0.114 LLM-driven). The retry presents k′ = H(action, a′) ≠ k.
T has never seen k′ → commits again → **duplicate**.

(ii) *Deterministic position keys*, K = (wid, i, action): the recovered
agent inserts a diagnostic step (admissible; observed plan-shift rate
0.30 scripted). The retried logical step now carries index i+1, so the
retry presents k′ = (wid, i+1, action) ≠ k → **duplicate** (or,
symmetrically, the shifted retry misses the original key and the effect
is lost while a phantom commits — both violate exactly-once).

In general, keys-alone pushes *all* of recovery correctness into a value
the harness cannot control after the crash. Any K depending on mutable
retry-time inputs admits an admissible recovery with K′ ≠ K. The only
escape is a K invariant across *all* admissible recoveries, which would
require constraining the LLM's re-synthesis — impossible for a general
agent harness. ∎

*Corollary (necessity of the log).* The source of truth for effect
identity must be fixed **before** the crash (a durable claim), not
re-derived after it. The write-ahead log is therefore *necessary*, not
merely convenient.

*Empirical counterpart.* Scripted sandbox, 1,500 episodes/condition,
in-window crash fraction 0.75: duplicate-effect rates — baseline (no
keys) 0.769, content-hash keys 0.367, deterministic keys 0.211,
write-ahead claim log **0.000**. The measured gap is the price of
re-derivation fragility.

## 4. Correctness: the WAL protocol guarantees exactly-once

> **Theorem 2 (Exactly-once under crash-recovery).** Under assumptions
> (A1) atomic idempotent T, (A2) durable L and C, (A3) crash-stop H only,
> (A4) epoch fencing, (A5) claim discipline — for **any** crash time t_c
> and **any** post-recovery agent behavior, every intended effect commits
> exactly once.

*Proof sketch* — case analysis on the crash landing for each step s:

- *Pre-step* (t_c < t_commit(s)). If t_c < t_claim(s): no durable trace;
  recovery treats s as never attempted; a fresh CLAIM with the
  deterministic key commits it once. If t_c ∈ [t_claim(s), t_commit(s)):
  the CLAIM is durable but the effect never committed; reconciliation
  replays it with the **original** key — T commits (call never arrived)
  or suppresses (key seen). Exactly once. ∎
- *In-window* (t_c ∈ W(s)). The effect committed; `COMMIT(s) ∉ L`; C not
  advanced past s. Reconciliation replays `CLAIM(s)` with its original
  key k; T finds k ∈ seen → `duplicate_suppressed`. C advances past s
  (log-fenced). Exactly once. ∎
- *Post-checkpoint* (t_c ≥ t_ckpt(s)). `COMMIT(s) ∈ L`, C advanced.
  Reconciliation skips s; the agent resumes after C. Exactly once. ∎
- *Stale writers.* Any in-flight pre-crash call arriving after recovery
  bears epoch e < e+1 = max_epoch → rejected by (A4). No zombie commits. ∎
- *Agent-behavior independence.* Reconciliation uses original keys from
  L — the agent is **never required to re-derive a key**. Post-recovery
  steps are checked against L by semantic identity before new claims
  issue, so reworded/shifted retries of claimed effects are skipped.
  The argument holds for arbitrary post-recovery behavior, including
  adversarial re-emission (observed: 11 consecutive re-emissions of
  committed effects, all suppressed, 0 duplicates over 70 LLM-driven
  episodes). ∎

*Remark (key determinism, sharpened).* The protocol requires keys to be
deterministic only **at claim time** (so a pre-crash claim and any
same-generation retry coincide). Post-crash *re-derivability* is
irrelevant — the log supplies the key. This is the precise point where
keys-alone fails and the WAL succeeds, and it is what Theorem 1
formalizes.

## 5. Assumptions and limits (stated honestly)

- **(L1) Tool idealization.** (A1) assumes atomic check-and-commit at T.
  Real tools with non-atomic or non-idempotent APIs need an adapter
  (e.g., a transactional outbox at the tool boundary); the theorem does
  not cover them. Same idealization as LIMBO's tool contract — cite it
  as shared ground, not as a weakness unique to this work.
- **(L2) Log durability.** (A2) is assumed, not proved. Log loss voids
  the guarantee — the standard WAL assumption, stated explicitly rather
  than buried.
- **(L3) Safety, not liveness.** Theorem 2 is a *safety* property
  (no duplicate commits; reconciliation gives at-least-once of *claimed*
  effects). It does **not** prove the agent will emit remaining claims —
  completeness depends on agent behavior and harness recovery policy.
  (See `MISSES_ANALYSIS.md`: the observed "misses" were the test
  harness's own attempt cap, now fixed; the protocol itself imposes no
  liveness bound, but neither does it guarantee agent progress.)
- **(L4) Semantic identity is a modeling choice.** The skip-logic keys on
  `(action, target)` as the stable business identity of an effect.
  Effects whose identity cannot be captured this way need a
  domain-specific identity function; misidentification breaks skipping
  in either direction. The paper must state the identity assumption per
  deployment.
- **(L5) Fault scope.** Crash-stop H only; no Byzantine harness, no
  tool-side crashes, single writer per workflow per epoch (fencing
  enforces this).
- **(L6) Claim discipline is enforced, not assumed.** (A5) held at 98.3%
  step-level in LLM validation because the harness *refuses* tool calls
  without valid claims — violations degrade to refused calls (missing,
  never duplicates). A deployment must preserve the refusal direction.

## 6. Positioning note (for the paper's intro / related work)

The expected reviewer objection — *"this is just write-ahead logging
applied to agents"* — is defeated in three moves, each grounded above:

1. **New fault class.** The checkpoint window (§2) is a harness-side
   crash-consistency gap absent from LIMBO's service-boundary taxonomy
   and, to our knowledge, from the crash-consistency literature as
   applied to agent harnesses. Classical WAL has no notion of it because
   classical writers do not re-synthesize their own transaction identity
   after a crash.
2. **Necessity, not analogy.** Theorem 1 shows the log is *required*:
   keys-alone is insufficient *in general* for LLM agents, not just in
   practice. The contribution is therefore the minimal durable structure
   that makes exactly-once possible under LLM re-synthesis
   nondeterminism — not "WAL applied to X".
3. **Non-trivial adaptation.** Semantic claim identity + log-fenced
   checkpoints + epoch fencing at the harness/tool boundary is not
   textbook WAL, which assumes a single writer with well-defined
   transaction boundaries and no post-crash identity re-synthesis. The
   adaptation — and the measured gap it closes (0.000 vs 0.211–0.769)
   — is the contribution.

Cite LIMBO as methodological foundation (fault-injection evaluation,
tool-contract idealization); ACRFence, AgentRewind, and the SagaLLM
family as nearest neighbors solving different problems (per the overlap
reports); the durable-execution literature (Temporal/DBOS-style) as the
systems lineage this work extends into the agent-harness setting.
