#!/usr/bin/env python3
"""A genuine LangGraph StateGraph agent implementing the A1 WAL protocol.

Nodes: plan -> claim -> execute -> commit -> checkpoint, looping per step.
Recovery mode: recover -> plan -> claim -> execute -> commit -> checkpoint.

The task planner is scripted/deterministic (common.make_plan): the fault
under study is harness-side crash consistency, not agent cognition, so a
deterministic planner is an honest scoping choice (see LANGGRAPH_PORT.md).
Everything else is real: the graph is a real LangGraph StateGraph, the
tools have real side effects (HTTP POST to the tool-server process; file
appends to the scratch dir), the claim log is fsync'd per record, the
checkpoint is atomic, and crashes are real SIGKILLs delivered by an
external watchdog that only observes the progress markers.

Deliberately NOT used: LangGraph's own checkpointer (MemorySaver etc.).
That would checkpoint trajectory state — the very thing the paper shows is
insufficient. Durability here comes from the claim log + checkpoint file,
which is the mechanism under test.

Progress markers (progress.log) are chaos-instrumentation, not protocol:
after each node's durable op the agent appends a marker and sleeps
marker_sleep_ms so the external crash driver can land SIGKILL precisely in
the commit->checkpoint window. The agent is oblivious to the crash plan.
"""
import os
import random
import time
from typing import Optional

import requests
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from checkpoint_store import CheckpointStore
from claim_log import ClaimLog
from common import (atomic_write_json, claim_identity, deterministic_key,
                    is_effectful, is_file_action, make_plan, read_json,
                    reword_args, READ_ACTION)
from file_tool import FileTool, FencedError


class AgentState(TypedDict, total=False):
    workflow_id: str
    run_dir: str
    condition: str          # wal | baseline | deterministic
    mode: str               # fresh | recover
    epoch: int
    server_url: str
    plan_seed: int
    recover_seed: int
    marker_sleep_ms: int
    p_reword: float
    p_plan_shift: float
    plan: list
    queue: list             # effectful steps still to execute, in order
    pos: int
    current: dict
    current_key: Optional[str]
    skip_current: bool
    last_status: str
    checkpoint: int
    error: Optional[str]


# --------------------------------------------------------------------------
# chaos instrumentation: progress markers observed by the external watchdog
# --------------------------------------------------------------------------
def _marker(state, text, sleep=True):
    path = os.path.join(state["run_dir"], "progress.log")
    with open(path, "ab", buffering=0) as f:
        f.write((text + "\n").encode())
        os.fsync(f.fileno())
    if sleep:
        time.sleep(state["marker_sleep_ms"] / 1000.0)


def _step_marker(state, uid, stage, extra=""):
    _marker(state, f"STEP {uid} {stage}" + (f" {extra}" if extra else ""))


# --------------------------------------------------------------------------
# tools (real side effects)
# --------------------------------------------------------------------------
def _http_tool_call(server_url, workflow_id, step_uid, action, target, note,
                    key, epoch):
    """REAL side effect: HTTP POST to the tool-server process, which commits
    durably to its ledger (or suppresses/fences)."""
    r = requests.post(server_url + "/tool", json={
        "workflow_id": workflow_id, "step_uid": step_uid, "action": action,
        "target": target, "note": note, "key": key, "epoch": epoch,
    }, timeout=30)
    body = r.json()
    if r.status_code == 409 or body.get("status") == "fenced":
        raise FencedError(f"tool server fenced call: {body}")
    return body


# --------------------------------------------------------------------------
# nodes
# --------------------------------------------------------------------------
def plan_node(state):
    run_dir = state["run_dir"]
    wid = state["workflow_id"]
    if state["mode"] == "fresh":
        rng = random.Random(state["plan_seed"])
        plan = make_plan(rng)
        atomic_write_json(os.path.join(run_dir, "plan.json"),
                          {"workflow_id": wid, "plan": plan,
                           "plan_seed": state["plan_seed"]})
        # durable fencing state starts at epoch 0
        atomic_write_json(os.path.join(run_dir, "epoch.json"), {"epoch": 0})
        FileTool(run_dir).set_epoch(0)
        CheckpointStore(run_dir).set(-1, 0)
        queue = [s for s in plan if is_effectful(s)]
        _marker(state, f"PLAN n={len(plan)} effectful={len(queue)}", sleep=False)
        return {"plan": plan, "queue": queue, "pos": 0, "epoch": 0,
                "checkpoint": -1}
    # recover mode: reload the durable plan, reconcile position from the
    # checkpoint, then model post-recovery replanning nondeterminism
    # (reword args / shift plan) exactly like the scripted sandbox.
    plan = read_json(os.path.join(run_dir, "plan.json"))["plan"]
    ckpt = CheckpointStore(run_dir).get()
    rng = random.Random(state["recover_seed"])
    queue = [dict(s) for s in plan
             if is_effectful(s) and s["uid"] > ckpt["checkpoint"]]
    shift = rng.random() < state["p_plan_shift"]
    reword = rng.random() < state["p_reword"]
    if shift:
        # recovered agent inserts a diagnostic read; subsequent step indices
        # shift +1 (the deterministic-key failure mode of sandbox (ii-b))
        for s in queue:
            s["uid"] = s["uid"] + 1
    if reword:
        for s in queue:
            s["args"] = reword_args(s["args"])
    _marker(state, f"RECOVER_PLAN remaining={len(queue)} "
                   f"shift={shift} reword={reword}", sleep=False)
    atomic_write_json(os.path.join(run_dir, "recovery_plan.json"),
                      {"queue": queue, "shift": shift, "reword": reword,
                       "checkpoint": ckpt["checkpoint"]})
    return {"plan": plan, "queue": queue, "pos": 0,
            "checkpoint": ckpt["checkpoint"]}


def recover_node(state):
    """Recovery path (DESIGN.md §2): new epoch, fence acquisition, then
    reconcile-first — replay every uncommitted claim with its ORIGINAL key."""
    run_dir = state["run_dir"]
    wid = state["workflow_id"]
    stored = read_json(os.path.join(run_dir, "epoch.json"), {"epoch": 0})
    new_epoch = int(stored.get("epoch", 0)) + 1
    atomic_write_json(os.path.join(run_dir, "epoch.json"),
                      {"epoch": new_epoch})
    # fence acquisition BEFORE anything else: the new generation registers
    # with the tool so in-flight calls from the dead generation go stale.
    r = requests.post(state["server_url"] + "/fence",
                      json={"workflow_id": wid, "epoch": new_epoch}, timeout=30)
    r.raise_for_status()
    FileTool(run_dir).set_epoch(new_epoch)
    _marker(state, f"RECOVER fenced epoch={new_epoch}", sleep=False)

    if state["condition"] == "wal":
        log = ClaimLog(os.path.join(run_dir, "claim.log"))
        for claim in log.uncommitted():
            if is_file_action({"action": claim["action"]}):
                res = FileTool(run_dir).append(
                    claim["action"], claim["target"], claim["note"],
                    claim["key"], new_epoch)
            else:
                res = _http_tool_call(
                    state["server_url"], wid, claim["uid"], claim["action"],
                    claim["target"], claim["note"], claim["key"], new_epoch)
            status = res["status"]
            _marker(state, f"RECOVER replay key={claim['key']} status={status}",
                    sleep=False)
            if status in ("committed", "duplicate_suppressed"):
                log.append_commit(claim)
            else:
                raise RuntimeError(f"reconcile failed: {res}")
        # checkpoint is fenced by the log: advance past reconciled claims
        done = [c["uid"] for c in log.claims() if log.is_committed(c)]
        ckpt = max(done) if done else -1
        CheckpointStore(run_dir).set(ckpt, new_epoch)
        _marker(state, f"RECOVER checkpoint={ckpt}", sleep=False)
        return {"epoch": new_epoch, "checkpoint": ckpt}
    # baseline / deterministic: no log to reconcile; checkpoint as-is
    ckpt = CheckpointStore(run_dir).get()
    CheckpointStore(run_dir).set(ckpt["checkpoint"], new_epoch)
    return {"epoch": new_epoch, "checkpoint": ckpt["checkpoint"]}


def claim_node(state):
    """Write-ahead claim (wal) / key derivation (deterministic) / nothing
    (baseline). Recovery replays uncommitted claims with ORIGINAL keys; steps
    whose (action, target) already has a committed claim are skipped."""
    step = state["queue"][state["pos"]]
    uid, action = step["uid"], step["action"]
    args = step["args"]
    wid = state["workflow_id"]
    cond = state["condition"]
    key, skip = None, False
    if cond == "wal":
        log = ClaimLog(os.path.join(state["run_dir"], "claim.log"))
        existing = log.find_by_identity(action, args.get("target"),
                                          args.get("occurrence", 0))
        if existing is not None:
            # Never re-derive: reuse the durable pre-crash key. A committed
            # claim means the effect is done — skip re-execution entirely.
            key = existing["key"]
            skip = log.is_committed(existing)
        else:
            key = deterministic_key(wid, uid, action)
            occ = log.next_occurrence(action, args.get("target"))
            log.append_claim(uid, action, args.get("target"),
                             args.get("note"), key, state["epoch"],
                             occurrence=occ)
    elif cond == "deterministic":
        # keys-alone: re-derived at call time from retry-time inputs.
        # Fragile to plan shifts by construction (Theorem 1, case ii).
        key = deterministic_key(wid, uid, action)
    _step_marker(state, uid, "CLAIM", f"key={key} skip={skip}")
    return {"current": step, "current_key": key, "skip_current": skip}


def execute_node(state):
    """Invoke the tool — the effect COMMITS here (t_commit). The watchdog's
    in-window SIGKILL lands after this node's marker, before commit."""
    if state["skip_current"]:
        return {"last_status": "skipped"}
    step = state["current"]
    uid, action = step["uid"], step["action"]
    args, key = step["args"], state["current_key"]
    wid = state["workflow_id"]
    if is_file_action(step):
        res = FileTool(state["run_dir"]).append(
            action, args.get("target"), args.get("note"), key, state["epoch"])
    else:
        res = _http_tool_call(state["server_url"], wid, uid, action,
                              args.get("target"), args.get("note"),
                              key, state["epoch"])
    status = res["status"]
    _step_marker(state, uid, "TOOL_CALLED", f"status={status}")
    return {"last_status": status}


def commit_node(state):
    """Durable COMMIT record (wal only). Marks the claim settled in the log."""
    if state["condition"] == "wal" and not state["skip_current"]:
        step = state["current"]
        log = ClaimLog(os.path.join(state["run_dir"], "claim.log"))
        claim = None
        for c in log.claims():
            if c["key"] == state["current_key"]:
                claim = c
        if claim is None:
            raise RuntimeError("commit without claim — claim discipline "
                               "violated (should be impossible)")
        log.append_commit(claim)
        _step_marker(state, step["uid"], "COMMIT")
    return {}


def checkpoint_node(state):
    """Advance the durable checkpoint past the current step (log-fenced in
    wal: the commit node ran first, so COMMIT ∈ log is guaranteed)."""
    step = state["current"]
    uid = step["uid"]
    if state["condition"] == "wal" and not state["skip_current"]:
        log = ClaimLog(os.path.join(state["run_dir"], "claim.log"))
        assert state["current_key"] in log.committed_keys(), \
            "log-fenced checkpoint violated: no COMMIT for current key"
    CheckpointStore(state["run_dir"]).set(uid, state["epoch"])
    _step_marker(state, uid, "CHECKPOINT")
    return {"checkpoint": uid, "pos": state["pos"] + 1}


# --------------------------------------------------------------------------
# graph assembly
# --------------------------------------------------------------------------
def entry_router(state):
    # return the path-map KEY; add_conditional_edges translates via the map
    return "recover" if state["mode"] == "recover" else "fresh"


def step_router(state):
    return "next" if state["pos"] < len(state["queue"]) else "done"


def plan_router(state):
    # Recovery can legitimately have nothing left to do (crash landed
    # post-checkpoint on the final step): then the graph is done.
    return "work" if state["pos"] < len(state["queue"]) else "empty"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("plan", plan_node)
    g.add_node("recover", recover_node)
    g.add_node("claim", claim_node)
    g.add_node("execute", execute_node)
    g.add_node("commit", commit_node)
    g.add_node("checkpoint", checkpoint_node)
    g.add_conditional_edges(START, entry_router,
                            {"fresh": "plan", "recover": "recover"})
    g.add_edge("recover", "plan")
    g.add_conditional_edges("plan", plan_router,
                            {"work": "claim", "empty": END})
    g.add_edge("claim", "execute")
    g.add_edge("execute", "commit")
    g.add_edge("commit", "checkpoint")
    g.add_conditional_edges("checkpoint", step_router,
                            {"next": "claim", "done": END})
    return g.compile()
