# A1 Phase 2 — Theory Repair Drafts (2026-10-08)

**Status:** DRAFTS ONLY. Neither `FORMAL_MODEL.md` nor `manuscript/main.tex` was edited
(sibling agents are drafting Phases 1 and 3 in parallel — no conflicts by construction).
Each item gives LOCATION, exact OLD TEXT, and exact NEW TEXT as a replacement spec.
Apply in Phase 5 (manuscript rewrite), after Mohammed resolves the flagged decision in 2.2.

**Empirical anchors used throughout** (Phase-4 results, verified):
- E2a positional shift: `det_shift` 46/60 duplicate episodes (0.7667 dup-ep rate), 46 missing effects, 14/60 exactly-once — BREAKS. `wal`: 0 duplicates, 60/60 exactly-once — HOLDS.
- E2b content rewording: `det_content` 46/60 duplicate episodes (92 excess commits), 14/60 exactly-once — BREAKS. `wal`: 0 duplicates, 60/60 exactly-once — HOLDS (canonicalized lookup).
- v2 stable-identity: deterministic keys tied WAL (0.0000 dup / 1.0000 eo, both) — keys suffice when identities are stable.
- E1 native persistence: 60/60 exactly-once, 0 duplicates — ties WAL under stable identities.
- E4 fencing: 102/102 offending calls class b (surviving-zombie fresh keys, stale epoch); 0 class a.

---

## 2.1 — Narrow Theorem 1 to identity-unstable derivations

**Reviewer objection:** the theorem demonstrates failures of two key schemes, not universal
insufficiency; stable externally supplied business-operation IDs are a counterexample.

### 2.1a — `FORMAL_MODEL.md`, §3 (replace theorem + proof sketch + corollary)

OLD TEXT (theorem):
> **Theorem 1 (Keys-alone insufficiency).** Let K be any idempotency-key derivation computed by the *recovered* agent at retry time from retry-time inputs (argument text, plan position, or any function thereof). If post-recovery re-synthesis is unconstrained — the agent may reword arguments or restructure the plan — then a keys-only retry protocol cannot guarantee exactly-once under in-window crashes.

NEW TEXT:
> **Theorem 1 (Retry-time key fragility).** Let K be an idempotency-key derivation computed by the *recovered* agent at retry time from retry-time inputs that are *mutable under re-synthesis* — argument text the agent may reword, or plan positions the recovery replan may shift. If post-recovery re-synthesis is unconstrained over those inputs, then a keys-only retry protocol cannot guarantee duplicate suppression across all admissible recovery replans under in-window crashes.

OLD TEXT (proof sketch): the existing two-case sketch ending "…impossible for a general agent harness. ∎"

NEW TEXT (proof sketch):
*Proof sketch.* Fix a step s committed in-window under k = K(pre-crash inputs). Two admissible
recoveries inside the mutable-input class:

(i) *Content-hash keys*, K = H(action, args): the recovered agent rewords the arguments to
a′ ≠ a (admissible). The retry presents k′ = H(action, a′) ≠ k. T has never seen k′ → commits
again → **duplicate**. *Empirical witness (E2b):* recovery-side target rewording broke
deterministic content-hash keys on 46/60 episodes (92 excess commits, 14/60 exactly-once);
the WAL held 60/60 via canonicalized identity lookup.

(ii) *Deterministic position keys*, K = (wid, i, action): the recovered agent rotates branch
indices on replan (admissible). The retried logical step carries i′ ≠ i, so the retry presents
k′ = (wid, i′, action) ≠ k → **duplicate**; symmetrically, a shifted retry whose new key
collides with an already-committed key is wrongly suppressed → **lost effect**. *Empirical
witness (E2a):* positional shift broke deterministic keys on 46/60 episodes with 46 missing
effects (14/60 exactly-once); the WAL held 60/60 via `find_by_identity` key reuse.

The failure is a property of the *class* — retry-time derivations from mutable inputs — not of
the two schemes: any K in the class admits an admissible recovery with K′ ≠ K, because the
harness cannot constrain re-synthesis inputs after the crash. ∎

*Scope.* The theorem is silent on keys that are **not** retry-time derivations: durable
business-operation IDs assigned by the tool or domain and passed through unchanged
(e.g., RIFL-style unique IDs, payment transaction IDs) lie outside its domain and may suffice;
the theorem neither covers nor refutes them. This is exactly the boundary the evaluation maps:
under stable identities, deterministic keys tie the WAL (v2 LangGraph: 0.0000/1.0000 both;
E1 native persistence: 60/60); under identity shift they fail (E2a/E2b). The theorem
characterizes the failure side of that boundary.

OLD TEXT (corollary):
> *Corollary (necessity of the log).* The source of truth for effect identity must be fixed **before** the crash (a durable claim), not re-derived after it. The write-ahead log is therefore necessary, not merely convenient.

NEW TEXT:
> *Corollary (durable identity information).* The source of truth for effect identity must be fixed **before** the crash — a durable write-ahead identity record binding the effect's logical identity to its key — not re-derived after it. The *information* (a durable pre-commit identity record) is necessary; the append-only claim log is our sufficient mechanism (see 2.2).

OLD TEXT (empirical counterpart):
> *Empirical counterpart.* Scripted sandbox, 1,500 episodes/condition, in-window crash fraction 0.75: duplicate-effect rates — baseline (no keys) 0.769, content-hash keys 0.367, deterministic keys 0.211, write-ahead claim log **0.000**. The measured gap is the price of re-derivation fragility.

NEW TEXT:
> *Empirical counterpart.* Scripted sandbox, 1,500 episodes/condition, in-window crash fraction 0.75: duplicate-effect rates — baseline (no keys) 0.769, content-hash keys 0.367, deterministic keys 0.211, write-ahead claim log **0.000**. LangGraph production port with real SIGKILL: under *stable* identities deterministic keys tie the WAL (0.0000/1.0000, both; E1 native persistence likewise 60/60) — keys suffice there. Under *identity shift across recovery* (E2a positional, E2b content rewording), deterministic keys break on 46/60 episodes each while the WAL holds 60/60. The measured gap is the price of re-derivation fragility, paid exactly where Theorem 1 says it is due.

### 2.1b — `manuscript/main.tex`, Formal Analysis § (replace theorem block)

OLD TEXT:
```latex
\begin{theorem}[Keys-alone insufficiency]
Let $K$ be any idempotency-key derivation computed by the
\emph{recovered} agent at retry time from retry-time inputs
(argument text, plan position, or any function thereof). If
post-recovery re-synthesis is unconstrained---the agent may
reword arguments or restructure the plan---then a keys-only retry
protocol cannot guarantee exactly-once under in-window crashes.
\end{theorem}
```

NEW TEXT:
```latex
\begin{theorem}[Retry-time key fragility]
Let $K$ be an idempotency-key derivation computed by the
\emph{recovered} agent at retry time from retry-time inputs that
are \emph{mutable under re-synthesis}---argument text the agent
may reword, or plan positions the recovery replan may shift. If
post-recovery re-synthesis is unconstrained over those
inputs, then a keys-only retry protocol cannot guarantee
duplicate suppression across all admissible recovery replans
under in-window crashes.
\end{theorem}
```

### 2.1c — `manuscript/main.tex` (replace proof sketch of Theorem 1)

OLD TEXT: the existing `\begin{proof}[Proof sketch] ... \end{proof}` for Theorem 1
(the two-case sketch ending "impossible for a general agent harness.").

NEW TEXT:
```latex
\begin{proof}[Proof sketch]
Fix a step $s$ committed in-window under $k = K(\text{pre-crash
inputs})$. Two admissible recoveries inside the mutable-input
class. (i) \emph{Content-hash keys}, $K = H(\mathit{action},
\mathit{args})$: the recovered agent rewords the arguments to
$a' \ne a$ (admissible). The retry presents
$k' = H(\mathit{action}, a') \ne k$; $T$ has never seen $k'$
and commits again---a duplicate. Empirical witness (E2b):
recovery-side rewording broke content-hash keys on 46/60
episodes (92 excess commits); the WAL held 60/60 via
canonicalized identity lookup. (ii) \emph{Deterministic
position keys}, $K = (\mathit{wid}, i, \mathit{action})$: the
recovered agent rotates branch indices on replan (admissible).
The retried logical step carries $i' \ne i$, so the retry
presents $k' = (\mathit{wid}, i', \mathit{action}) \ne k$---a
duplicate; symmetrically, a shifted retry whose new key
collides with an already-committed key is wrongly
suppressed---a lost effect. Empirical witness (E2a): positional
shift broke deterministic keys on 46/60 episodes with 46 missing
effects; the WAL held 60/60 via \texttt{find\_by\_identity} key
reuse. The failure is a property of the \emph{class}---retry-time
derivations from mutable inputs---not of the two schemes: any
$K$ in the class admits an admissible recovery with
$K' \ne K$, because the harness cannot constrain re-synthesis
inputs after the crash.
\end{proof}

\begin{remark}[Scope]
The theorem is silent on keys that are \emph{not} retry-time
derivations: durable business-operation IDs assigned by the tool
or domain and passed through unchanged lie outside its domain
and may suffice. This is exactly the boundary our evaluation
maps: under stable identities deterministic keys tie the WAL
(v2: 0.0000/1.0000 both; E1 native persistence 60/60); under
identity shift they fail (E2a/E2b).
\end{remark}
```

### 2.1d — `manuscript/main.tex` (replace Corollary "Necessity of the log")

OLD TEXT:
```latex
\begin{corollary}[Necessity of the log]
The source of truth for effect identity must be fixed
\emph{before} the crash (a durable claim), not re-derived after
it. The write-ahead log is therefore necessary, not merely
convenient.
\end{corollary}
```

NEW TEXT:
```latex
\begin{corollary}[Durable identity information]
The source of truth for effect identity must be fixed
\emph{before} the crash---a durable write-ahead identity record
binding the effect's logical identity to its key---not
re-derived after it. The \emph{information} (a durable
pre-commit identity record) is necessary; the append-only claim
log is a sufficient mechanism, not the unique one.
\end{corollary}
```

### 2.1e — `manuscript/main.tex` (empirical counterpart paragraph)

OLD TEXT:
```latex
\emph{Empirical counterpart.} Scripted sandbox, 1,500
episodes/condition, in-window crash fraction 0.75:
duplicate-effect rates---baseline (no keys) 0.7687,
content-hash keys 0.3667, deterministic keys 0.2113,
write-ahead claim log \textbf{0.0000}. The measured gap is the
price of re-derivation fragility.
```

NEW TEXT:
```latex
\emph{Empirical counterpart.} Scripted sandbox, 1,500
episodes/condition, in-window crash fraction 0.75:
duplicate-effect rates---baseline (no keys) 0.7687,
content-hash keys 0.3667, deterministic keys 0.2113,
write-ahead claim log \textbf{0.0000}. LangGraph production
port with real \texttt{SIGKILL}: under \emph{stable} identities
deterministic keys tie the WAL (0.0000/1.0000 both; E1 native
persistence likewise 60/60)---keys suffice there. Under
\emph{identity shift across recovery} (E2a positional, E2b
content rewording), deterministic keys break on 46/60 episodes
each while the WAL holds 60/60. The measured gap is the price
of re-derivation fragility, paid exactly where Theorem~1 says
it is due.
```

### 2.1f — `manuscript/main.tex`, Introduction contribution (2)

OLD TEXT:
```latex
We prove (Theorem~1) that \emph{any}
idempotency-key derivation computed at retry time from retry-time
inputs is insufficient in general under unconstrained LLM
re-synthesis---the log is necessary, not merely convenient---and
(Theorem~2) that the protocol guarantees exactly-once for
arbitrary crash times and arbitrary post-recovery agent behavior.
```

NEW TEXT:
```latex
We prove (Theorem~1) that idempotency-key derivations computed
at retry time from \emph{mutable} inputs---rewordable argument
text, shiftable plan positions---cannot guarantee duplicate
suppression across all admissible recovery replans, and show
empirically where that boundary lies (E2a/E2b); durable
write-ahead identity information is the necessary ingredient,
and our claim log is a sufficient mechanism. Theorem~2 then
separates what the protocol guarantees: at-most-once commitment
per durable claim identity (safety), eventual commitment of
accepted claims under explicit progress assumptions, and
workflow completion as a property of the planning policy, not
the protocol.
```

### 2.1g — `manuscript/main.tex`, Discussion (~line 912, "This is why Theorem~1 matters")

OLD TEXT:
```latex
This is why Theorem~1 matters beyond the formalism: it says
the boundary is not an artifact of our two key schemes but a
property of \emph{any} retry-time derivation under
unconstrained re-synthesis. A practitioner reading our v2
result (``deterministic keys work here'') might conclude keys
suffice; the v1 result and the theorem together say that
conclusion does not transfer. The write-ahead log is the
mechanism that makes recovery independent of which side of
the boundary a given deployment lands on.
```

NEW TEXT:
```latex
This is why Theorem~1 matters beyond the formalism: it says
the boundary is not an artifact of our two key schemes but a
property of \emph{retry-time derivations from mutable inputs}
under unconstrained re-synthesis. A practitioner reading our v2
result (``deterministic keys work here'') might conclude keys
suffice; E2a/E2b and the theorem together say that conclusion
does not transfer across the identity-stability boundary---it
holds only while identities survive recovery, which is not a
property the harness can assume. The write-ahead claim log is
the mechanism that makes recovery independent of which side of
the boundary a given deployment lands on.
```

### 2.1h — `FORMAL_MODEL.md`, §6 positioning note, point 2

OLD TEXT:
> 2. **Necessity, not analogy.** Theorem 1 shows the log is *required*: keys-alone is insufficient *in general* for LLM agents, not just in practice. The contribution is therefore the minimal durable structure that makes exactly-once possible under LLM re-synthesis nondeterminism — not "WAL applied to X".

NEW TEXT:
> 2. **Necessity of the information, not analogy.** Theorem 1 shows *durable write-ahead identity information* is required: keys derived at retry time from mutable inputs are insufficient across admissible replans — not just in practice, and not just for our two schemes (E2a/E2b are the empirical witnesses). The contribution is therefore the minimal durable structure that makes exactly-once possible under LLM re-synthesis nondeterminism — not "WAL applied to X". The append-only log is our sufficient mechanism; an equivalent durable operation table would satisfy the same requirement.

---

## 2.2 — Claim-log necessity → sufficiency ⚠️ NEEDS-MOHAMMED-DECISION

**Reviewer objection:** durable identity information does not prove an append-only claim log is
uniquely necessary — a durable operation table could suffice.

**Analysis.** A full necessity proof would have to rule out *every* durable structure carrying
pre-commit identity information. But a durable (identity → status) operation table written
*before* the tool call **is** a write-ahead claim under a different schema — the information
requirement is identical; only the data structure differs. What Theorem 1 (contrapositive)
actually establishes is necessity of the *information*: without any durable pre-crash identity
record, retry-time derivation fails. The schema (append-only JSONL log vs. op table vs. embedded
claim fields in the checkpointer) is an implementation choice among mechanisms satisfying that
requirement.

**Recommendation (drafting agent): adopt (b).** Option (a) — keep claiming the log itself is
necessary with a formal information-requirement argument — re-invites the exact objection the
reviewer already raised, and we cannot win it honestly: the op-table counterexample is valid.
Option (b) — "durable write-ahead identity record necessary; append-only log sufficient" — is
honest, reviewer-proof, and arguably *strengthens* the paper: it answers "is this just WAL?"
with "the information requirement is the contribution; the log is the evaluated mechanism."
All draft text below implements (b).

**NEEDS-MOHAMMED-DECISION:** (a) keep the strong "log necessary" claim, or (b) adopt the
"durable write-ahead identity record necessary; append-only log sufficient" framing?
Drafts below assume (b). If he picks (a), the corollary/remark drafts in 2.1d and 2.1h must be
reverted to necessity language and a formal information-requirement proof attempted (flagged as
high-risk).

### 2.2a — `FORMAL_MODEL.md`, §5 limits: add explicit limit

NEW TEXT (append to §5 as new limit; renumber subsequent as needed):
> - **(L7) Mechanism vs. information.** The theorems establish necessity of *durable write-ahead identity information* (Corollary, §3), not uniqueness of the append-only log schema. A durable operation table (identity → status) written before each tool call would satisfy the same requirement; our JSONL claim log is the evaluated sufficient mechanism. Claims in the paper about "necessity" refer to the information, never the schema.

### 2.2b — `manuscript/main.tex`, Assumptions and limits: add matching limit

NEW TEXT (append after the existing limits, before or within the limits subsection):
```latex
\textbf{(L7) Mechanism vs.\ information.} The theorems establish
necessity of \emph{durable write-ahead identity information},
not uniqueness of the append-only log schema. A durable
operation table (identity $\to$ status) written before each
tool call would satisfy the same requirement; our claim log is
the evaluated sufficient mechanism. Necessity claims in this
paper refer to the information, never the schema.
```

---

## 2.3 — Define logical effect identity

**Reviewer objection:** semantic identity underspecified — two legitimate refunds to the same
recipient must not be conflated; equivalent retries must be recognized.

### 2.3a — `FORMAL_MODEL.md`, §1 (new definition, after the Claim discipline paragraph)

NEW TEXT:
> **Logical effect identity.** A logical effect identity is a function id: E → I from tool effects to an identity space, supplied per deployment, satisfying: (i) *stability* — id is invariant under argument rewording and plan repositioning (it captures business meaning, not surface form); (ii) *discrimination* — distinct business intents map to distinct identities even when (action, target) coincide (e.g., two separately authorized refunds to the same recipient differ by an occurrence/authorization component); (iii) *retry equivalence* — a post-recovery retry r of a claimed effect c is *equivalent* iff id(r) = id(c); equivalent retries must be suppressed, non-equivalent effects must both commit.
>
> Default instantiation: id = (action, target, occurrence), where *occurrence* disambiguates legitimate repetitions. Misidentification breaks the protocol in either direction (over-suppression of distinct intents, or duplicate commits of equivalent retries); the identity function is therefore a deployment modeling assumption (cf. L4), not a theorem. All "exactly-once" claims in §4 are per *durable claim identity* under the deployment's id.

### 2.3b — `manuscript/main.tex`, Formal Analysis (new definition block before the Correctness subsection)

NEW TEXT (insert immediately before `\subsection{Correctness: the protocol guarantees exactly-once}`):
```latex
\begin{definition}[Logical effect identity]
A \emph{logical effect identity} is a function
$\mathit{id}: \mathcal{E} \to \mathcal{I}$ from tool effects to
an identity space, supplied per deployment, satisfying:
(i)~\emph{stability}---$\mathit{id}$ is invariant under argument
rewording and plan repositioning (business meaning, not surface
form); (ii)~\emph{discrimination}---distinct business intents
map to distinct identities even when $(\mathit{action},
\mathit{target})$ coincide (e.g., two separately authorized
refunds to the same recipient differ by an
occurrence/authorization component); (iii)~\emph{retry
equivalence}---a post-recovery retry $r$ of a claimed effect $c$
is \emph{equivalent} iff $\mathit{id}(r) = \mathit{id}(c)$;
equivalent retries must be suppressed, non-equivalent effects
must both commit. Default instantiation:
$\mathit{id} = (\mathit{action}, \mathit{target},
\mathit{occurrence})$. Misidentification breaks the protocol in
either direction; the identity function is a deployment
modeling assumption, not a theorem. All exactly-once claims
below are per \emph{durable claim identity} under the
deployment's $\mathit{id}$.
\end{definition}
```

---

## 2.4 — Split Theorem 2 into (a) safety, (b) conditional liveness, (c) policy-dependent completion

**Reviewer objection:** Theorem 2 conflates safety (zero duplicates — proven) with
completion/liveness (66/70 — not proven).

### 2.4a — `FORMAL_MODEL.md`, §4 (replace theorem + proof sketch)

OLD TEXT (theorem):
> **Theorem 2 (Exactly-once under crash-recovery).** Under assumptions (A1) atomic idempotent T, (A2) durable L and C, (A3) crash-stop H only, (A4) epoch fencing, (A5) claim discipline — for **any** crash time t_c and **any** post-recovery agent behavior, every intended effect commits exactly once.

NEW TEXT:
> **Theorem 2a (At-most-once commitment — safety).** Under (A1) atomic idempotent T, (A2) durable L and C, (A3) crash-stop H only, (A4) epoch fencing, (A5) claim discipline — for **any** crash time t_c and **any** post-recovery agent behavior, no durable claim identity (per the deployment's id, §1) commits more than one tool effect.
>
> **Theorem 2b (Eventual commitment of accepted claims — conditional liveness).** Under (A1)–(A5) plus progress assumptions (P1) T eventually processes every call it accepts, (P2) the harness eventually runs recovery to completion, (P3) fencing epochs are acquired atomically — every CLAIM durably accepted into L is eventually committed by T. Accepted claims are at-least-once; with 2a, exactly-once per claim identity.
>
> **Theorem 2c (Workflow completion — policy-dependent).** The protocol does **not** guarantee the agent emits the remaining claims of a workflow; completion is a property of the planning/recovery policy, not the protocol. The measured 66/70 completion (94.29%, gpt-4o-mini; the 4 misses were model re-emission loops, a supervisor-policy behavior) is an empirical completion rate under a specific policy, not a liveness proof. Safety (2a) held on all 70 episodes including the 4 incomplete ones: 0 duplicates.

(The existing proof sketch becomes the proof sketch for **2a**; append:)
> *Proof sketch for 2b.* Reconciliation replays every CLAIM without a matching COMMIT using its original key (§1, recovery path step 2). By (P2) reconciliation runs to completion; each replayed call either finds its key at T (already committed — done) or commits it (P1); (P3) guarantees the replaying epoch owns the workflow so no conflicting writer interferes. Hence every accepted claim is eventually committed. ∎
> *2c is a non-theorem* (stated as a scope delimitation): no protocol acting below the planning layer can compel a planner to emit claims; the 66/70 measurement is reported as evidence about the *supervisor policy*, not the protocol.

### 2.4b — `manuscript/main.tex` (replace Theorem 2 block and proof sketch)

OLD TEXT:
```latex
\begin{theorem}[Exactly-once under crash-recovery]
Under (A1) atomic idempotent $T$, (A2) durable $L$ and $C$,
(A3) crash-stop $H$ only, (A4) epoch fencing, (A5) claim
discipline---for \textbf{any} crash time $t_c$ and \textbf{any}
post-recovery agent behavior, every intended effect commits
exactly once.
\end{theorem}
```

NEW TEXT:
```latex
\begin{theorem}[At-most-once commitment]
Under (A1) atomic idempotent $T$, (A2) durable $L$ and $C$,
(A3) crash-stop $H$ only, (A4) epoch fencing, (A5) claim
discipline---for \textbf{any} crash time $t_c$ and
\textbf{any} post-recovery agent behavior, no durable claim
identity (per the deployment's $\mathit{id}$) commits more than
one tool effect.
\end{theorem}

\begin{theorem}[Eventual commitment of accepted claims]
Under (A1)--(A5) plus progress assumptions (P1) $T$ eventually
processes every call it accepts, (P2) the harness eventually
runs recovery to completion, (P3) fencing epochs are acquired
atomically---every \textsc{Claim} durably accepted into $L$ is
eventually committed by $T$. Accepted claims are at-least-once;
with Theorem~2a, exactly-once per claim identity.
\end{theorem}

\begin{remark}[Workflow completion is policy-dependent]
The protocol does \textbf{not} guarantee the agent emits the
remaining claims of a workflow; completion is a property of the
planning/recovery policy, not the protocol. The measured 66/70
completion (94.29\%, gpt-4o-mini; the 4 misses were model
re-emission loops, a supervisor-policy behavior) is an empirical
completion rate under a specific policy, not a liveness proof.
Safety held on all 70 episodes including the 4 incomplete ones:
0 duplicates.
\end{remark}
```

(Then the existing proof sketch follows as the proof of the at-most-once theorem, with the
case analysis repaired per 2.5 below; append the 2b proof sketch:)
```latex
\begin{proof}[Proof sketch for eventual commitment]
Reconciliation replays every \textsc{Claim} without a matching
\textsc{Commit} using its original key. By (P2) reconciliation
runs to completion; each replayed call either finds its key at
$T$ (already committed) or commits it (P1); (P3) guarantees the
replaying epoch owns the workflow. Hence every accepted claim
is eventually committed.
\end{proof}
```

### 2.4c — `FORMAL_MODEL.md`, §5: L3 already states safety-not-liveness; align its wording

OLD TEXT:
> - **(L3) Safety, not liveness.** Theorem 2 is a *safety* property (no duplicate commits; reconciliation gives at-least-once of *claimed* effects). It does **not** prove the agent will emit remaining claims — completeness depends on agent behavior and harness recovery policy. (See `MISSES_ANALYSIS.md`: the observed "misses" were the test harness's own attempt cap, now fixed; the protocol itself imposes no liveness bound, but neither does it guarantee agent progress.)

NEW TEXT:
> - **(L3) Safety, conditional liveness, no workflow-completion guarantee.** Theorem 2a is a *safety* property (no duplicate commits per claim identity). Theorem 2b gives at-least-once of *claimed* effects only under explicit progress assumptions (P1–P3). Neither proves the agent will emit remaining claims — workflow completion depends on the planning/recovery policy (Theorem 2c; measured 66/70 under the gpt-4o-mini supervisor policy). (See `MISSES_ANALYSIS.md`: the observed "misses" were the test harness's own attempt cap, now fixed; the protocol itself imposes no liveness bound, but neither does it guarantee agent progress.)

---

## 2.5 — Fix the proof inconsistency (Commit durability inside the checkpoint window)

**Reviewer objection:** the proof assumes `COMMIT(s) ∉ L` throughout the in-window case, but the
event ordering `t_commit < t_mark < t_ckpt` means the sub-interval `[t_mark, t_ckpt) ⊂ W(s)`
has `COMMIT(s) ∈ L`. The old conclusion (exactly once) still held — the idempotent receiver
suppresses by key either way — but the case analysis was unsound as written.

### 2.5a — `FORMAL_MODEL.md`, §4: replace the proof sketch's case analysis

OLD TEXT: the bullet list ("*Pre-step* … *In-window* … *Post-checkpoint* … *Stale writers.* … *Agent-behavior independence.* …").

NEW TEXT (replaces the per-step case bullets; keep *Stale writers* and *Agent-behavior independence* with the small edits noted):
- *Case 1 — before CLAIM durable* (t_c < t_claim(s)). No durable trace; recovery treats s as never attempted; a fresh CLAIM with the claim-time key commits it once. Exactly once.
- *Case 2 — CLAIM durable, call never arrived* (t_c ∈ [t_claim(s), t_call(s))). Reconciliation replays with the original key; T has never seen it → commits. Exactly once.
- *Case 3 — effect committed, COMMIT not yet durable* (t_c ∈ [t_call(s), t_mark(s))). By (A1) atomicity the effect committed exactly when the call arrived. COMMIT(s) ∉ L. Reconciliation replays with the original key; T finds the key → `duplicate_suppressed`; then COMMIT is written and C advances (log-fenced). Exactly once. (This is the true in-window sub-case.)
- *Case 4 — COMMIT durable, checkpoint not yet advanced* (t_c ∈ [t_mark(s), t_ckpt(s))). COMMIT(s) ∈ L but C not advanced past s — **the sub-case the previous version mishandled** (it asserted COMMIT(s) ∉ L throughout W(s), but [t_mark, t_ckpt) ⊂ W(s)). Reconciliation finds the CLAIM+COMMIT pair and issues **no replay**; C advances past s (log-fenced). No duplicate, no loss. Exactly once.
- *Case 5 — post-checkpoint* (t_c ≥ t_ckpt(s)). COMMIT(s) ∈ L, C advanced. Reconciliation skips s; the agent resumes after C. Exactly once.
- *Stale writers.* Any in-flight pre-crash call arriving after recovery bears e < max_epoch → rejected by (A4). No zombie commits. (E4: 102/102 offending calls were this class; 0 same-key recommit attempts succeeded.)
- *Agent-behavior independence.* Reconciliation uses original keys from L — the agent is **never required to re-derive a key**. Post-recovery steps are checked against L by logical effect identity (Definition, §1) before new claims issue, so reworded/shifted retries of claimed effects are recognized as equivalent and skipped. The argument holds for arbitrary post-recovery behavior, including adversarial re-emission (observed: 11 consecutive re-emissions of committed effects, all suppressed, 0 duplicates over 70 LLM-driven episodes). ∎

### 2.5b — `manuscript/main.tex`: replace the proof sketch's case analysis

OLD TEXT:
```latex
\begin{proof}[Proof sketch]
Case analysis on the crash landing for each step $s$.
\emph{Pre-step} ($t_c < t_{\mathrm{commit}}(s)$): if
$t_c < t_{\mathrm{claim}}(s)$, no durable trace exists and
recovery treats $s$ as never attempted; if
$t_c \in [t_{\mathrm{claim}}(s), t_{\mathrm{commit}}(s))$, the
\textsc{Claim} is durable but the effect never committed, so
reconciliation replays it with the original key---$T$ commits or
suppresses atomically. \emph{In-window} ($t_c \in W(s)$): the
effect committed but $\textsc{Commit}(s) \notin L$;
reconciliation replays $\textsc{Claim}(s)$ with its original key
$k$; $T$ finds $k$ seen and suppresses the duplicate; $C$
advances past $s$. \emph{Post-checkpoint}
($t_c \ge t_{\mathrm{ckpt}}(s)$): $\textsc{Commit}(s) \in L$ and
$C$ advanced; reconciliation skips $s$. \emph{Stale writers:}
any in-flight pre-crash call arriving after recovery bears
$e < \mathit{max\_epoch}$ and is rejected by (A4).
\emph{Agent-behavior independence:} reconciliation uses original
keys from $L$---the agent never re-derives a key---and
post-recovery steps are checked against $L$ by semantic identity
before new claims issue. The argument holds for arbitrary
post-recovery behavior, including adversarial re-emission
(observed: 11 consecutive re-emissions of committed effects, all
suppressed, 0 duplicates over 70 LLM-driven episodes).
\end{proof}
```

NEW TEXT:
```latex
\begin{proof}[Proof sketch for at-most-once]
Case analysis on the crash landing for each step $s$, split at
every durability boundary. \emph{Case 1---before
\textsc{Claim} durable} ($t_c < t_{\mathrm{claim}}(s)$): no
durable trace exists; recovery treats $s$ as never attempted and
a fresh \textsc{Claim} with the claim-time key commits it once.
\emph{Case 2---\textsc{Claim} durable, call never arrived}
($t_c \in [t_{\mathrm{claim}}(s), t_{\mathrm{call}}(s))$):
reconciliation replays with the original key; $T$ has never seen
it and commits. \emph{Case 3---effect committed,
\textsc{Commit} not yet durable}
($t_c \in [t_{\mathrm{call}}(s), t_{\mathrm{mark}}(s))$): by
(A1) atomicity the effect committed exactly when the call
arrived, but $\textsc{Commit}(s) \notin L$. Reconciliation
replays with the original key; $T$ finds the key and suppresses
the duplicate; then \textsc{Commit} is written and $C$ advances
(log-fenced). This is the true in-window sub-case.
\emph{Case 4---\textsc{Commit} durable, checkpoint not yet
advanced} ($t_c \in [t_{\mathrm{mark}}(s),
t_{\mathrm{ckpt}}(s))$): $\textsc{Commit}(s) \in L$ but $C$ not
advanced past $s$. Reconciliation finds the
\textsc{Claim}+\textsc{Commit} pair and issues \emph{no replay};
$C$ advances past $s$. No duplicate, no loss. (The previous
version asserted $\textsc{Commit}(s) \notin L$ throughout $W(s)$;
since $t_{\mathrm{mark}} < t_{\mathrm{ckpt}}$, the sub-interval
$[t_{\mathrm{mark}}, t_{\mathrm{ckpt}}) \subset W(s)$ already has
the \textsc{Commit} durable. The old conclusion held---the
receiver suppresses by key either way---but the case analysis
was unsound as written; this split repairs it.)
\emph{Case 5---post-checkpoint} ($t_c \ge t_{\mathrm{ckpt}}(s)$):
$\textsc{Commit}(s) \in L$ and $C$ advanced; reconciliation
skips $s$ and the agent resumes after $C$. \emph{Stale writers:}
any in-flight pre-crash call arriving after recovery bears
$e < \mathit{max\_epoch}$ and is rejected by (A4); no zombie
commits (E4: 102/102 offending calls were this class; 0
same-key recommit attempts succeeded).
\emph{Agent-behavior independence:} reconciliation uses original
keys from $L$---the agent never re-derives a key---and
post-recovery steps are checked against $L$ by logical effect
identity before new claims issue, so reworded or shifted
retries of claimed effects are recognized as equivalent and
skipped. The argument holds for arbitrary post-recovery
behavior, including adversarial re-emission (observed: 11
consecutive re-emissions of committed effects, all suppressed,
0 duplicates over 70 LLM-driven episodes).
\end{proof}
```

---

## Application notes for Phase 5 (manuscript rewrite)

1. The remark "Key determinism, sharpened" (`FORMAL_MODEL.md` §4, `main.tex`) remains valid
   unchanged — it is now *more* central: claim-time determinism is all the protocol needs,
   which is exactly why retry-time re-derivation (Theorem 1's domain) is the fragile part.
2. `FORMAL_MODEL.md` §6 point 1 ("New fault class") is unaffected. Point 3 ("Non-trivial
   adaptation") is unaffected.
3. The abstract/conclusion safety-vs-completion split (checklist 1.6, Phase 1 sibling) must use
   the 2a/2b/2c vocabulary: "at-most-once commitment per durable claim identity (safety),
   eventual commitment of accepted claims under progress assumptions, workflow completion
   policy-dependent."
4. Uncertainty bounds (checklist 1.8): 0/60 → one-sided exact 95% upper bound ≈ 4.87% applies
   to the WAL's 60/60 E2a/E2b holds and E1's 60/60; 0/1,500 → ≈ 0.20% for the sandbox campaign.
5. If Mohammed picks 2.2 option (a) instead of (b), revert 2.1d, 2.1h, 2.2a, 2.2b to necessity
   language and attempt the formal information-requirement proof (high risk — not recommended).

## Checklist mapping

- [x] 2.1 drafted (2.1a–2.1h) — narrowed theorem, scope remark, empirical witnesses, intro + discussion updates
- [x] 2.2 drafted (2.2a–2.2b) — ⚠️ NEEDS-MOHAMMED-DECISION: (a) vs (b); drafts assume (b)
- [x] 2.3 drafted (2.3a–2.3b) — logical effect identity definition, both files
- [x] 2.4 drafted (2.4a–2.4c) — Theorem 2 → 2a/2b/2c, both files
- [x] 2.5 drafted (2.5a–2.5b) — six-case proof split repairing the Commit-durability inconsistency
