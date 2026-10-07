#!/usr/bin/env python3
"""Subprocess entry point: runs one agent generation (fresh or recover).

Each episode's agent runs in its own OS process so the crash driver can
SIGKILL it for real. The recovery generation is a *new* process with a new
epoch — exactly the production crash-restart shape. Only durable state
(claim.log, checkpoint.json, epoch.json, plan.json, tool-server ledgers,
scratch files) crosses the crash.

Prints a JSON result to stdout; also writes agent_result.json in the run dir.
"""
import argparse
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_graph import build_graph
from common import atomic_write_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["fresh", "recover"], required=True)
    ap.add_argument("--workflow-id", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--condition", choices=["wal", "baseline", "deterministic"],
                    required=True)
    ap.add_argument("--server-url", required=True)
    ap.add_argument("--plan-seed", type=int, required=True)
    ap.add_argument("--recover-seed", type=int, required=True)
    ap.add_argument("--marker-sleep-ms", type=int, default=30)
    ap.add_argument("--p-reword", type=float, default=0.5)
    ap.add_argument("--p-plan-shift", type=float, default=0.3)
    args = ap.parse_args()

    os.makedirs(args.run_dir, exist_ok=True)
    state = {
        "workflow_id": args.workflow_id,
        "run_dir": args.run_dir,
        "condition": args.condition,
        "mode": args.mode,
        "epoch": 0,
        "server_url": args.server_url,
        "plan_seed": args.plan_seed,
        "recover_seed": args.recover_seed,
        "marker_sleep_ms": args.marker_sleep_ms,
        "p_reword": args.p_reword,
        "p_plan_shift": args.p_plan_shift,
        "plan": [],
        "queue": [],
        "pos": 0,
        "checkpoint": -1,
        "error": None,
    }
    result = {"workflow_id": args.workflow_id, "condition": args.condition,
              "mode": args.mode, "ok": False, "error": None}
    try:
        graph = build_graph()
        final = graph.invoke(state, config={"recursion_limit": 500})
        result["ok"] = True
        result["checkpoint"] = final.get("checkpoint")
        result["steps_executed"] = final.get("pos")
    except Exception as e:  # noqa: BLE001 — must survive to report
        result["error"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()[-4000:]
    atomic_write_json(os.path.join(args.run_dir, f"agent_result_{args.mode}.json"),
                      result)
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
