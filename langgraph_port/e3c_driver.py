#!/usr/bin/env python3
"""E3c — concurrent workflows against ONE shared tool server ($0, scripted).

For K in {1, 4, 16}: start a single shared tool_server on port 8770, then
launch K crash_harness_v2 campaigns concurrently (each 20 wal episodes,
distinct run-tags, A1_REUSE_SERVER=1 + A1_SHARED_LEDGER_DIR so scoring reads
the shared ledger). Measures: wall-clock time, per-episode latency
p50/p99, duplicate rate / exactly-once under server contention.

Launches harnesses detached with setsid/nohup so they survive; this driver
then blocks until all K harnesses exit.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

PORT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(PORT_DIR, ".venv", "bin", "python")
PROJ = os.path.dirname(PORT_DIR)
PORT = 8770


def sh(cmd, **kw):
    return subprocess.Popen(cmd, **kw)


def wait_healthy(url, tries=200):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url + "/health", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.05)
    return False


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0.0


def main():
    results = {}
    for k in (1, 4, 16):
        tag = f"e3c_shared_k{k}"
        sdir = os.path.join(PORT_DIR, "runs", tag, "_server", "shared")
        os.makedirs(sdir, exist_ok=True)
        srv_log = open(os.path.join(PORT_DIR, "logs", f"e3c_k{k}_server.log"), "w")
        srv = sh([VENV_PY, os.path.join(PORT_DIR, "tool_server.py"),
                  "--state-dir", sdir, "--host", "127.0.0.1",
                  "--port", str(PORT)],
                 stdout=srv_log, stderr=subprocess.STDOUT)
        url = f"http://127.0.0.1:{PORT}"
        assert wait_healthy(url), f"shared server failed to start (K={k})"
        print(f"[K={k}] shared server up at {url}", flush=True)

        env = dict(os.environ, A1_REUSE_SERVER="1", A1_SHARED_LEDGER_DIR=sdir)
        procs = []
        t0 = time.time()
        for j in range(k):
            rtag = f"{tag}_j{j}"
            logf = open(os.path.join(PORT_DIR, "logs", f"e3c_k{k}_j{j}.log"), "w")
            p = sh(["setsid", "nohup", VENV_PY, "crash_harness_v2.py",
                    "--config", "config_e3c.json", "--run-tag", rtag,
                    "--out", f"results_e3c_k{k}_j{j}.json",
                    "--jsonl-out", f"results_e3c_k{k}_j{j}.jsonl"],
                   cwd=PORT_DIR, env=env,
                   stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                   start_new_session=True)
            procs.append(p)
            print(f"[K={k}] harness j={j} pid={p.pid}", flush=True)
        for p in procs:
            p.wait()
        wall = time.time() - t0
        srv.terminate()
        srv.wait(timeout=10)

        # aggregate per-episode records across the K harness jsonl files
        eps = []
        for j in range(k):
            jp = os.path.join(PORT_DIR, f"results_e3c_k{k}_j{j}.jsonl")
            with open(jp) as f:
                for line in f:
                    eps.append(json.loads(line))
        lat = sorted(e["elapsed_s"] for e in eps)
        dup_eps = sum(1 for e in eps if e["duplicates"] > 0)
        eo = sum(1 for e in eps if e["exactly_once"])
        results[f"K={k}"] = {
            "harness_instances": k, "episodes": len(eps),
            "wall_clock_s": round(wall, 1),
            "episode_latency_s": {"p50": round(pct(lat, .5), 2),
                                 "p99": round(pct(lat, .99), 2),
                                 "max": round(max(lat), 2)},
            "duplicate_episode_rate": round(dup_eps / len(eps), 4),
            "exactly_once_rate": round(eo / len(eps), 4),
        }
        print(f"[K={k}] done: {len(eps)} eps, wall={wall:.0f}s, "
              f"ep_lat p50={pct(lat,.5):.1f}s p99={pct(lat,.99):.1f}s, "
              f"dup_rate={dup_eps/len(eps):.4f}, eo={eo/len(eps):.4f}", flush=True)

    doc = {}
    p = os.path.join(PROJ, "results_e3_scale.json")
    if os.path.exists(p):
        doc = json.load(open(p))
    doc["e3c_concurrent"] = results
    json.dump(doc, open(p, "w"), indent=2)
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
