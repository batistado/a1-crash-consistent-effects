# A1 Claim-Log Overhead Measurement

**Date:** 2026-10-07 · **Script:** `src/measure_overhead.py` (raw: `overhead_raw.json`)
**Cost:** $0 (no API calls) · **Env:** VM disk, btrfs (`/dev/mapper/rv`)

## Method

~200 synthetic episodes × 4 steps. Per step, the durable path performs three
durable writes, each followed by `fsync`:

1. **CLAIM** — append the write-ahead claim record (must be durable *before*
   the tool call; this ordering is the protocol, not a tuning choice).
2. **COMMIT** — append the commit record after the tool call.
3. **CHECKPOINT** — write the checkpoint file (last fully-recorded step).

Record shape reuses the harness's WAL entry
(`uid, action, target, note, key, epoch, committed`). Baseline for comparison:
the in-memory list-append log used in the scripted sandbox / LLM validation.

## Results

| Operation (per step) | mean | p50 | p99 |
|---|---|---|---|
| CLAIM append + fsync | 19.1 ms | 17.3 ms | 42.8 ms |
| COMMIT append + fsync | 19.3 ms | 17.2 ms | 53.1 ms |
| Checkpoint write + fsync | 13.3 ms | 11.9 ms | 38.8 ms |
| **Per-step total (durable)** | **51.7 ms** | **51.8 ms** | **103.5 ms** |
| Per-step (in-memory, no fsync) | 0.0017 ms | — | 0.011 ms |

| Bytes | per op (mean) |
|---|---|
| CLAIM record | 180 B |
| COMMIT record | 179 B |
| Checkpoint file | 17 B |
| **Per-step total** | **~376 B** |

## What this implies for the paper's cost-of-safety claim

The durability tax is ~52 ms and ~376 bytes per effectful step. Two points
for the TPDS framing:

1. **Negligible against the dominant cost.** A single LLM-driven agent step
   in our validation took ~4–8 s wall-clock (model inference + tool round
   trip). The claim log adds roughly **1% latency overhead** per step — the
   safety guarantee is essentially free at agentic timescales. A reviewer
   asking "what does the log cost?" gets a measured answer, not a
   hand-wave.
2. **Headroom for optimization, honestly noted.** This is the naive
   discipline (3 fsyncs/step). COMMIT and the checkpoint advance can be
   folded into a single fsync (~2 fsyncs/step, ≈38 ms), and group commit
   across workflows would amortize further. We report the unoptimized
   number as the conservative bound.

Caveats: measured on one VM (btrfs, virtualized disk); fsync latency is
environment-sensitive — ext4/NVMe will differ, almost surely downward.
The in-memory baseline is included only to show durability, not Python,
dominates the cost.
