#!/usr/bin/env python3
"""E3c: concurrent-workflow load test on the tool server.

Spawns a tool server and hammers it with K concurrent clients doing
fence + commit RPCs. Measures: throughput (ops/s), p50/p99 latency,
and whether the server serializes (latency collapse under concurrency).

$0, stdlib only (urllib + threads).
"""
import json, os, subprocess, sys, tempfile, threading, time, urllib.request

PORT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(PORT_DIR, ".venv", "bin", "python")


def rpc(url, path, payload):
    req = urllib.request.Request(
        url + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    K = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    OPS_PER_CLIENT = 50
    state_dir = tempfile.mkdtemp(prefix="e3c_srv_")
    port = 8791
    proc = subprocess.Popen(
        [VENV_PY, os.path.join(PORT_DIR, "tool_server.py"),
         "--state-dir", state_dir, "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(200):
            try:
                with urllib.request.urlopen(url + "/health", timeout=1):
                    break
            except Exception:
                time.sleep(0.05)
        lat = []
        lock = threading.Lock()

        def client(cid):
            rpc(url, "/fence", {"workflow_id": f"e3c-w{cid}", "epoch": 1})
            for i in range(OPS_PER_CLIENT):
                t0 = time.perf_counter()
                rpc(url, "/tool", {
                    "workflow_id": f"e3c-w{cid}", "epoch": 1,
                    "key": f"k-{cid}-{i}", "action": "a", "target": f"t-{i}"})
                dt = (time.perf_counter() - t0) * 1000
                with lock:
                    lat.append(dt)

        t0 = time.perf_counter()
        threads = [threading.Thread(target=client, args=(c,)) for c in range(K)]
        for t in threads: t.start()
        for t in threads: t.join()
        wall = time.perf_counter() - t0
        lat.sort()
        total = len(lat)
        p50 = lat[total // 2]
        p99 = lat[int(total * 0.99)]
        print(json.dumps({
            "concurrency": K, "total_ops": total,
            "wall_s": round(wall, 2),
            "throughput_ops": round(total / wall, 1),
            "lat_p50_ms": round(p50, 2), "lat_p99_ms": round(p99, 2),
        }, indent=2))
        out = os.path.join(PORT_DIR, f"results_e3c_k{K}.json")
        json.dump({"concurrency": K, "total_ops": total, "wall_s": wall,
                   "throughput_ops": total / wall,
                   "lat_p50_ms": p50, "lat_p99_ms": p99},
                  open(out, "w"), indent=2)
        print("wrote", out)
    finally:
        proc.kill()


if __name__ == "__main__":
    main()
