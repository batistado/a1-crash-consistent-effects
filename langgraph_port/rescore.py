#!/usr/bin/env python3
"""Rescore completed episodes from durable on-disk state.

Used when the episode driver dies before writing its summary (the per-episode
records were only held in memory). Every input here is durable:
run_meta.json, plan.json, agent_result_*.json, progress.log, the tool
server's ledger.jsonl/epochs.json, and each run's scratch/audit.log.

Zombie probes are RE-EXECUTED (not inferred): the fencing epochs persist in
epoch.json / the server's epochs.json, so a stale-epoch probe today tests
the same fence the live probe tested.

Usage:
  .venv/bin/python rescore.py --run-root runs --server-state-dir \
      runs/_server/20261007-062144 --conditions wal,baseline \
      --server-url http://127.0.0.1:8765   # server must be running on the state dir
  Writes rescore_records.json (list of per-episode records, same shape as
  crash_harness.py emits).
"""
import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import is_effectful, read_json, score_episode
from file_tool import FileTool, FencedError

TARGET_FOR = {
    "pre_step": "CLAIM",
    "in_window": "TOOL_CALLED",
    "post_checkpoint": "CHECKPOINT",
}


def load_ledger_entries(ledger_path, workflow_id):
    out = []
    if os.path.exists(ledger_path):
        with open(ledger_path, "rb") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("workflow_id") == workflow_id:
                    out.append((rec.get("action"), rec.get("target")))
    return out


def probe_http_stale(server_url, workflow_id):
    body = json.dumps({"workflow_id": workflow_id, "step_uid": "zombie",
                       "action": "issue_refund", "target": "zombie",
                       "note": "zombie", "key": f"zombie-{workflow_id}",
                       "epoch": -1}).encode()
    req = urllib.request.Request(server_url + "/tool", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r).get("status") == "fenced"
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return json.load(e).get("status") == "fenced"
        return False
    except Exception:
        return False


def probe_file_stale(run_dir):
    try:
        FileTool(run_dir).append("append_audit", "zombie-probe", "z",
                                 "zombie-key", epoch=-1)
        return False
    except FencedError:
        return True


def rescore_episode(run_dir, ledger_path, server_url):
    meta = read_json(os.path.join(run_dir, "run_meta.json"))
    wid = meta["workflow_id"]
    cond = meta["condition"]
    target = f"STEP {meta['crash_step_uid']} {TARGET_FOR[meta['landing']]}"
    try:
        with open(os.path.join(run_dir, "progress.log"), "rb") as f:
            saw_marker = any(l.startswith(target.encode())
                             for l in f.read().split(b"\n"))
    except FileNotFoundError:
        saw_marker = False
    fresh_res = read_json(os.path.join(run_dir, "agent_result_fresh.json"))
    rec_res = read_json(os.path.join(run_dir, "agent_result_recover.json"))
    crashed = bool(saw_marker and (not fresh_res or not fresh_res.get("ok")))
    crash_missed = not saw_marker
    recover_ok = bool(rec_res and rec_res.get("ok"))

    plan_doc = read_json(os.path.join(run_dir, "plan.json"), {})
    intended = [(s["action"], s["args"].get("target"))
                for s in plan_doc.get("plan", []) if is_effectful(s)]
    committed = load_ledger_entries(ledger_path, wid)
    for e in FileTool(run_dir).ledger():
        committed.append((e["action"], e["target"]))
    sc = score_episode(intended, committed)
    return {
        "workflow_id": wid, "condition": cond, "episode": meta["episode"],
        "plan_seed": meta["plan_seed"], "recover_seed": meta["recover_seed"],
        "crash_step_uid": meta["crash_step_uid"], "landing": meta["landing"],
        "crashed": crashed, "crash_missed": crash_missed,
        "recover_ok": recover_ok,
        "duplicates": sc["duplicates"], "missing": sc["missing"],
        "exactly_once": sc["exactly_once"],
        "zombie_http_fenced": probe_http_stale(server_url, wid),
        "zombie_file_fenced": probe_file_stale(run_dir),
        "n_intended": len(intended), "n_committed": len(committed),
        "elapsed_s": None,  # not recoverable; timing was informational
        "rescored": True,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-root", default="runs")
    ap.add_argument("--server-state-dir", required=True)
    ap.add_argument("--server-url", required=True)
    ap.add_argument("--conditions", required=True)
    ap.add_argument("--out", default="rescore_records.json")
    args = ap.parse_args()
    conds = [c.strip() for c in args.conditions.split(",")]
    ledger_path = os.path.join(args.server_state_dir, "ledger.jsonl")
    records = []
    for cond in conds:
        cdir = os.path.join(args.run_root, cond)
        for wf in sorted(os.listdir(cdir)):
            rdir = os.path.join(cdir, wf)
            if not os.path.isdir(rdir):
                continue
            # skip partial episodes (no recovery result): they never completed
            if not os.path.exists(os.path.join(rdir, "agent_result_recover.json")):
                print(f"SKIP partial {wf}")
                continue
            rec = rescore_episode(rdir, ledger_path, args.server_url)
            records.append(rec)
    records.sort(key=lambda r: (r["condition"], r["episode"]))
    with open(args.out, "w") as f:
        json.dump(records, f, indent=2)
    n = len(records)
    bad = [r for r in records if not r["exactly_once"] and r["condition"] == "wal"]
    print(f"rescored {n} episodes -> {args.out}")
    print(f"wal non-exactly-once: {len(bad)}; "
          f"crash_missed: {sum(r['crash_missed'] for r in records)}; "
          f"recover failures: {sum(not r['recover_ok'] for r in records)}")


if __name__ == "__main__":
    sys.exit(main())
