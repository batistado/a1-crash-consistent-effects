# ClaimFence: Crash-Consistent Distributed Agent Workflows

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Dataset](https://img.shields.io/badge/HuggingFace-Dataset-yellow)](https://huggingface.co/datasets/batistado/a1-crash-recovery-results)

**ClaimFence** is a crash-consistent execution middleware for distributed cloud and LLM agent workflows that invoke stateful external tools and microservices.

Existing agent orchestration frameworks (`LangGraph`, `CrewAI`, `AutoGen`, cloud agent SDKs) checkpoint *conversation trajectories* at superstep boundaries rather than *external effect commitments*. When a worker crashes inside the harness crash window $W(s) = (t_{\mathrm{commit}}(s), t_{\mathrm{ckpt}}(s))$—after an external service commits a mutation but before the checkpoint advances—restarted LLM planners paraphrase tool arguments (breaking content-hash keys), insert diagnostic steps that shift positional indices (breaking positional keys and post-call checkpoint ledgers), and lose volatile return tokens required by downstream workflow stages.

## Key Capabilities

1. **Concurrency-Safe $O(1)$ Write-Ahead Claim Stores (`claimfence/claim_store.py`):**
   - `IndexedJSONLClaimStore`: Append-only log with `O(1)` hash lookup (`2.17 µs` at `10,000` claims — `12,987x` faster than unindexed JSONL scanning), incremental cross-process tail refresh, ARIES-style torn-tail truncation, POSIX `fcntl.flock` serialization across concurrent workers, and optional physical NAND flush (`F_FULLFSYNC`).
   - `SQLiteWALClaimStore`: Transactional SQLite WAL backend (`PRAGMA journal_mode=WAL; synchronous=FULL`) with `0.37 ms` per-step write latency.
2. **Server-Enforced Atomic `CAS_inc` Epoch-Lease Fencing (`claimfence/receiver.py`):**
   - Atomically increments `(max_epoch[wid], holder)` at the service boundary, rejecting delayed zombie workers (`HTTP 409`) and serializing concurrent dual-recovery instances without client-side race windows.
3. **Payload-Preserving Reconciliation-First Recovery (`claimfence/reconciler.py`):**
   - Replays uncommitted pre-crash claims with their frozen keys *before* consulting the LLM planner and restores RIFL-complete return payloads (`receipt_token`) to downstream dependent workflow stages.
4. **Exhaustive Finite-State Model Checker (`benchmarks/model_check_protocol.py`):**
   - Explores 100% of reachable asynchronous crash, zombie, and dual-recovery interleavings (`149` states, `259` transitions), verifying zero safety, completion, or payload-loss violations.

## Repository Structure

- `claimfence/` — Core `ClaimFence` v2.0 Python package (`IndexedJSONLClaimStore`, `SQLiteWALClaimStore`, `AtomicIdempotentReceiver`, `ClaimFenceRuntime`).
- `benchmarks/` — Reproducible verification and benchmark suite:
  - `model_check_protocol.py` — Exhaustive BFS finite-state model checker across 5 protocol designs.
  - `run_chaos_6way.py` — `33,000`-episode paired 6-architecture chaos & multi-crash horizon ($k \in \{1..4\}$) suite.
  - `run_multimodel_sigkill.py` — Live Apple Silicon (`MPS` FP16) real OS `SIGKILL` evaluation across `Qwen2.5-3B-Instruct`, `Qwen2.5-7B-Instruct`, and `Qwen2.5-Coder-14B-Instruct`.
  - `run_storage_scaling.py` — Persistent NVMe write-path breakdown (`os.fsync`, `F_FULLFSYNC`, `SQLite-WAL`), lookup scaling ($N = 100..10{,}000$), and `K = 1..32` concurrent workflow load tests.
- `langgraph_port/` — Production `LangGraph` `StateGraph` (`v1` linear and `v2` conditional supervisor + parallel `Send` subgraphs + `E1–E5` boundary experiments).
- `src/` — Standalone sandbox and `OpenAI` (`gpt-4o-mini`, `gpt-4.1-mini`) recovery-prompt ablation drivers.
- `tests/` — `pytest` unit, crash-window, torn-tail, multi-worker contention, and dual-recovery test suite.
- `paper/` — Archival manuscript (`main.tex`, `main.pdf`), Elsevier FGCS `highlights.tex` / `highlights.pdf`, vector figures, and static validator.

## Quick Start

```bash
# Run unit & concurrency stress tests
pytest tests/test_claimfence.py -v

# Run exhaustive finite-state model checker
python3 benchmarks/model_check_protocol.py

# Run 6-architecture multi-crash chaos suite
python3 benchmarks/run_chaos_6way.py

# Run persistent NVMe storage & concurrency benchmarks
python3 benchmarks/run_storage_scaling.py

# Run real OS SIGKILL multi-model campaign on Apple Silicon (MPS) or CUDA
python3 benchmarks/run_multimodel_sigkill.py --episodes 20
```

## License

Apache License 2.0. See [LICENSE](LICENSE).
