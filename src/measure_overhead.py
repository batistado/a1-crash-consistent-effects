#!/usr/bin/env python3
"""A1 claim-log overhead measurement (OVERHEAD.md).

Compares a durable filesystem-backed append-only claim log (fsync per
CLAIM/COMMIT record + fsync'd checkpoint write per step) against the
in-memory log used in the scripted sandbox / LLM validation.

Reuses the WAL record shape from src/llm_validation.py:
  CLAIM: {"uid", "action", "target", "note", "key", "epoch", "committed": False}
  COMMIT: flip "committed" -> True (appended as a second record here,
          matching an append-only log discipline)
  CHECKPOINT: small file holding the last fully-recorded step index.

~200 synthetic episodes x 4 steps, timed with perf_counter_ns.
Stdlib only. No API calls.
"""
import json
import os
import shutil
import statistics
import sys
import tempfile
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N_EPISODES = 200
STEPS_PER_EPISODE = 4


def make_record(uid, action, target, committed):
    return {
        "uid": uid,
        "action": action,
        "target": target,
        "note": f"synthetic note for {action} on {target}",
        "key": f"wf-bench:{uid:04d}:{action}:deadbeef",
        "epoch": 1,
        "committed": committed,
    }


def bench_durable(root, n_episodes, steps):
    """Append-only JSONL log + checkpoint file, fsync on every write."""
    log_path = os.path.join(root, "claim.log")
    ckpt_path = os.path.join(root, "checkpoint.json")
    lat = {"claim": [], "commit": [], "checkpoint": []}
    nbytes = {"claim": [], "commit": [], "checkpoint": []}
    logf = open(log_path, "ab", buffering=0)
    try:
        for _ in range(n_episodes):
            for uid in range(steps):
                rec = make_record(uid, "update_record", f"rec-{uid:03d}", False)
                line = (json.dumps(rec, separators=(",", ":")) + "\n").encode()
                t0 = time.perf_counter_ns()
                logf.write(line)
                os.fsync(logf.fileno())
                lat["claim"].append((time.perf_counter_ns() - t0) / 1e6)
                nbytes["claim"].append(len(line))

                crec = dict(rec, committed=True)
                cline = (json.dumps(crec, separators=(",", ":")) + "\n").encode()
                t0 = time.perf_counter_ns()
                logf.write(cline)
                os.fsync(logf.fileno())
                lat["commit"].append((time.perf_counter_ns() - t0) / 1e6)
                nbytes["commit"].append(len(cline))

                cbytes = json.dumps({"checkpoint": uid}).encode()
                t0 = time.perf_counter_ns()
                # atomic-ish: write temp + rename + fsync dir would be the
                # production discipline; here we measure the plain write+fsync
                with open(ckpt_path, "wb") as cf:
                    cf.write(cbytes)
                    cf.flush()
                    os.fsync(cf.fileno())
                lat["checkpoint"].append((time.perf_counter_ns() - t0) / 1e6)
                nbytes["checkpoint"].append(len(cbytes))
    finally:
        logf.close()
    return lat, nbytes


def bench_memory(n_episodes, steps):
    """In-memory log: list appends, no durability (baseline harness)."""
    wal = []
    checkpoint = -1
    lat = []
    for _ in range(n_episodes):
        for uid in range(steps):
            t0 = time.perf_counter_ns()
            wal.append(make_record(uid, "update_record", f"rec-{uid:03d}", False))
            wal[-1]["committed"] = True
            checkpoint = uid
            lat.append((time.perf_counter_ns() - t0) / 1e6)
    return lat


def pct(v, p):
    s = sorted(v)
    return s[min(len(s) - 1, int(p / 100 * len(s)))]


def main():
    workdir = tempfile.mkdtemp(prefix="a1-overhead-", dir=PROJECT)
    try:
        lat, nbytes = bench_durable(workdir, N_EPISODES, STEPS_PER_EPISODE)
        mem = bench_memory(N_EPISODES, STEPS_PER_EPISODE)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    n_steps = N_EPISODES * STEPS_PER_EPISODE
    per_step = [c + m + k for c, m, k in
                zip(lat["claim"], lat["commit"], lat["checkpoint"])]
    out = {
        "env": {
            "episodes": N_EPISODES,
            "steps_per_episode": STEPS_PER_EPISODE,
            "total_steps": n_steps,
        },
        "durable_ms_per_op": {
            op: {"mean": round(statistics.mean(v), 4),
                 "p50": round(pct(v, 50), 4),
                 "p99": round(pct(v, 99), 4)}
            for op, v in lat.items()
        },
        "durable_ms_per_step_total": {
            "mean": round(statistics.mean(per_step), 4),
            "p50": round(pct(per_step, 50), 4),
            "p99": round(pct(per_step, 99), 4),
        },
        "inmemory_ms_per_step": {
            "mean": round(statistics.mean(mem), 5),
            "p99": round(pct(mem, 99), 5),
        },
        "bytes_per_op": {
            op: {"mean": round(statistics.mean(v), 1)}
            for op, v in nbytes.items()
        },
        "bytes_per_step_total": round(
            statistics.mean(nbytes["claim"]) + statistics.mean(nbytes["commit"])
            + statistics.mean(nbytes["checkpoint"]), 1),
    }
    print(json.dumps(out, indent=2))
    with open(os.path.join(PROJECT, "overhead_raw.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("wrote overhead_raw.json")


if __name__ == "__main__":
    sys.exit(main())
