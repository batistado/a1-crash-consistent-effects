#!/usr/bin/env python3
"""V2 'research-assistant' agent: a production-shaped LangGraph StateGraph.

Topology::

    plan -> supervisor -+-> dispatch -Send-> worker_subgraph (x3, parallel)
                        |                  (compiled subgraph:
                        |                   w_claim -> w_execute -> w_commit,
                        |                   with w_retry backoff loop on
                        |                   transient failure, then w_done)
                        |                       ||
                        |                       \\/
                        |                    aggregate -+
                        +-> esc_claim -> esc_execute -> esc_commit -+
                                                                   v
                                                              supervisor ...
                                                              -> finalize -> END

Real LangGraph features exercised:
  * add_conditional_edges — the supervisor makes genuine branching routing
    decisions (fan_out vs escalate vs done).
  * Send API — parallel fan-out to 3 worker subgraphs, fan-in via a reducer.
  * A compiled worker subgraph (not just nodes) — the delegate/worker shape
    real multi-agent systems use.
  * A framework-level retry loop with a REAL backoff sleep (w_retry).

WAL machinery is identical to v1 (durable fsync'd ClaimLog, epoch fencing,
log-fenced checkpoints) but claims are per (round, branch, effect). The new
fault under test is PARTIAL fan-out completion — some workers committed,
others not yet started — which the linear v1 loop cannot express.

Deliberately NOT used: LangGraph's own checkpointer (same reason as v1 —
that is the thing shown insufficient), and any LLM planner (scripted
decisions; the fault under study is harness-side, see DESIGN_V2.md).
"""
import operator
import json
import os
import random
import time
from typing import Annotated, Optional

import requests
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict

from checkpoint_store import CheckpointStore  # noqa: F401  (kept for parity)
from claim_log import ClaimLog
from common import atomic_write_json, is_file_action, read_json
from common_v2 import (branch_key, canonical_target_v2, claim_key_v2,
                       claim_uid, content_key_v2, escalate_effect,
                       intended_effects, is_transient_scripted, make_scenario,
                       reword_target_v2, supervisor_route, worker_effects)
from file_tool import FileTool, FencedError

# Per-record claim-log latency instrumentation (chaos/measurement only).
# Each agent process accumulates its own list; agent_run_v2.py persists it.
CLAIM_TIMINGS = []


class AgentStateV2(TypedDict, total=False):
    workflow_id: str
    run_dir: str
    condition: str          # wal | baseline | deterministic
    mode: str               # fresh | recover
    epoch: int
    server_url: str
    plan_seed: int
    recover_seed: int
    marker_sleep_ms: int
    retry_backoff_s: float
    p_reword: float
    p_plan_shift: float
    reword_recovery: bool   # E2b: recovery replanning rephrases targets
    planner: str             # scripted | llm (round-1 routing decision source)
    scenario: dict
    round: int
    route: str
    todo: list
    branch_results: Annotated[list, operator.add]
    esc_key: Optional[str]
    esc_skip: bool
    esc_status: str
    error: Optional[str]


class WorkerState(TypedDict, total=False):
    workflow_id: str
    run_dir: str
    condition: str
    epoch: int
    server_url: str
    marker_sleep_ms: int
    retry_backoff_s: float
    round: int
    branch: int
    effects: list
    idx: int
    attempts: int
    transient: bool
    status: str
    skip_effect: bool
    claim_uid: str
    claim_key: Optional[str]
    key_branch: Optional[int]   # E2a: shifted positional index for keys
    reword_recovery: bool       # E2b: targets rephrased in recovery
    branch_results: Annotated[list, operator.add]


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


def _wmarker(state, stage, extra=""):
    _marker(state, "WORKER r{} b{} e{} {}".format(
        state["round"], state["branch"], state["idx"], stage)
        + (f" {extra}" if extra else ""))


# --------------------------------------------------------------------------
# tools (real side effects; same contracts as v1)
# --------------------------------------------------------------------------
def _http_tool_call(server_url, workflow_id, step_uid, action, target, note,
                    key, epoch):
    r = requests.post(server_url + "/tool", json={
        "workflow_id": workflow_id, "step_uid": step_uid, "action": action,
        "target": target, "note": note, "key": key, "epoch": epoch,
    }, timeout=30)
    body = r.json()
    if r.status_code == 409 or body.get("status") == "fenced":
        raise FencedError(f"tool server fenced call: {body}")
    return body


def _do_tool(state, uid, action, target, key):
    """Execute one effect through the real tool path. Returns the status."""
    if is_file_action({"action": action}):
        res = FileTool(state["run_dir"]).append(
            action, target, f"v2 {uid}", key, state["epoch"])
    else:
        res = _http_tool_call(state["server_url"], state["workflow_id"], uid,
                              action, target, f"v2 {uid}", key,
                              state["epoch"])
    return res["status"]


# --------------------------------------------------------------------------
# durable branch-state (the v2 "checkpoint"): which branches are settled.
# Implemented as one atomic file per settled branch inside branch_done/ —
# append-only per branch, so concurrent worker threads can never lose each
# other's updates (a single read-modify-write JSON file races under Send
# fan-out; this is the same reason the claim log is append-only).
# --------------------------------------------------------------------------
def _branch_state_dir(run_dir):
    d = os.path.join(run_dir, "branch_done")
    os.makedirs(d, exist_ok=True)
    return d


def _read_branch_state(run_dir):
    d = _branch_state_dir(run_dir)
    branches, esc = [], False
    for f in os.listdir(d):
        if f == "esc.done":
            esc = True
        elif f.endswith(".json"):
            branches.append(f[:-len(".json")])
    return {"branches": branches, "escalate_done": esc}


def _mark_branch_done(run_dir, bkey):
    atomic_write_json(os.path.join(_branch_state_dir(run_dir), bkey + ".json"),
                      {"branch": bkey, "done": True})


def _mark_escalate_done(run_dir):
    atomic_write_json(os.path.join(_branch_state_dir(run_dir), "esc.done"),
                      {"done": True})


def _reset_branch_state(run_dir, branches, esc_done):
    """Wipe and rewrite from a log-derived settled set (wal recovery)."""
    import shutil
    d = _branch_state_dir(run_dir)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    for bkey in branches:
        _mark_branch_done(run_dir, bkey)
    if esc_done:
        _mark_escalate_done(run_dir)


# --------------------------------------------------------------------------
# supervisor graph nodes
# --------------------------------------------------------------------------
def plan_node(state):
    run_dir = state["run_dir"]
    if state["mode"] == "fresh":
        rng = random.Random(state["plan_seed"])
        scenario = make_scenario(rng)
        atomic_write_json(os.path.join(run_dir, "scenario.json"),
                          {"workflow_id": state["workflow_id"],
                           "scenario": scenario,
                           "plan_seed": state["plan_seed"]})
        atomic_write_json(os.path.join(run_dir, "epoch.json"), {"epoch": 0})
        FileTool(run_dir).set_epoch(0)
        _reset_branch_state(run_dir, [], False)
        _marker(state, "PLAN rounds={}".format(len(scenario["rounds"])),
                sleep=False)
        return {"scenario": scenario, "round": 0, "epoch": 0}
    scenario = read_json(os.path.join(run_dir, "scenario.json"))["scenario"]
    _marker(state, "RECOVER_PLAN rounds={}".format(len(scenario["rounds"])),
            sleep=False)
    return {"scenario": scenario}


def recover_node(state):
    """New epoch, fence acquisition, reconcile-first replay of every
    uncommitted claim with its ORIGINAL key, then log-fenced branch-state
    recomputation. After this, the supervisor simply re-runs: dispatch
    skips branches the log shows as settled."""
    run_dir = state["run_dir"]
    wid = state["workflow_id"]
    # Recovery resumes by re-running the supervisor from round 0 with the
    # same scenario: dispatch skips settled branches, workers skip settled
    # effects via the claim log (wal) / key dedup (deterministic).
    scenario = read_json(os.path.join(run_dir, "scenario.json"))["scenario"]
    stored = read_json(os.path.join(run_dir, "epoch.json"), {"epoch": 0})
    new_epoch = int(stored.get("epoch", 0)) + 1
    atomic_write_json(os.path.join(run_dir, "epoch.json"),
                      {"epoch": new_epoch})
    r = requests.post(state["server_url"] + "/fence",
                      json={"workflow_id": wid, "epoch": new_epoch}, timeout=30)
    r.raise_for_status()
    FileTool(run_dir).set_epoch(new_epoch)
    _marker(state, f"RECOVER fenced epoch={new_epoch}", sleep=False)

    if state["condition"] == "wal":
        log = ClaimLog(os.path.join(run_dir, "claim.log"))
        for claim in log.uncommitted():
            # Re-emit the ORIGINAL key — never re-derive (A2 of the protocol).
            status = _do_tool(
                {**state, "epoch": new_epoch}, claim["uid"], claim["action"],
                claim["target"], claim["key"])
            _marker(state, f"RECOVER replay uid={claim['uid']} "
                           f"status={status}", sleep=False)
            if status in ("committed", "duplicate_suppressed"):
                log.append_commit(claim)
            else:
                raise RuntimeError(f"reconcile failed: {status}")
        # Log-fenced checkpoint: branch-state advances ONLY past claims the
        # log shows as committed — and a branch counts as settled only when
        # ALL of its effects' claims are committed (partial fan-out must NOT
        # mark the branch done, or recovery would skip its remaining effects).
        committed_uids = {c["uid"] for c in log.claims()
                          if log.is_committed(c)}
        esc_done = "esc" in committed_uids
        done = []
        for rd in scenario["rounds"]:
            if rd["route"] != "fan_out":
                continue
            for b in rd["branches"]:
                effs = worker_effects(rd["round"], b)
                if all(claim_uid(rd["round"], b, e) in committed_uids
                       for e in range(len(effs))):
                    done.append(branch_key(rd["round"], b))
        _reset_branch_state(run_dir, done, esc_done)
        _marker(state, f"RECOVER branches_done={len(done)} esc={esc_done}",
                sleep=False)
    # baseline / deterministic: the per-branch done-files are already
    # durable; nothing to recompute.
    return {"epoch": new_epoch, "scenario": scenario, "round": 0}


def _persist_llm_decision(state, route, meta):
    """Durably record the LLM's round-1 routing decision.

    1. scenario.json: the recovery generation reads this for the wal
       log-fenced branch-state recomputation, so it must reflect the ACTUAL
       route, not the scripted placeholder written by plan_node.
    2. decisions.jsonl: audit trail + ground-truth source for the harness.
    The claim log is never consulted here (and never shown to the model).
    """
    run_dir = state["run_dir"]
    spath = os.path.join(run_dir, "scenario.json")
    doc = read_json(spath, {"scenario": {"rounds": []}})
    for rd in doc.get("scenario", {}).get("rounds", []):
        if rd.get("round") == 1:
            rd["route"] = route
            rd["branches"] = ([0, 1, 2] if route == "fan_out" else ["esc"])
    atomic_write_json(spath, {**doc, "llm_planner": True,
                              "llm_route1": route})
    dpath = os.path.join(run_dir, "decisions.jsonl")
    rec = {"round": 1, "mode": state["mode"], "route": route,
           "ts": time.time(), **meta}
    with open(dpath, "a") as f:
        f.write(json.dumps(rec) + "\n")
    # Return the updated scenario: the caller must feed it back into the
    # LangGraph state, because dispatch_node reads state["scenario"]
    # (in-memory), not the file. Without this, dispatch would use the
    # scripted placeholder route still in memory.
    return doc["scenario"]


def supervisor_node(state):
    if state.get("planner") == "llm" and state["round"] == 1:
        # Real-LLM routing decision. Round 0 stays structural (always
        # fan_out, as in the scripted scenario); round 1 is the genuine
        # routing judgment. The model receives only the reconciled branch
        # state -- in recover mode, recover_node (deterministic
        # reconciliation) has already run before this node.
        import llm_planner
        settled = set(_read_branch_state(state["run_dir"])["branches"])
        # Seeded per-episode evidence profile (identical in fresh/recover:
        # derived from plan_seed). Without varying evidence the prompt is
        # degenerate and the model can only ever fan out.
        evidence = llm_planner.evidence_summary(state["plan_seed"])
        route, meta = llm_planner.decide_route(
            1, settled, state["mode"], state["run_dir"], evidence)
        scenario = _persist_llm_decision(state, route, meta)
        # The BRANCH marker is the post-branch-decision crash window:
        # decision durable in the watchdog's sight, tool not yet invoked.
        _marker(state, f"BRANCH route={route} round={state['round']}")
        return {"route": route, "scenario": scenario}
    else:
        route = supervisor_route(state["scenario"], state["round"])
    # The BRANCH marker is the post-branch-decision crash window:
    # decision durable in the watchdog's sight, tool not yet invoked.
    _marker(state, f"BRANCH route={route} round={state['round']}")
    return {"route": route}


def sup_router(state):
    return state["route"]  # fan_out | escalate | done


def dispatch_node(state):
    """Fan-out point. Persists the dispatched set (chaos bookkeeping), then
    the router Sends one packet per unsettled branch into the worker
    subgraph. Branches the log already shows as settled are NOT re-sent —
    that skip is the recovery path; in the baseline condition the skip
    cannot happen (no log), which is exactly the measured duplicate."""
    rd = state["scenario"]["rounds"][state["round"]]
    done = set(_read_branch_state(state["run_dir"])["branches"])
    todo = [b for b in rd["branches"] if branch_key(state["round"], b) not in done]
    atomic_write_json(
        os.path.join(state["run_dir"],
                     f"dispatched_r{state['round']}.json"),
        {"round": state["round"], "dispatched": todo})
    _marker(state, f"DISPATCH round={state['round']} n={len(todo)}",
            sleep=False)
    return {"todo": todo}


def dispatch_router(state):
    todo = state["todo"]
    if not todo:
        return "aggregate"
    # E2a (det_shift): recovery replanning reprioritizes — rotate dispatch
    # positions so re-derived positional keys differ from fresh. The worker
    # still executes the ORIGINAL branch's effects (branch label unchanged);
    # only the key-derivation position shifts.
    # E2b (reword_recovery): recovery replanning rephrases targets.
    key_branch_of = {}
    if state["condition"] == "det_shift" and state["mode"] == "recover":
        rotated = todo[1:] + todo[:1]
        key_branch_of = {b: i for i, b in enumerate(rotated)}
        _marker(state, f"RESHIFT rotated={[str(b) for b in rotated]}",
                sleep=False)
    pkts = []
    for b in todo:
        effects = worker_effects(state["round"], b)
        if state.get("reword_recovery") and state["mode"] == "recover":
            effects = [dict(e, target=reword_target_v2(e["target"]))
                       for e in effects]
        pkt = {
            "workflow_id": state["workflow_id"],
            "run_dir": state["run_dir"],
            "condition": state["condition"],
            "epoch": state["epoch"],
            "server_url": state["server_url"],
            "marker_sleep_ms": state["marker_sleep_ms"],
            "retry_backoff_s": state["retry_backoff_s"],
            "round": state["round"],
            "branch": b,
            "effects": effects,
            "idx": 0, "attempts": 0, "transient": False,
            "skip_effect": False,
        }
        if b in key_branch_of:
            pkt["key_branch"] = key_branch_of[b]
        if state.get("reword_recovery"):
            pkt["reword_recovery"] = True
        pkts.append(Send("worker_sub", pkt))
    return pkts


def aggregate_node(state):
    _marker(state, f"AGGREGATE round={state['round']}", sleep=False)
    return {"round": state["round"] + 1}


def finalize_node(state):
    n = len(_read_branch_state(state["run_dir"])["branches"])
    _marker(state, f"FINALIZE branches_done={n}", sleep=False)
    return {}


# --------------------------------------------------------------------------
# escalation chain (single non-idempotent alert effect)
# --------------------------------------------------------------------------
def esc_claim_node(state):
    eff = escalate_effect()
    key, skip = None, False
    if state["condition"] == "wal":
        log = ClaimLog(os.path.join(state["run_dir"], "claim.log"))
        existing = log.find_by_identity(eff["action"], eff["target"],
                                          eff.get("occurrence", 0))
        if existing is not None:
            key = existing["key"]
            skip = log.is_committed(existing)
        else:
            key = claim_key_v2(state["workflow_id"], 1, "esc", 0,
                               eff["action"])
            occ = log.next_occurrence(eff["action"], eff["target"])
            t0 = time.perf_counter()
            log.append_claim("esc", eff["action"], eff["target"], "v2 esc",
                             key, state["epoch"], occurrence=occ)
            CLAIM_TIMINGS.append(("claim", time.perf_counter() - t0))
    elif state["condition"] in ("deterministic", "native"):
        key = claim_key_v2(state["workflow_id"], 1, "esc", 0, eff["action"])
    elif state["condition"] == "det_content":
        key = content_key_v2(eff["action"], eff["target"])
    _marker(state, f"ESCALATE CLAIM skip={skip}")
    return {"esc_key": key, "esc_skip": skip}


def esc_execute_node(state):
    if state.get("esc_skip"):
        _marker(state, "ESCALATE SKIP", sleep=False)
        return {"esc_status": "skipped"}
    eff = escalate_effect()
    status = _do_tool(state, "esc", eff["action"], eff["target"],
                      state.get("esc_key"))
    _marker(state, f"ESCALATE TOOL_CALLED status={status}")
    return {"esc_status": status}


def esc_commit_node(state):
    if state["condition"] == "wal" and not state.get("esc_skip"):
        log = ClaimLog(os.path.join(state["run_dir"], "claim.log"))
        t0 = time.perf_counter()
        for c in log.claims():
            if c["key"] == state["esc_key"]:
                log.append_commit(c)
                break
        CLAIM_TIMINGS.append(("commit", time.perf_counter() - t0))
    _marker(state, "ESCALATE COMMIT")
    _mark_escalate_done(state["run_dir"])
    return {}


# --------------------------------------------------------------------------
# worker subgraph: claim -> execute -> commit, with retry/backoff loop
# --------------------------------------------------------------------------
def w_claim_node(state):
    eff = state["effects"][state["idx"]]
    uid = claim_uid(state["round"], state["branch"], state["idx"])
    action, target = eff["action"], eff["target"]
    wid = state["workflow_id"]
    cond = state["condition"]
    key, skip = None, False
    if cond == "wal":
        log = ClaimLog(os.path.join(state["run_dir"], "claim.log"))
        # E2b: the business identity is reword-invariant — canonicalize the
        # lookup target so a rephrased retry matches the original claim.
        # canonical_target_v2 is a no-op for non-reworded targets.
        lookup_target = (canonical_target_v2(target)
                         if state.get("reword_recovery") else target)
        existing = log.find_by_identity(action, lookup_target,
                                          eff.get("occurrence", 0))
        if existing is not None:
            # Never re-derive: reuse the durable key. Committed -> skip the
            # effect entirely; uncommitted (should not survive recovery, but
            # be safe) -> re-emit the original key without skipping.
            key = existing["key"]
            skip = log.is_committed(existing)
        else:
            key = claim_key_v2(wid, state["round"], state["branch"],
                               state["idx"], action)
            occ = log.next_occurrence(action, target)
            t0 = time.perf_counter()
            log.append_claim(uid, action, target, f"v2 {uid}", key,
                             state["epoch"], occurrence=occ)
            CLAIM_TIMINGS.append(("claim", time.perf_counter() - t0))
    elif cond in ("deterministic", "native"):
        # native: same durable operation identities as deterministic; the
        # difference is the recovery mechanism (checkpointer resume), not
        # the key derivation.
        key = claim_key_v2(wid, state["round"], state["branch"],
                           state["idx"], action)
    elif cond == "det_shift":
        # E2a: positional keys, but recovery reprioritizes — the positional
        # index used for key derivation (key_branch) differs from fresh.
        kb = state.get("key_branch", state["branch"])
        key = claim_key_v2(wid, state["round"], kb,
                           state["idx"], action)
    elif cond == "det_content":
        # E2b: content-hash keys bind identity to the exact target string;
        # recovery rewording changes the hash.
        key = content_key_v2(action, target)
    _wmarker(state, "CLAIM", f"skip={skip}")
    return {"claim_uid": uid, "claim_key": key, "skip_effect": skip}


def w_execute_node(state):
    if state.get("skip_effect"):
        return {"transient": False, "status": "skipped"}
    eff = state["effects"][state["idx"]]
    attempts = state.get("attempts", 0)
    if is_transient_scripted(state["round"], state["branch"], attempts):
        # Scripted transient failure: the tool is NOT invoked, nothing
        # commits; the graph routes to the real backoff retry.
        _wmarker(state, "TOOL_TRANSIENT", f"attempt={attempts}")
        return {"transient": True, "attempts": attempts + 1}
    uid = state["claim_uid"]
    status = _do_tool(state, uid, eff["action"], eff["target"],
                      state.get("claim_key"))
    _wmarker(state, "TOOL_CALLED", f"status={status} attempt={attempts}")
    return {"transient": False, "status": status,
            "attempts": attempts + 1}


def w_exec_router(state):
    return "retry" if state.get("transient") else "ok"


def w_retry_node(state):
    """Framework-level retry with a REAL backoff sleep. A crash landing
    here is the new 'during retry backoff' window: the claim exists but is
    uncommitted, so wal recovery reconciles it; the baseline has nothing
    to reconcile and simply re-dispatches."""
    _wmarker(state, "RETRY_WAIT", f"attempt={state.get('attempts', 0)}")
    time.sleep(state["retry_backoff_s"])
    return {}


def w_commit_node(state):
    if state.get("skip_effect"):
        _wmarker(state, "SKIP")
        return {}
    if state["condition"] == "wal":
        log = ClaimLog(os.path.join(state["run_dir"], "claim.log"))
        t0 = time.perf_counter()
        for c in log.claims():
            if c["key"] == state["claim_key"]:
                log.append_commit(c)
                break
        CLAIM_TIMINGS.append(("commit", time.perf_counter() - t0))
    # The COMMIT marker (with its chaos sleep) is the mid-fan-out crash
    # window: effect committed, branch not yet marked done. Baseline
    # recovery re-executes here -> duplicate; wal skips via the log.
    _wmarker(state, "COMMIT")
    return {}


def w_next_router(state):
    # w_advance already incremented idx: the next effect exists iff
    # idx is still inside the effects list.
    if state["idx"] < len(state["effects"]):
        return "more"
    return "done"


def w_advance_node(state):
    return {"idx": state["idx"] + 1, "attempts": 0, "skip_effect": False,
            "transient": False, "status": ""}


def w_done_node(state):
    _mark_branch_done(state["run_dir"],
                      branch_key(state["round"], state["branch"]))
    # Dedicated marker (not _wmarker): idx has already advanced past the
    # last effect, so the generic per-effect marker would print a bogus e2.
    _marker(state, "WORKER r{} b{} DONE".format(state["round"],
                                               state["branch"]),
            sleep=False)
    return {"branch_results": [{"round": state["round"],
                                "branch": state["branch"],
                                "effects": len(state["effects"])}]}


def build_worker_subgraph():
    g = StateGraph(WorkerState)
    g.add_node("w_claim", w_claim_node)
    g.add_node("w_execute", w_execute_node)
    g.add_node("w_retry", w_retry_node)
    g.add_node("w_commit", w_commit_node)
    g.add_node("w_advance", w_advance_node)
    g.add_node("w_done", w_done_node)
    g.add_edge(START, "w_claim")
    g.add_edge("w_claim", "w_execute")
    g.add_conditional_edges("w_execute", w_exec_router,
                            {"retry": "w_retry", "ok": "w_commit"})
    g.add_edge("w_retry", "w_execute")
    g.add_edge("w_commit", "w_advance")
    g.add_conditional_edges("w_advance", w_next_router,
                            {"more": "w_claim", "done": "w_done"})
    g.add_edge("w_done", END)
    return g.compile()


_WORKER_SUBGRAPH = build_worker_subgraph()


def worker_sub_node(packet):
    """Send target: runs the compiled worker subgraph on one branch packet
    and returns ONLY the fan-in key. Returning the subgraph's full state
    would concurrently write every shared key from N parallel branches
    (InvalidUpdateError); the reducer key is the entire cross-boundary
    contract, which is also the honest delegate shape (results out, not
    internal worker state)."""
    wstate = {
        "workflow_id": packet["workflow_id"],
        "run_dir": packet["run_dir"],
        "condition": packet["condition"],
        "epoch": packet["epoch"],
        "server_url": packet["server_url"],
        "marker_sleep_ms": packet["marker_sleep_ms"],
        "retry_backoff_s": packet["retry_backoff_s"],
        "round": packet["round"],
        "branch": packet["branch"],
        "effects": packet["effects"],
        "idx": 0,
        "attempts": 0,
        "transient": False,
        "skip_effect": False,
    }
    # E2: identity-shift bookkeeping crosses the Send boundary explicitly.
    if "key_branch" in packet:
        wstate["key_branch"] = packet["key_branch"]
    if packet.get("reword_recovery"):
        wstate["reword_recovery"] = True
    final = _WORKER_SUBGRAPH.invoke(wstate,
                                    config={"recursion_limit": 1000})
    return {"branch_results": final.get("branch_results", [])}


# --------------------------------------------------------------------------
# main graph assembly
# --------------------------------------------------------------------------
def entry_router(state):
    return "recover" if state["mode"] == "recover" else "fresh"


def build_graph_v2():
    g = StateGraph(AgentStateV2)
    g.add_node("plan", plan_node)
    g.add_node("recover", recover_node)
    g.add_node("supervisor", supervisor_node)
    g.add_node("dispatch", dispatch_node)
    g.add_node("worker_sub", worker_sub_node)
    g.add_node("aggregate", aggregate_node)
    g.add_node("esc_claim", esc_claim_node)
    g.add_node("esc_execute", esc_execute_node)
    g.add_node("esc_commit", esc_commit_node)
    g.add_node("finalize", finalize_node)

    g.add_conditional_edges(START, entry_router,
                            {"fresh": "plan", "recover": "recover"})
    g.add_edge("plan", "supervisor")
    g.add_edge("recover", "supervisor")
    g.add_conditional_edges("supervisor", sup_router,
                            {"fan_out": "dispatch",
                             "escalate": "esc_claim",
                             "done": "finalize"})
    g.add_conditional_edges("dispatch", dispatch_router,
                            {"aggregate": "aggregate"})
    # Send fan-out: each packet enters the worker subgraph; all completions
    # merge back and flow once to aggregate (fan-in).
    g.add_edge("worker_sub", "aggregate")
    g.add_edge("aggregate", "supervisor")
    g.add_edge("esc_claim", "esc_execute")
    g.add_edge("esc_execute", "esc_commit")
    g.add_edge("esc_commit", "aggregate")
    g.add_edge("finalize", END)
    return g.compile()
