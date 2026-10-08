# A1 Phase 4 — Experiment Designs (2026-10-07)

Reviewer: research reviewer LLM, private pre-submission assessment.
Target: IEEE TPDS. These four experiments close Major Concerns #3 (strong
baselines) and #4 (fencing causal mechanism), and supply the boundary
characterization the reviewer flagged as the paper's potential central insight.

All experiments use the existing v2 LangGraph harness
(`langgraph_port/crash_harness_v2.py`, real SIGKILL, external watchdog) or the
stdlib sandbox (`src/component_ablation.py`), unless noted. Crash fault model
is unchanged: SIGKILL of our own harness processes only.

---

## E1 — Native-persistence baseline

**Reviewer ask** (§3): "Add a baseline using native persistence, documented
task boundaries, durable operation identities, and the same receiver contract.
Compare it with your protocol under matched crash schedules and recovery
policies."

**Design.**
New condition `native` in the v2 harness:
- Graph compiled with LangGraph's own `SqliteSaver` checkpointer
  (`langgraph-checkpoint-sqlite`), file-backed so checkpoints survive the
  SIGKILL. This is literally "native persistence" — state persisted at node
  boundaries by the framework, not by our WAL.
- Tool calls use deterministic positional keys
  (`claim_key_v2`: `det:{wid}:r{round}:b{branch}:e{idx}:{action}`) — the
  "durable operation identities." Same receiver contract (tool_server.py:
  idempotent by key, epoch fencing — though native does no fencing).
- NO claim log. NO manual recover_node. Recovery = new process, same
  `thread_id`, `graph.invoke(None, config)` — LangGraph resumes from the
  last checkpointed node and re-executes.
- Task boundaries are the graph's node boundaries (documented: plan,
  supervisor, dispatch, worker_sub [claim/execute/commit per effect],
  aggregate, escalate chain, finalize).
- Matched crash schedules: same three windows (mid_fanout 0.5,
  post_branch 0.25, retry_backoff 0.25), same seeds, same episode count
  (60/condition).

**Honest expectation.** In the stable-identity v2 setting, `native` should
match `wal` on duplicates (0.0000): when recovery re-executes an interrupted
node, it re-derives the SAME deterministic key, and the idempotent receiver
suppresses the re-commit. This is not a failure of the experiment — it is the
boundary result: native persistence + stable identities suffices; the WAL's
value appears only when identities shift (E2). We report this plainly.

**Metrics.** duplicate rate, exactly-once rate, missing-effect rate, recovery
success, per-condition, plus by-crash-type breakdown. Compare against wal /
baseline / deterministic from the existing v2 results.

**Implementation.** `langgraph_port/agent_graph_v2_native.py` (graph variant
compiled with SqliteSaver; fresh vs resume entry points),
`langgraph_port/agent_run_v2_native.py` (subprocess entry), harness
`--conditions native` support. If subgraph resume proves problematic, fall
back to a documented manual equivalent (persist state dict per node via
SqliteSaver API) — the semantics (node-boundary state persistence) are what
matter.

**PASS criterion.** Experiment runs cleanly (60 episodes, crash injection
verified); results reported honestly whatever they are. The paper's claim is
updated to the boundary characterization.

---

## E2 — Identity shift across recovery (the critical experiment)

**Reviewer ask** (§3): "Include a case where identities change across
recovery and show precisely what the stronger baseline cannot preserve."

**Design.** Two shift mechanisms, each a new condition; `wal` unchanged as
control; `baseline` as reference. 60 episodes/condition, same crash windows.

### E2a — positional shift (primary)
Recovery replanning permutes branch indices (seeded by `recover_seed`).
Rationale (realistic, not a strawman): after a crash, the supervisor
replans and reprioritizes remaining work; positional indices are not
preserved across replanning — this is the normal LLM-replanning behavior,
and v1's own `p_plan_shift` models the same phenomenon for step indices.

Mechanics:
- Fresh generation: branches 0..k-1, deterministic keys from positions.
- Crash (mid_fanout: branch b committed effect, but branch-done marker not
  yet written — the exact window where v2 deterministic currently holds).
- Recovery: supervisor takes the unsettled original branches, orders them
  by a seeded permutation (the "replan"), assigns NEW positional indices
  0..m-1 in that order. The re-dispatched worker for original branch b now
  derives key `det:{wid}:r{r}:b{i}:e:{idx}:{action}` with i ≠ b.
- Tool sees an unseen key → commits → semantic duplicate of (action,
  target). Ground-truth scoring is unchanged (targets are identical strings;
  only key-derivation inputs shifted).
- `wal`: `find_by_identity(action, target)` matches the original claim,
  reuses the ORIGINAL key → `duplicate_suppressed`. No duplicate.

Expected: `det_shift` duplicates > 0 (estimate 0.3–0.6 of mid_fanout
episodes, where the committed-but-unmarked branch gets a new index);
`wal` 0 duplicates. This is the boundary: deterministic keys fail exactly
when post-recovery recomputation re-derives different identities.

### E2b — content shift (secondary; replicates the sandbox finding in v2)
New condition `det_content`: keys are content-hashes
`sha256(action + "|" + target)` (like sandbox's `content_hash_key`).
Recovery rewords targets via a fixed, invertible paraphrase map
(e.g. `finding-r0-b0` → `r0-b0-finding`; `source-r0-b0` → `src-r0-b0`),
modeling LLM rephrasing across replanning. The tool commits the reworded
target with an unseen hash → duplicate. Scoring normalizes through the
inverse map (`canonical_target()`). The `wal` condition canonicalizes on
claim lookup, reusing the original key.

Expected: `det_content` duplicates > 0; `wal` 0.

**Why not LLM rewording.** Scripted paraphrase is deterministic, $0, and
matches the sandbox's validated `reword_args` approach. The question is
whether key identity survives rewording, not whether an LLM can paraphrase.

**PASS criterion.** `wal` holds 0 duplicates while at least one
deterministic variant breaks (>0 duplicates) under the SAME crash windows.
The paper's central insight becomes the boundary characterization.

---

## E3 — Scale measurements

**Reviewer ask** (§3): "For TPDS, also measure a modest range of fan-out
sizes, concurrent workflows, and recovery-log lengths."

### E3a — fan-out sizes
N_BRANCHES ∈ {2, 4, 8}, `wal` condition, 30 episodes each (scripted,
$0). Metrics: duplicate rate (expect 0), per-episode wall time, claim-log
write latency p50/p99, recovery time. Question: does the protocol hold and
does overhead stay flat as fan-out grows?

### E3b — recovery-log length
Microbenchmark ($0): append N claims to a `ClaimLog` (N ∈ {100, 1k, 10k}),
measure append latency p50/p99/max and `find_by_identity` latency vs N.
Rationale: `find_by_identity` and `claims()` scan the log linearly — this
quantifies the O(n) lookup cost the reviewer would ask about. If it
degrades, we report it honestly and note indexing as follow-up.

### E3c — concurrent workflows
Run K harness instances in parallel (K ∈ {1, 4, 16}) against one tool
server, `wal` condition, 20 episodes each ($0). Metrics: wall-clock time,
per-episode latency p50/p99, server-side contention (fenced rejections,
ledger throughput). Question: does the shared tool server serialize
recovery?

**PASS criterion.** Measurements reported with the honest denominator;
the "~1% overhead" claim is replaced by the measured scaling curves.

---

## E4 — Fencing trace analysis

**Reviewer ask** (§4): "Show an offending trace with the claim identity,
key, epoch, and receiver decision. Separate delayed same-key requests from
surviving writers that create fresh work."

**Background (from the data).** `component_ablation_results.json`:
`no_fencing` dup_rate=0.4927, mean_dup/ep=0.4927,
zombie_committed=739/1500=0.4927. The duplicate rate EQUALS the zombie-commit
rate — essentially all no-fencing duplicates are zombie commits. `full`:
zombie_fenced=749, dup=0.

**Mechanism (from the code).** The F2 writer-zombie (`component_ablation.py`)
survives the crash and retries with its OLD epoch and a FRESHLY DERIVED
content-hash key over (possibly reworded) args — "a key from a keyspace the
new generation never saw. The tool's idempotency check cannot suppress it
(unseen key); only the epoch fence can reject it." So the mechanism is (b)
surviving writers creating fresh keys — NOT (a) delayed same-key retries
(the zombie never reuses the original key, by construction modeling a stale
at-least-once agent).

**Deliverable.** Instrumented re-run of the `no_fencing` condition (200
episodes, stdlib, $0) logging every `tool.call` as
`(caller, workflow_id, step_uid, action, target, key, epoch, result)`.
For each duplicate episode, classify the offending call:
(a) same key as a prior commit (delayed same-key retry), or
(b) fresh key never seen before (surviving-writer fresh claim).
Produce ONE fully worked trace: the fresh call (key K1, epoch 0,
committed), the zombie call (key K2≠K1, epoch 0 stale, committed —
accepted because no fence), the receiver's decision at each step, and the
resulting semantic duplicate. Report the (a)/(b) split across all duplicate
episodes.

**Expected.** 100% type (b), 0% type (a) — confirming the paper's
characterization and answering the reviewer's causal question with a trace.

**PASS criterion.** Worked trace delivered; (a)/(b) split quantified; the
~49% is attributed to the demonstrated stale-writer mechanism, not a
generic retry.

---

## Cross-cutting

- Every run appends to `RUNLOG.md` (date, config, result, spend, verdict).
- API spend: $0 for E1/E3/E4 (scripted/local); E2 uses scripted rewording
  ($0). Total API $0. (The $5 cap is unused — reserved if LLM rewording
  validation is later deemed necessary.)
- No H4 re-runs. Crash injection is SIGKILL of our own harness processes.
- Results committed to `main` per experiment.
- Result files: `results_e1_native.json`, `results_e2_identity_shift.json`,
  `results_e3_scale.json`, `results_e4_fencing_trace.json` (+ per-episode
  JSONL), and `PHASE4_RESULTS.md` summary.
