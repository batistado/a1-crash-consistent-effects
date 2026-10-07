# LangGraph Production Port v2 — "Research Assistant" Scenario

Companion to the v1 linear-loop port (`agent_graph.py`, `LANGGRAPH_PORT.md`). v1 proved the protocol on plan → claim → execute → commit → checkpoint. v2 answers the follow-up question: whether it survives a production-shaped agent — branching, parallel fan-out, delegation, retries — or only a toy loop.

## The scenario

A two-round evidence-gathering agent:

- **Round 0** — the supervisor fans out over 3 source branches. Each worker records a finding (HTTP POST to the tool server, non-idempotent) and logs the source (file append, non-idempotent).
- **Round 1** — the supervisor *decides*: fan out again (p=0.6) or **escalate** (p=0.4: a single alert effect on a different branch).
- Then finalize.

All supervisor/planner decisions are scripted from the episode seed. Honest scoping: the fault under study is **harness-side crash consistency** (branch/fan-out/retry crash windows), not agent cognition — an LLM planner would add $cost and nondeterminism without changing the fault class.

## Graph features (all genuine LangGraph)

| Feature | Where | Reviewer objection it answers |
|---|---|---|
| `add_conditional_edges` supervisor routing (fan_out / escalate / done) | `supervisor_node` | "Real agents branch; a crash between the branch decision and the tool call is a distinct window" → the new `post_branch` crash point |
| `Send`-based parallel fan-out to a **compiled worker subgraph**, fan-in via reducer | `dispatch_router`, `worker_sub` | "Real agents fan out / delegate; effects commit concurrently" → the new `mid_fanout` partial-completion case |
| Framework-level retry loop with a **real backoff sleep** (`w_retry`) | worker subgraph | "Real agents retry transient failures; crashing mid-backoff must not lose or duplicate the effect" → the new `retry_backoff` crash point |
| Per-(round, branch, effect) durable claims, epoch fencing, log-fenced branch-state | `ClaimLog`, `recover_node` | "Does the WAL machinery compose with branching, or does branch identity break recovery?" |

## New crash windows (seeded, external watchdog, real SIGKILL)

1. **mid_fanout** (p=0.5): kill on the first `WORKER r0 … COMMIT` marker. Some workers committed, others still in flight — partial fan-out completion, the scatter-gather case distributed systems reviewers know. Baseline recovery re-dispatches the unsettled branch → duplicate; wal skips via the committed claim.
2. **post_branch** (p=0.25): kill right after the supervisor's `BRANCH` marker for round 1, before any tool call of that round. Decision made, nothing committed — a liveness/recovery-correctness check (no duplicates expected in any condition; missing effects would be the failure).
3. **retry_backoff** (p=0.25): kill while a worker sleeps in `RETRY_WAIT` (scripted transient failure on branch 0's first attempt, real 1s backoff). Claim exists but uncommitted → wal reconciles it; baseline re-dispatches.

## Conditions

- **wal**: full protocol (per-branch claims, fencing, log-fenced branch-state).
- **baseline**: no claim log, no keys, no fencing (naive retry).
- **deterministic**: keys re-derived at call time. In v2, branch identities are *stable* across recovery (unlike v1's plan-shift), so deterministic keys are expected to hold here — an informative contrast that sharpens the paper's claim: keys fail exactly when post-recovery recomputation re-derives different identities.

## What v2 deliberately does NOT test

- LLM-driven planning/cognition (scripted; fault class is harness-side).
- Cross-process worker concurrency races (workers are threads in one process; the crash-stop model holds — recovery starts only after SIGKILL).
- Multi-crash episodes (one crash per episode, same as v1 and the sandbox).

## Deliverables

- `agent_graph_v2.py`, `agent_run_v2.py`, `crash_harness_v2.py`, `common_v2.py`, `config_v2.json` (seed 20261011, tool server on :8766).
- `results_langgraph_v2.json` / `.jsonl` (incremental, crash-safe).
- `LANGGRAPH_PORT_V2.md` — results and honest caveats.
- `RUNLOG.md` entry.
