# A1 Phase 3 — Protocol Specification Revisions (drafted 2026-10-07, $0)

Ground truth: `langgraph_port/claim_log.py`, `tool_server.py`, `file_tool.py`,
`checkpoint_store.py`, `common.py`, `agent_graph_v2.py` (recover_node, w_claim_node,
dispatch_router, worker_sub_node), `agent_graph.py` (v1 recover_node).
Sibling agents are drafting Phases 1–2 in parallel: do NOT edit
`manuscript/main.tex` here — apply these replacements when the phases merge.

Reviewer ask: "Protocol specification gaps: atomic epoch acquisition/recovery;
returning original results on duplicate calls; partial JSONL records; parallel
completion frontier/dependencies; concurrent equivalent claims; proof
inconsistency around Commit durability inside the checkpoint window."
(The proof inconsistency is Phase 2's item 2.5; this file covers the four
protocol-spec items 3.1–3.4.)

---

## Part A — Self-contained protocol specification

### A.1 Epoch acquisition, ownership, and atomicity (checklist 3.1)

**What the code does.**

- *Fresh generation.* `plan_node` (agent_graph_v2.py) writes `epoch.json =
  {epoch: 0}` and calls `FileTool.set_epoch(0)`, both via
  `atomic_write_json` (common.py: temp file + fsync + `os.replace` + directory
  fsync — each individual write is crash-atomic).
- *Recovery.* `recover_node` reads `epoch.json`, computes
  `new_epoch = stored + 1`, writes `epoch.json` (atomic), then `POST /fence
  {workflow_id, epoch: new_epoch}` to the tool server, then
  `FileTool.set_epoch(new_epoch)`. The tool server keeps
  `max_epoch[workflow_id]` (durable in `epochs.json`, rewritten atomically)
  and only ever increases it: `fence()` is `max`-monotonic, and `call()` also
  bumps `max_epoch` when a call arrives with `epoch > cur` (permissive
  self-registration). The file tool keeps its own durable epoch in
  `tool_epoch.json` (atomic rewrite) and raises `FencedError` for any call
  with `epoch < get_epoch()`.
- *Ordering.* The local `epoch.json` write happens BEFORE the `/fence` POST.
  A crash in between leaves the epoch "used up" locally but never registered
  at the server; the next recovery reads N+1 and registers N+2. Safe
  (monotonic), slightly wasteful. The fence POST is `r.raise_for_status()`,
  so a failed registration aborts recovery rather than proceeding unfenced.

**Ownership.** An epoch is owned by one agent generation (one OS process).
The durable arbiter is the tool server's `max_epoch` per workflow; `epoch.json`
is the harness-side durable record; `tool_epoch.json` is the file-tool-side
record. Fencing is enforced at both tool surfaces (HTTP server and file tool).

**Atomicity guarantee and its boundary.**

- Guaranteed: each durable epoch write is individually crash-atomic; the
  server's `max_epoch` never decreases, even across server restarts (rebuilt
  from `epochs.json` on startup).
- NOT guaranteed: the read-increment-write of `epoch.json` is not atomic
  across two concurrent recovery processes. Both could read N and both write
  N+1; the server's max-monotonicity makes the second fence a harmless no-op,
  but the two generations would then share epoch N+1, so neither fences the
  other. The implementation relies on the **crash-stop + single-recovery-writer**
  assumption: the watchdog launches exactly one recover process per crash, and
  the crashed generation is dead (SIGKILL), so no two writers are ever live
  concurrently (stated in `file_tool.py`'s module docstring).
- Specified fix (spec change, no code change yet): epoch acquisition MUST be a
  single atomic compare-and-swap against the tool server — the durable arbiter
  — returning the assigned epoch; `epoch.json` is then a local cache of the
  CAS result, not the source of truth. Until then the paper must state the
  single-recovery-writer assumption explicitly.

### A.2 Duplicate-call result return (checklist 3.2)

**What the code does.** On an already-seen key the tool server returns
`200 {"status": "duplicate_suppressed", "key": key}` — status only, no result
payload (tool_server.py `call()`). The file tool returns the identical shape
(file_tool.py `append()`). The harness (`_do_tool`) propagates only
`res["status"]`; downstream graph nodes never consume tool outputs
(`branch_results` carries effect counts, not values), and `w_execute_node`
treats `duplicate_suppressed` as success for routing purposes.

**Gap (honest).** The protocol's receiver contract currently specifies
status-only idempotency responses. A deployment whose downstream nodes need
tool outputs has no specified way to obtain the original result on a
duplicate. Specified fix: the tool ledger stores the result alongside the
commit record; `duplicate_suppressed` responses include the stored result;
the harness caches results keyed by claim key so replays after reconciliation
also hit the cache. Until implemented, the paper must say the contract
returns status only and that result-return is specified future work — it must
NOT claim "original results are returned."

### A.3 Partially written JSONL records (checklist 3.3)

**What the code does.**

- `ClaimLog._append` opens the file in unbuffered append mode, performs a
  single `write()` of the complete line, then `os.fsync`, then closes — one
  record is durable the moment `_append` returns.
- `ClaimLog.load()` implements the standard WAL torn-tail discipline: a line
  that fails JSON parsing is skipped if it is the *last* line (the crashed
  writer died mid-record); a parse failure on any *non-trailing* line raises
  loudly (corruption, not a torn write).
- The tool server's `_rebuild` skips undecodable ledger lines; the file
  tool's `ledger()` drops lines that fail its field-count parse (ground-truth
  scoring only, not protocol state).

**Why it is safe.** If a `Commit` record is torn and skipped, the claim
appears uncommitted; recovery replays it with the *original* key and the
idempotent receiver suppresses the re-commit — exactly-once is preserved, at
the cost of one wasted replay. If a `Claim` record is torn and skipped, the
effect was never invoked (write-ahead discipline: claim precedes the tool
call), so nothing is lost; the post-recovery agent re-claims it normally.

**Gaps (honest).**

1. The torn-tail skip is silent — no counter or log line records that a torn
   record was discarded. Specified fix: recovery reports a torn-record count
   in the run stats.
2. POSIX permits a partial `write()` even on regular files (vanishingly rare
   for small writes to a local filesystem); the torn-tail handler is the
   backstop, and it is the *only* backstop — there is no checksum per record.
   The paper must not claim stronger durability than fsync + torn-tail skip.

### A.4 Parallel execution (checklist 3.4)

**What the code does.**

- *Fan-out/fan-in.* `dispatch_router` Sends one packet per unsettled branch
  into the compiled worker subgraph; completions merge through the
  `branch_results` reducer (`Annotated[list, operator.add]`).
  `worker_sub_node` returns ONLY the fan-in key — the comment in the code
  states why: returning the subgraph's full state would concurrently write
  every shared key from N parallel branches (`InvalidUpdateError`).
- *Checkpoint frontier.* Branch settlement is one atomic file per branch in
  `branch_done/` (deliberately not a single read-modify-write JSON file —
  the comment cites the Send fan-out race). The frontier is the *set* of
  settled branch keys; gaps are legal because `dispatch_node` skips by set
  membership, not by contiguous index.
- *Log-fenced recomputation.* On recovery, `recover_node` rebuilds the
  frontier from the log: a branch counts as settled only when **all** of its
  effects' claims are committed (`claim_uid` ∈ committed set). The escalation
  effect counts as settled iff uid `"esc"` is committed. Partial fan-out
  (some branches done, others not; commit written but branch not yet marked
  done — the mid-fan-out crash window) is therefore handled: only fully
  committed branches are skipped, the rest re-dispatch.
- *Dependencies.* Rounds are sequential (`aggregate` → `supervisor` → next
  round); recovery restarts at round 0 and relies on the skip. There are no
  cross-branch data dependencies in the harness beyond the round barrier.

**Gap — concurrent equivalent claims (honest).** `w_claim_node`'s
`find_by_identity` check-then-append has no mutual exclusion: two concurrent
workers claiming the same `(action, target)` could both miss and append
distinct keys, and the tool server dedups by *key*, not identity — a semantic
duplicate. In the harness this cannot arise (workers own disjoint
branch/effect sets), but the protocol as specified does not prevent it.
Specified fix: a unique identity constraint on the claim log (claim CAS on
`(action, target)`) or identity-aware dedup at the receiver. The paper must
scope the exactly-once claim to disjoint effect ownership until this is
closed.

---

## Part B — Manuscript replacements (apply at merge time)

### B.1 — Principals paragraph (fencing contract)

OLD (main.tex ~§"Principals"):
> an \emph{atomic idempotent receiver}: $T.\mathrm{call}(k, e,
> \mathit{args})$ atomically checks whether key $k$ was seen and
> commits the effect iff not; it keeps a durable per-workflow key
> set and a per-workflow fencing epoch $\mathit{max\_epoch}$,
> rejecting calls with $e < \mathit{max\_epoch}$.

NEW:
> an \emph{atomic idempotent receiver}: $T.\mathrm{call}(k, e,
> \mathit{args})$ atomically checks whether key $k$ was seen and
> commits the effect iff not, returning \textsc{committed} or
> \textsc{duplicate\_suppressed} (status only; the original result
> payload is not returned — §\ref{sec:limits}). It keeps a durable
> per-workflow key set and a per-workflow fencing epoch
> $\mathit{max\_epoch}$, rejecting calls with $e <
> \mathit{max\_epoch}$. Fence acquisition is
> $\mathit{max}$-monotonic at $T$: the durable arbiter of the
> current epoch is $T$, not the harness's local epoch file.

### B.2 — Algorithm 1 (recovery)

OLD:
> \STATE $\mathit{epoch} \gets \mathit{epoch} + 1$; register with
> $T$ \COMMENT{fence acquisition}

NEW:
> \STATE $\mathit{epoch} \gets \mathrm{CAS}_{T}(\mathit{epoch}+1)$
> \COMMENT{atomic fence acquisition at $T$; single-recovery-writer
> assumed in our implementation (\S\ref{sec:design})}

(Body unchanged; add after the algorithm: "A torn trailing record in $L$ is
skipped on load (standard WAL tail discipline); a torn non-trailing record is
treated as corruption. A torn \textsc{Commit} is safe: the claim replays with
its original key and $T$ suppresses it.")

### B.3 — Zombie-writer paragraph

OLD:
> Second, the fencing epoch closes the \emph{zombie writer} hole: a pre-crash in-flight call
> arriving after recovery bears a stale epoch and is rejected, so
> no phantom commit can slip in after reconciliation.

NEW:
> Second, the fencing epoch closes the \emph{zombie writer} hole: a pre-crash in-flight call
> arriving after recovery bears a stale epoch and is rejected, so
> no phantom commit can slip in after reconciliation. This holds under the
> crash-stop fault model with a single recovery writer per crash: epoch
> acquisition is read-increment-write on the harness side and atomic only
> via $T$'s $\mathit{max}$-monotonic fence; two concurrent recoveries could
> share an epoch (see \S\ref{sec:limits}).

### B.4 — New paragraph: parallel execution and the completion frontier

INSERT after the semantic-skip paragraph ("The semantic skip in step~4
handles the LLM re-synthesis problem..."):

> \emph{Parallel execution.} Fan-out uses one durable file per settled branch
> rather than a single checkpoint record, so concurrent workers never race on
> a read-modify-write checkpoint; the completion frontier is the \emph{set} of
> settled branches and tolerates gaps. Recovery recomputes the frontier from
> $L$ under the log-fenced rule: a branch is settled only if \emph{every} one
> of its effects has a matching \textsc{Commit}. The protocol currently
> assumes disjoint effect ownership across parallel workers: two workers
> concurrently claiming the same $(\mathit{action}, \mathit{target})$ are not
> serialized by the log, and the receiver dedups by key, not by identity
> (see \S\ref{sec:limits}).

---

## Part C — Gap register (for §"Limitations" / Phase-2 theory handoff)

| # | Gap | Status |
|---|-----|--------|
| G1 | Epoch read-increment-write not atomic across concurrent recoveries | Spec fix written (CAS at $T$); code unchanged; assumption must be stated |
| G2 | Duplicate responses carry status only, not original results | Spec fix written (result-carrying suppressions + harness cache); not implemented |
| G3 | Torn-tail skips are silent (no counter) | Spec fix: recovery-time torn-record count |
| G4 | Concurrent equivalent claims not serialized (identity has no uniqueness constraint) | Spec fix: claim CAS on identity or identity-aware receiver dedup; paper must scope to disjoint ownership |
| G5 | Per-record checksums absent (torn-tail parse is the only backstop) | Document; do not overclaim durability |

Net for the paper: the implemented protocol is exactly-once under
crash-stop + single recovery writer + disjoint parallel effect ownership +
status-only idempotency. Each assumption is now named with its code location
and its specified fix.
