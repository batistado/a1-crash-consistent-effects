#!/usr/bin/env python3
"""Subprocess entry point for the E1 native-persistence baseline.

One agent generation per OS process (fresh or resume), so the crash driver
can SIGKILL it for real.

  --mode fresh   : invoke the checkpointer-compiled graph with initial state.
  --mode recover : invoke with state=None and the same thread_id — LangGraph
                   resumes from the SqliteSaver checkpoint. There is no
                   manual recover_node; this is the framework's native path.

Condition is always "native" (deterministic keys, no claim log, no fencing).
"""
import argparse
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langgraph.checkpoint.sqlite import SqliteSaver

from agent_graph_v2_native import build_graph_v2_native
from common import atomic_write_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["fresh", "recover"], required=True)
    ap.add_argument("--workflow-id", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--server-url", required=True)
    ap.add_argument("--plan-seed", type=int, required=True)
    ap.add_argument("--recover-seed", type=int, required=True)
    ap.add_argument("--marker-sleep-ms", type=int, default=30)
    ap.add_argument("--retry-backoff-s", type=float, default=1.0)
    args = ap.parse_args()

    os.makedirs(args.run_dir, exist_ok=True)
    db_path = os.path.join(args.run_dir, "checkpoints.db")
    # Progress marker so the harness's partial-fanout analysis can cut
    # pre-crash lines (same convention as the manual recover_node).
    if args.mode == "recover":
        with open(os.path.join(args.run_dir, "progress.log"), "ab",
                  buffering=0) as f:
            f.write(b"RECOVER native-checkpointer-resume\n")
            os.fsync(f.fileno())
    result = {"workflow_id": args.workflow_id, "condition": "native",
              "mode": args.mode, "ok": False, "error": None}
    try:
        with SqliteSaver.from_conn_string(db_path) as checkpointer:
            graph = build_graph_v2_native(checkpointer)
            cfg = {"configurable": {"thread_id": args.workflow_id},
                   "recursion_limit": 1000}
            if args.mode == "fresh":
                state = {
                    "workflow_id": args.workflow_id,
                    "run_dir": args.run_dir,
                    "condition": "native",
                    "mode": "fresh",
                    "epoch": 0,
                    "server_url": args.server_url,
                    "plan_seed": args.plan_seed,
                    "recover_seed": args.recover_seed,
                    "marker_sleep_ms": args.marker_sleep_ms,
                    "retry_backoff_s": args.retry_backoff_s,
                    "p_reword": 0.0,
                    "p_plan_shift": 0.0,
                    "planner": "scripted",
                    "round": 0,
                    "error": None,
                }
                final = graph.invoke(state, cfg)
            else:
                # Native resume: no state, no manual recovery node.
                final = graph.invoke(None, cfg)
            result["ok"] = True
            result["rounds_completed"] = (final or {}).get("round")
    except Exception as e:  # noqa: BLE001 — must survive to report
        result["error"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()[-4000:]
    atomic_write_json(os.path.join(args.run_dir,
                                   f"agent_result_native_{args.mode}.json"),
                      result)
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
