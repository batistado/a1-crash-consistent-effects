# LangGraph Production Port — Design

## Goal

Prove the crash-consistent checkpointing protocol works inside a real agent framework (LangGraph), with real side effects and real crashes. This answers the strongest anticipated TPDS reviewer objection: "your harness is synthetic."

## Architecture

**Agent**: a LangGraph `StateGraph` with nodes:
- `planner` — LLM produces the next plan step (a *claim*: what effect to cause).
- `claim_logger` — write-ahead: appends the claim to a durable JSONL log with `fsync` BEFORE the tool executes. Fields: `claim_id` (durable, derived from the original plan step — never re-derived after recovery), `tool`, `args_hash`, `epoch`, timestamp.
- `tool_executor` — executes the tool; the wrapper checks the epoch fence.
- `checkpointer` — LangGraph checkpoint of agent state (separate from the claim log).
- `recovery` — on restart: reads the claim log, reconciles. Claims marked committed-but-uncheckpointed are treated as DONE (never re-executed); uncommitted claims are re-emitted to the planner.

**Epoch fencing**: every run gets an epoch written to the log. On recovery the epoch increments. The tool wrapper and the test server reject any claim carrying a stale epoch — this is what stops a crashed run's in-flight retries from double-applying after recovery.

## Tools (all non-idempotent — duplicates must be observable and harmful)

1. `file_append` — appends a line to a scratch file. A duplicate = a duplicate line.
2. `http_post` — POSTs to a local test server (Flask/FastAPI) that logs every request with its idempotency key and epoch. A duplicate = a double-logged request.
3. `mailbox_send` — appends to a mailbox file (simulates sending a message). A duplicate = a double send.

Non-idempotency is deliberate: with idempotent tools exactly-once is trivial and reviewers will say so.

## Crash injection

Real `SIGKILL` to the agent process at randomized, seeded points:
- pre-claim (sanity: nothing should be lost or duplicated)
- post-claim, pre-tool-call
- **post-tool-call, pre-checkpoint** — the critical window: effect committed, checkpoint not saved. This is the fault class the paper formalizes.
- post-checkpoint (sanity)

Seeded schedule for reproducibility; the seed is recorded in the report.

## Test cases

1. **Crash-point matrix**: N=50 episodes per crash point × (protocol vs baseline). Primary metric: duplicate-effect rate.
2. **Baseline arm**: identical agent using LangGraph's native checkpointing with naive retry (no claim log, no fencing). Expected: substantial duplicates in the critical window — this is the "what happens without us" control.
3. **In-framework ablations**: protocol minus fencing; protocol minus claim log. Mirrors the scripted ablations; shows each piece matters inside the real framework too.
4. **Re-synthesis stress**: planner runs at temperature 0.7 after a crash so the re-plan rewords/restructures steps. Tests the keys-alone-insufficiency theorem *in vivo*: re-derived keys fail, durable original claims hold.
5. **Fencing test**: replay a claim carrying a stale epoch against the test server — must be rejected 100% of the time.
6. **Overhead**: p50/p99 added latency per tool call from the fsync'd claim-log writes; bytes per claim on disk.

## Metrics

- Duplicate-effect rate (primary), exactly-once rate, missing-effect rate, claim adherence, recovery time, added latency p50/p99.

## Reviewer objections → design answers

| Objection | Answer in this design |
|---|---|
| "Toy/synthetic harness" | Real LangGraph StateGraph, real tools, real SIGKILL |
| "This is just WAL applied to agents" | Formal model + ablations: the contribution is the combination (durable original claims + log-fenced checkpoints + semantic effect identity + epoch fencing); baseline with naive retry still duplicates |
| "Idempotent tools make exactly-once trivial" | All three tools are non-idempotent by design |
| "Simulated crashes aren't convincing" | Real process kills on a seeded schedule, not flags |
| "Only one model" | Covered by the separate second-model validation; the protocol itself is model-agnostic |
| "No cost analysis" | Overhead test case measures latency + storage in the real setup |

## Deliverables

- `langgraph_port/`: `requirements.txt` (pinned), `README.md` (setup/run/repro), agent code, tool server, crash-injection harness, analysis script.
- `LANGGRAPH_PORT.md`: results, tables, and the reviewer-facing notes above.
- `RUNLOG.md` entry on completion.
