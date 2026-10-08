#!/usr/bin/env python3
"""E3b — claim-log length microbenchmark ($0, no LLM, no crashes).

Quantifies the O(n) lookup cost of the append-only JSONL claim log:
  append N claims to a ClaimLog (N in {100, 1_000, 10_000});
  measure per-append latency p50/p99/max;
  measure find_by_identity latency (present hit + absent miss) vs N;
  measure claims() full-scan latency vs N.

Honest denominator: JSONL append is O(1) per record; find_by_identity and
claims() are linear scans. This is the measurement the reviewer would ask
about; if lookup degrades, we report it and note indexing as follow-up.

Output: results_e3_scale.json (E3b section) + stdout summary.
"""
import json
import os
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "langgraph_port"))
from claim_log import ClaimLog


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return 0.0
    i = min(len(xs) - 1, int(q * len(xs)))
    return xs[i]


def bench(n):
    d = tempfile.mkdtemp(prefix=f"e3b_n{n}_")
    log = ClaimLog(os.path.join(d, "claim.log"))
    appends = []
    for i in range(n):
        t0 = time.perf_counter()
        log.append_claim(f"uid-{i}", "fetch", f"target-r0-b{i % 8}",
                         f"note {i}", f"key-{i}", 1)
        appends.append((time.perf_counter() - t0) * 1000.0)
    # hit: identity present (last record); miss: absent identity
    hits, misses, scans = [], [], []
    for _ in range(50):
        t0 = time.perf_counter()
        log.find_by_identity("fetch", f"target-r0-b{(n - 1) % 8}")
        hits.append((time.perf_counter() - t0) * 1000.0)
        t0 = time.perf_counter()
        log.find_by_identity("fetch", "target-absent-xyz")
        misses.append((time.perf_counter() - t0) * 1000.0)
        t0 = time.perf_counter()
        log.claims()
        scans.append((time.perf_counter() - t0) * 1000.0)
    size_b = os.path.getsize(os.path.join(d, "claim.log"))
    return {
        "n": n,
        "append_ms": {"p50": pct(appends, .5), "p99": pct(appends, .99),
                      "max": max(appends)},
        "find_hit_ms": {"p50": pct(hits, .5), "p99": pct(hits, .99)},
        "find_miss_ms": {"p50": pct(misses, .5), "p99": pct(misses, .99)},
        "full_scan_ms": {"p50": pct(scans, .5), "p99": pct(scans, .99)},
        "log_bytes": size_b,
    }


def main():
    out = []
    for n in (100, 1_000, 10_000):
        r = bench(n)
        out.append(r)
        print(f"N={n:6d} append p50={r['append_ms']['p50']:.3f}ms "
              f"p99={r['append_ms']['p99']:.3f}ms max={r['append_ms']['max']:.3f}ms "
              f"| find(hit) p50={r['find_hit_ms']['p50']:.3f}ms "
              f"| find(miss) p50={r['find_miss_ms']['p50']:.3f}ms "
              f"| scan p50={r['full_scan_ms']['p50']:.3f}ms "
              f"| log={r['log_bytes']/1e6:.2f}MB", flush=True)
    proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(proj, "results_e3_scale.json")
    doc = {}
    if os.path.exists(p):
        doc = json.load(open(p))
    doc["e3b_log_length"] = out
    json.dump(doc, open(p, "w"), indent=2)
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
