# A1 LangGraph Production Port

Crash-consistent checkpointing for exactly-once agent effects, running on a **real LangGraph `StateGraph`** with **real tool side effects**, a **real fsync'd write-ahead claim log**, **real `SIGKILL` crash injection**, and **real epoch fencing** — no mocks in the crash path.

This is the production-faithfulness companion to the scripted sandbox (`../src/sandbox.py`) for the A1 TPDS paper push.

## Architecture

```
crash_harness.py  (episode driver: crash schedule, watchdog, scoring)
    |  spawns per episode
    +-- agent_run.py --mode fresh     (LangGraph StateGraph, own OS process)
    |       plan -> claim -> execute -> commit -> checkpoint (per step)
    |       tools: HTTP POST -> tool_server.py | file append -> scratch/
    |       ... watchdog delivers SIGKILL at the scheduled point ...
    +-- agent_run.py --mode recover   (NEW process, new epoch)
            recover -> plan -> claim -> execute -> commit -> checkpoint
              recover = fence epoch + reconcile uncommitted claims
                        with ORIGINAL keys + advance checkpoint (log-fenced)
```

**Durable state** (the only thing that survives the `SIGKILL`): `runs/<cond>/<workflow-id>/claim.log` (fsync'd JSONL), `checkpoint.json` (atomic), `epoch.json`, `plan.json`, `scratch/audit.log` (file-tool ledger); the tool server's `ledger.jsonl` + `epochs.json` in its own process/directory.

## Setup

```bash
cd langgraph_port
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # langgraph==1.2.14, requests==2.34.2, ...
```

## Run

```bash
# full experiment v1 (60 episodes x 3 conditions, ~15-20 min, $0)
.venv/bin/python crash_harness.py

# v2 "research-assistant" scenario (60 episodes x 3 conditions, ~35-45 min, $0)
.venv/bin/python crash_harness_v2.py

# quick smoke test
.venv/bin/python crash_harness.py --conditions wal --episodes 2 --out /tmp/smoke.json

# crash schedule lives in config.json (seeded RNG; edit episodes/conditions there)
```

`crash_harness.py` starts the tool server itself (default `127.0.0.1:8765`), runs every episode, then writes `results_langgraph.json`. `crash_harness_v2.py` is the same shape for the v2 scenario (tool server on `127.0.0.1:8766`, schedule in `config_v2.json`, results in `results_langgraph_v2.json`).

## v2 — "research-assistant" scenario

`DESIGN_V2.md` has the full rationale. In short: v1's loop is linear, and reviewers will ask whether the protocol survives a production-shaped agent. v2 models one in the same directory without touching v1:

- **Supervisor** with `add_conditional_edges` routing (fan_out / escalate / done) — real branching.
- **`Send`-based fan-out** to a **compiled worker subgraph** (3 parallel branches, fan-in via reducer) — real delegation.
- **Retry loop with a real backoff sleep** on scripted transient tool failure — real retry behavior.
- **New crash windows**: mid-fan-out (partial completion — some workers committed, others not), post-branch-decision, during retry backoff.

New files: `common_v2.py` (scenario), `agent_graph_v2.py` (graph), `agent_run_v2.py` (runner), `crash_harness_v2.py` (driver), `config_v2.json` (seed 20261011). Results: `LANGGRAPH_PORT_V2.md`. Shared unchanged: `tool_server.py`, `file_tool.py`, `claim_log.py`, `common.py` scoring.

## What each file is

| File | Role |
|---|---|
| `config.json` | Crash schedule config: seed, episodes, 75/15/10 landing weights, reword/shift probabilities, timeouts |
| `common.py` | Plan generator, claim identity, deterministic keys, semantic scoring (mirrors `sandbox.py`) |
| `claim_log.py` | Durable append-only JSONL claim log, fsync per CLAIM/COMMIT (record shape matches `measure_overhead.py`) |
| `checkpoint_store.py` | Atomic checkpoint file (temp+fsync+rename) |
| `file_tool.py` | Real file-write tool: idempotent check-and-append + epoch fencing on the scratch dir |
| `tool_server.py` | Local HTTP tool server (separate process): atomic check-and-commit, per-workflow seen-keys, fencing epochs, durable ledger |
| `agent_graph.py` | The LangGraph `StateGraph`: plan/claim/execute/commit/checkpoint + recover nodes |
| `agent_run.py` | Subprocess entry point (`--mode fresh` / `--mode recover`) |
| `crash_harness.py` | Episode driver: deterministic crash schedule, watchdog `SIGKILL`, zombie probes, ledger scoring |

## Reproducing

The crash schedule is fully seeded (`config.json: seed=20261010`; per-episode RNG = `seed + ep*7919 + cond_offset*104729`). Given the same code, config, and seed, episode `i` of each condition draws the same plan seed, crash step, and landing. Results land in `results_langgraph.json` (per-episode rows included).

## Design notes

- The planner is scripted/deterministic — the fault under study is harness-side crash consistency, not agent cognition (documented in `../LANGGRAPH_PORT.md`, "what's real vs simulated").
- LangGraph's own checkpointer is deliberately **not** used: it checkpoints trajectory state, which is exactly the structure the paper shows is insufficient. Durability comes from the claim log + checkpoint file.
- Progress markers in `progress.log` are chaos-instrumentation (like observing a log line before `kill -9`); the agent never sees the crash plan.
