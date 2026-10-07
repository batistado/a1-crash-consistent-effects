# LangGraph Production Port v2 — "Research Assistant" Scenario

Companion to the v1 linear-loop port (`agent_graph.py`, `LANGGRAPH_PORT.md`). v1 proved the protocol on plan → claim → execute → commit → checkpoint. v2 answers the follow-up question: whether it survives a production-shaped agent — branching, parallel fan-out, delegation, retries — or only a toy loop.

## The scenario

A two-round evidence-gathering agent:

- **Round 0** — the supervisor fans out over 3 source branches. Each worker records a finding (HTTP POST to the tool server, non-idempotent) and logs the source (file append, non-idempotent).
- **Round 1** — the supervisor *decides*: fan out again (p=0.6) or **escalate** (p=0.4: a single alert effect on a different branch).
- Then finalize.

All supervisor/planner decisions are scripted from the episode seed in the
base variant. Honest scoping: the fault under study is **harness-side crash
consistency** (branch/fan-out/retry crash windows), not agent cognition — a
deterministic planner is the right cost/validity trade (no API spend, fully
reproducible). A real-LLM planner variant exists (see "Planner variants"
below) that re-runs the identical experiment with round-1 routing decided by
gpt-4o-mini — including a mixed-distribution campaign (temperature 1.0) whose
genuine 135-escalate / 79-fan_out split is the primary reported supervisor
result.

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

- Cross-process worker concurrency races (workers are threads in one process; the crash-stop model holds — recovery starts only after SIGKILL).
- Multi-crash episodes (one crash per episode, same as v1 and the sandbox).

## Planner variants

- **scripted** (default, `$0`): round-1 route drawn from the episode seed
  (`P_ROUND1_FANOUT = 0.6`). Fully reproducible; the fault class is
  harness-side, so this is the primary variant.
- **llm** (`--planner llm`, gpt-4o-mini): the round-1 routing decision is a
  real model judgment call. Constraints: the model plans *routes only* and
  **never sees the raw claim log**; in the recovery generation it is consulted
  *after* deterministic reconciliation (`recover_node`) with the reconciled
  branch state as its context. Round 0 stays structural (always fan_out) in
  both variants. Decisions are persisted per episode (`decisions.jsonl` +
  `scenario.json`), and ground-truth scoring is built from the actual
  decisions, not the scripted generator. On persistent API failure the
  planner falls back to `fan_out` (logged). Campaign hard stop: $5 OpenAI
  API.
  - 2026-10-07 temp-0 run (180 eps): $0.0069, 214 judgments, 0 fallbacks —
    but the model chose fan_out in all 180 episodes (degenerate prompt: it
    showed identical evidence every episode, so fan_out was the only rational
    answer).
  - 2026-10-07 temp-1.0 mixed campaign (180 eps, same seed 20261011):
    prompt fixed with seeded per-episode evidence profiles
    (`evidence_summary`, deterministic in plan_seed so fresh/recover judge
    identical evidence) plus a cost-aware decision rule (fan_out costs 6 more
    effects + delays resolution). Result: genuine 135 escalate / 79 fan_out
    split, 0 fallbacks; wal 0.0000 duplicates / 1.0000 exactly-once, baseline
    0.80 duplicates, deterministic 0.0000 — $0.0117. This is the primary
    reported supervisor result: the protocol holds under a genuine mixed
    route distribution, not just a uniform one.

## Deliverables

- `agent_graph_v2.py`, `agent_run_v2.py`, `crash_harness_v2.py`, `common_v2.py`, `config_v2.json` (seed 20261011, tool server on :8766).
- `results_langgraph_v2.json` / `.jsonl` (incremental, crash-safe).
- `LANGGRAPH_PORT_V2.md` — results and honest caveats.
- `RUNLOG.md` entry.
