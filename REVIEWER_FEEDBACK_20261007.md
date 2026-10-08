# A1 Manuscript Review — Research Reviewer LLM (2026-10-07)

Private pre-submission assessment, not an official IEEE review. Reviewer checked
public literature and documentation; did not inspect or execute private code,
datasets, or experiment traces. Reviewed the complete 17-page October 2026 draft
(a1-manuscript-draft-pdf.pdf).

**Provisional judgment: not ready for TPDS submission.** More than presentation
changes needed, but the empirical work is a useful foundation.

## Major concerns

### 1. Theorem 1 does not establish universal insufficiency or necessity of a claim log
(High confidence)
The proof demonstrates failures of two constructions (content-hash keys,
positional keys). It does not prove every retry-time derivation fails. A key
derived from a stable, externally supplied business-operation identifier can
remain unchanged despite rewording or inserted steps. The corollary's second
jump is also unsupported: needing durable identity information does not establish
that an append-only write-ahead claim log is necessary — a durable operation
table, transactional workflow state, or recorded decision history could suffice.

Revision: narrow Theorem 1 to identity-unstable derivations, or formulate a
genuine information requirement (what persistent information is available, which
histories recovery cannot distinguish, why those histories require different
actions). Describe the claim log as sufficient unless proven necessary.
Defensible statement: "Idempotency keys derived from mutable argument text or
unstable plan positions cannot guarantee duplicate suppression across all
admissible recovery replans."

### 2. Theorem 2 conflates duplicate prevention with completion; semantic identity underspecified
(High confidence)
Theorem promises "every intended effect commits exactly once" for "any
post-recovery agent behavior." Section 5.4 says the protocol does not prove the
agent emits remaining claims — an agent that stops before creating a claim is an
immediate counterexample. Table 3: gpt-4o-mini completes exactly-once in 66/70
episodes despite zero duplicates. Calling these liveness failures is reasonable;
claiming 1.000 exactly-once across every campaign is not. The semantic skip
(action, target) can conflate distinct legitimate operations (initial email vs
reminder; two separately authorized partial refunds) or let reworded equivalents
evade suppression.

Revision: define logical effect identity; separate (a) at-most-once commitment
per durable claim identity, (b) eventual commitment of accepted claims under
explicit progress assumptions, (c) workflow completion (depends on planning and
recovery policy). Require identity to distinguish legitimate repeats and
recognize equivalent retries. Add tests for both. Report zero observed duplicates
separately from workflow completion in abstract, contributions, conclusion.

### 3. Strongest experiment does not establish advantage over a strong baseline
(High confidence)
Every LangGraph v2 campaign reports identical outcomes for WAL and deterministic
keys (0.0000 duplicates, 1.0000 exactly-once) — no demonstrated incremental
correctness benefit from the claim log in the strongest deployment evidence.
Section 6.3 deliberately does not use LangGraph's own checkpointer: evaluates
our recovery machinery inside a StateGraph but not superiority over properly
configured native persistence. Durable-execution comparison too restrictive:
Temporal places nondeterministic LLM calls in Activities outside deterministic
replay, so LLM nondeterminism alone does not establish durable execution cannot
handle this setting.

Revision: add baseline using native persistence + documented task boundaries +
durable operation identities + same receiver contract, under matched crash
schedules and recovery policies. Include a case where identities change across
recovery; show precisely what the stronger baseline cannot preserve. For TPDS:
measure fan-out sizes, concurrent workflows, recovery-log lengths.

### 4. Fencing ablation needs clearer causal explanation and fault model
(Medium-high confidence)
With an atomic idempotent receiver, a delayed old-generation call carrying the
original key should already be suppressed — removing fencing should not make
that same-key retry duplicate. Table 6's ~49% duplicates without fencing suggests
the zombie writer creates a new key, issues a new logical claim, or bypasses
another discipline — materially different mechanisms. The described zombie fault
(pre-crash process survives and retries) extends beyond the stated crash-stop
harness model. Rejecting older epochs does not by itself establish a single
writer within an epoch.

Revision: show an offending trace (claim identity, key, epoch, receiver
decision). Separate delayed same-key requests from surviving writers creating
fresh work. Specify epoch acquisition, ownership, atomic registration. Present
fencing as necessary for the demonstrated stale-writer property, not as the
generic cause of all no-fencing duplicates.

### 5. Related-work positioning needs substantive correction
(High confidence)
- LogAct: manuscript characterizes it as oversight logging that never treats
  the crash problem. Its full text explicitly discusses crash recovery,
  recovery from logged inference outputs, and fencing of old drivers (§3.2).
  Current dismissal is inaccurate.
- ACRFence: threat model includes crash-induced restore; mechanism logs effects
  and distinguishes equivalent replay from changed intent. Adversarial framing
  does not eliminate recovery-mechanism overlap.
- LIMBO: harness-crash testing distinction is supported, but attributing its
  residual 4% to our theorem overstates the connection (it distinguishes
  attempts with no original key from retries with a new key; discusses pinning
  a key per intent, §6.3).
- Missing foundational bibliography: classical WAL, durable execution, sagas
  lack entries. RIFL (Lee et al., SOSP 2015) especially relevant (RPC
  identification, durable atomic completion records, returned results, retry
  handling).
- Bibliographic metadata errors: refs [1], [2], [3] titles differ from public
  records; [1], [2], [3], [6] list "Anonymous" despite publicly available authors.

Revision: replace broad novelty assertions with a comparison table (fault model,
durable records, identity handling, receiver assumptions, fencing, guarantee,
evaluation). State the precise property our system adds.

### 6. Protocol specification omits crash/parallel recovery details
(High confidence on reporting gaps)
Open: epoch recovery/increase atomicity; whether duplicate calls return original
results (generated refund IDs/receipts may be needed downstream); partially
written JSONL records; parallel checkpoint advancement with gaps/dependencies;
serialization of concurrently emitted equivalent claims. Proof inconsistency: the
defined checkpoint window includes the interval after t_mark but before t_ckpt,
where a Commit record already exists — but the in-window proof case assumes it
does not.

Revision: specify state transitions, recovery outcomes, result persistence,
parallel completion frontier. Split proof cases at Claim durability, tool
commitment, Commit durability, checkpoint durability.

## Reporting corrections
- Abstract/contributions/conclusion: "perfect exactly-once across all campaigns"
  conflicts with Table 3's 66/70. Report safety and completion separately.
- §6.2/Table 3: "140 episodes" covers the initial two campaigns; the
  tightened-prompt campaign makes 210 if distinct. Give campaign-level totals;
  explain reuse vs independence.
- Table 5: caption says identical crash distributions, but exposures differ
  across conditions. Clarify pairing; report conditional results.
- §§6.3, 9: uniform routing reported as 214/214 decisions and later 180/180.
  Distinguish episodes from routing decisions.
- §6.4/tables: "duplicate rate" alternates between excess ledger commits and
  duplicate episodes. Define both measures and denominators.
- Abstract/overhead: 20.3 ms described as per-step overhead and as claim-log
  write latency. Identify exactly what each timing includes.
- Algorithm 1: semantic skip described as step 4 but appears on line 7. Correct.
- PDF: literal \S references, inconsistent Roman/Arabic table labels, stranded
  headings. Repair in submission template.

## Uncertainty quantification
Zero observed failures need bounds: 0/60 → one-sided exact 95% upper bound
≈4.87%; 0/1,500 → 0.20%. These describe the experimental distribution, not
production incidence. The "~1%" overhead claim is plausible but currently
estimated: report paired end-to-end latency, throughput, recovery time; account
for multiple durable writes per step.

## Recommended revision order
1. Define logical effect identity; separate safety from completion.
2. Repair or narrow both theorems.
3. Correct novelty comparison; specify the distributed protocol.
4. Evaluate against native durable persistence with stable operation identities.
5. Reconcile campaign counts, metrics, uncertainty, overhead.
6. Provide reviewer-accessible artifact; prepare journal-format manuscript.

## Suggested defensible central contribution
"A crash-recovery protocol that preserves tool-operation identities across agent
replanning, with explicit receiver assumptions and fault-injection evaluation."
