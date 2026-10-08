#!/usr/bin/env python3
"""E3b: claim-log length scaling microbenchmark.

Reviewer ask (§3): measure recovery-log lengths (TPDS scale behavior).

Appends N claims (+ N commit records) to a ClaimLog and measures:
  - append latency p50/p99/max vs N
  - find_by_identity latency vs N (the O(n) linear scan)
  - load() time vs N (recovery reads the whole log)

$0, stdlib + claim_log only.
"""
import json
import os
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "langgraph_port"))
from claim_log import ClaimLog


def pct(xs, q):
    xs = sorted(xs)
    return xs[max(0, int(q * len(xs)) - 1)]


def bench(n):
    d = tempfile.mkdtemp(prefix="e3b_")
    log = ClaimLog(os.path.join(d, "claim.log"))
    append_lats = []
    for i in range(n):
        t0 = time.perf_counter()
        log.append_claim(f"r0b{i % 8}e{i}", "record_finding",
                         f"finding-r0-b{i % 8}-{i}", f"note {i}",
                         f"det:wid:r0:b{i % 8}:e{i}:record_finding", 0)
        append_lats.append(time.perf_counter() - t0)
    for i in range(n):
        c = {"uid": f"r0b{i % 8}e{i}", "key": f"det:wid:r0:b{i % 8}:e{i}",
             "action": "record_finding",
             "target": f"finding-r0-b{i % 8}-{i}"}
        t0 = time.perf_counter()
        log.append_commit(c)
        append_lats.append(time.perf_counter() - t0)

    # find_by_identity: hit (last claim) and miss
    t0 = time.perf_counter()
    log.find_by_identity("record_finding", f"finding-r0-b{(n - 1) % 8}-{n - 1}")
    find_hit = time.perf_counter() - t0
    t0 = time.perf_counter()
    log.find_by_identity("record_finding", "nonexistent-target")
    find_miss = time.perf_counter() - t0

    t0 = time.perf_counter()
    recs = log.load()
    load_t = time.perf_counter() - t0

    return {
        "n_claims": n,
        "records": len(recs),
        "append_p50_ms": round(pct(append_lats, 0.5) * 1000, 3),
        "append_p99_ms": round(pct(append_lats, 0.99) * 1000, 3),
        "append_max_ms": round(max(append_lats) * 1000, 3),
        "find_hit_ms": round(find_hit * 1000, 3),
        "find_miss_ms": round(find_miss * 1000, 3),
        "load_s": round(load_t, 4),
    }


def main():
    out = []
    for n in (100, 1000, 10000):
        r = bench(n)
        out.append(r)
        print(f"n={n}: append p50={r['append_p50_ms']}ms "
              f"p99={r['append_p99_ms']}ms find_hit={r['find_hit_ms']}ms "
              f"find_miss={r['find_miss_ms']}ms load={r['load_s']}s",
              flush=True)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "results_e3b_logscale.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("wrote results_e3b_logscale.json")


if __name__ == "__main__":
    sys.exit(main())
