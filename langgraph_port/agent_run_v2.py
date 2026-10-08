#!/usr/bin/env python3
"""Subprocess entry point for the v2 research-assistant agent.

One agent generation (fresh or recover) per OS process, so the crash driver
can SIGKILL it for real. Recovery is a new process with a new epoch.
Persists claim-log latency timings for the overhead analysis.
"""
import argparse
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agent_graph_v2
from agent_graph_v2 import build_graph_v2
from common import atomic_write_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["fresh", "recover"], required=True)
    ap.add_argument("--workflow-id", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--condition", choices=["wal", "baseline", "deterministic",
                                           "det_shift", "det_content"],
                    required=True)
    ap.add_argument("--server-url", required=True)
    ap.add_argument("--plan-seed", type=int, required=True)
    ap.add_argument("--recover-seed", type=int, required=True)
    ap.add_argument("--marker-sleep-ms", type=int, default=30)
    ap.add_argument("--retry-backoff-s", type=float, default=1.0)
    ap.add_argument("--p-reword", type=float, default=0.5)
    ap.add_argument("--p-plan-shift", type=float, default=0.3)
    ap.add_argument("--reword-recovery", action="store_true",
                    help="E2b: recovery replanning rephrases effect targets")
    ap.add_argument("--planner", choices=["scripted", "llm"],
                    default="scripted",
                    help="round-1 routing decision source: scripted (default) "
                         "or real gpt-4o-mini via the custom.openai connector")
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
        "retry_backoff_s": args.retry_backoff_s,
        "p_reword": args.p_reword,
        "p_plan_shift": args.p_plan_shift,
        "reword_recovery": args.reword_recovery,
        "planner": args.planner,
        "round": 0,
        "error": None,
    }
    result = {"workflow_id": args.workflow_id, "condition": args.condition,
              "mode": args.mode, "ok": False, "error": None}
    try:
        graph = build_graph_v2()
        final = graph.invoke(state, config={"recursion_limit": 1000})
        result["ok"] = True
        result["rounds_completed"] = final.get("round")
    except Exception as e:  # noqa: BLE001 — must survive to report
        result["error"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()[-4000:]
    atomic_write_json(os.path.join(args.run_dir,
                                   f"agent_result_v2_{args.mode}.json"),
                      result)
    atomic_write_json(os.path.join(args.run_dir,
                                   f"claim_timings_v2_{args.mode}.json"),
                      [{"op": op, "latency_s": lat}
                       for op, lat in agent_graph_v2.CLAIM_TIMINGS])
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
