#!/usr/bin/env python3
"""E4: Fencing trace analysis — instrumented no_fencing re-run.

Reviewer ask (§4): "Show an offending trace with the claim identity, key,
epoch, and receiver decision. Separate delayed same-key requests from
surviving writers that create fresh work."

Runs the sandbox `no_fencing` condition (claim log kept, epoch fencing
REMOVED) with per-call instrumentation. Every tool.call is logged as
(caller, workflow_id, step_uid, action, target-signature, key, epoch,
result). For each duplicate episode, the offending call is classified:
  (a) same key as a prior commit (delayed same-key retry)
  (b) fresh key never seen before (surviving-writer fresh claim)

Stdlib only. $0.
"""
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from component_ablation import ToolServer, P_ZOMBIE
from sandbox import (
    content_hash_key,
    deterministic_key,
    reword_args,
    make_plan,
    READ_ACTION,
    P_IN_WINDOW,
    P_POST_CHECKPOINT,
    P_REWORD_ARGS,
    P_PLAN_SHIFT,
)

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results_e4_fencing_trace.json"

SEED = 20261010
EPISODES = 200


class TracingToolServer(ToolServer):
    """ToolServer with fencing disabled + per-call trace log."""

    def __init__(self):
        super().__init__(fencing_enabled=False)
        self.calls = []  # (caller, wid, step_uid, action, sig, key, epoch, result)

    def call(self, workflow_id, step_uid, action, args, key, epoch,
             caller="fresh"):
        sig = (action, args.get("target"), args.get("record"))
        try:
            res = super().call(workflow_id, step_uid, action, args, key, epoch)
            result = res["status"]
        except Exception as e:  # noqa: BLE001
            result = f"EXC:{type(e).__name__}"
            raise
        finally:
            # record even on exception paths
            pass
        self.calls.append({
            "caller": caller,
            "workflow_id": workflow_id,
            "step_uid": step_uid,
            "action": action,
            "sig": list(sig),
            "key": key,
            "epoch": epoch,
            "result": result,
        })
        return res


def run_episode_traced(rng, tool, episode_idx):
    """Mirror of component_ablation.run_episode for 'no_fencing', with the
    tool calls tagged by caller (fresh / recovery / zombie). Returns
    (result_dict, calls_for_this_episode)."""
    # import the episode runner and monkeypatch its tool usage is complex;
    # instead re-implement the no_fencing episode here with caller tags.
    from component_ablation import run_episode as _run  # noqa
    # We reimplement to tag callers. Keep the RNG stream identical by
    # replicating run_episode's draws in order.
    workflow_id = f"wf-{rng.randint(0, 1 << 60):016x}"
    plan = make_plan(rng)
    effectful = [s for s in plan if s["action"] != READ_ACTION]
    crash_step = rng.choice(effectful)
    r = rng.random()
    if r < P_IN_WINDOW:
        landing = "in_window"
    elif r < P_IN_WINDOW + P_POST_CHECKPOINT:
        landing = "post_checkpoint"
    else:
        landing = "pre_step"

    checkpoint = -1
    wal = []
    epoch = 0
    call_base = len(tool.calls)

    def durable_claim(step_uid, action, args, key):
        wal.append({"workflow_id": workflow_id, "step_uid": step_uid,
                    "action": action, "args": args, "key": key,
                    "epoch": epoch, "committed": False})

    def claim_identity(action, args):
        return (action, args.get("target"), args.get("record"))

    def find_claim(action, args):
        ident = claim_identity(action, args)
        for c in wal:
            if claim_identity(c["action"], c["args"]) == ident:
                return c
        return None

    crashed = False
    zombie_committed = 0

    def execute_step(step, caller):
        nonlocal checkpoint, crashed
        action, args = step["action"], step["args"]
        uid = step["uid"]
        claim = find_claim(action, args)
        if claim is None:
            key = deterministic_key(workflow_id, uid, action)
            durable_claim(uid, action, args, key)
            claim = wal[-1]
        elif claim["committed"]:
            if uid > checkpoint:
                checkpoint = uid
            return False
        key = claim["key"]

        is_crash_step = (uid == crash_step["uid"])
        if is_crash_step and landing == "pre_step" and not crashed:
            crashed = True
            return True

        tool.call(workflow_id, uid, action, args, key, epoch, caller=caller)

        if is_crash_step and landing == "in_window" and not crashed:
            crashed = True
            return True

        claim["committed"] = True
        checkpoint = uid

        if is_crash_step and landing == "post_checkpoint" and not crashed:
            crashed = True
            return True
        return False

    for step in plan:
        if step["action"] == READ_ACTION:
            continue
        if execute_step(step, "fresh"):
            break

    if crashed:
        epoch += 1  # new fencing epoch (no fence_epoch: fencing disabled)
        for claim in wal:
            if not claim["committed"]:
                res = tool.call(workflow_id, claim["step_uid"],
                                claim["action"], claim["args"],
                                claim["key"], epoch, caller="recovery")
                if res["status"] in ("committed", "duplicate_suppressed"):
                    claim["committed"] = True
        done = [c["step_uid"] for c in wal if c["committed"]]
        if done:
            checkpoint = max(checkpoint, max(done))

        resume_plan = [s for s in plan if s["uid"] > checkpoint]
        shift = rng.random() < P_PLAN_SHIFT
        if shift:
            shifted = []
            for s in resume_plan:
                ns = dict(s)
                ns["uid"] = s["uid"] + 1
                shifted.append(ns)
            resume_plan = shifted
        reword = rng.random() < P_REWORD_ARGS
        for step in resume_plan:
            if step["action"] == READ_ACTION:
                continue
            args = reword_args(step["args"]) if reword else step["args"]
            rstep = {"uid": step["uid"], "action": step["action"],
                     "args": args}
            execute_step(rstep, "recovery")

        if rng.random() < P_ZOMBIE:
            z_args = dict(crash_step["args"])
            if rng.random() < P_REWORD_ARGS:
                z_args = reword_args(z_args)
            z_key = content_hash_key(crash_step["action"], z_args)
            zres = tool.call(workflow_id, crash_step["uid"],
                             crash_step["action"], z_args, z_key, epoch - 1,
                             caller="zombie")
            if zres["status"] == "committed":
                zombie_committed = 1

    def sig_of(action, args):
        return (action, args.get("target"), args.get("record"))

    intended_counts = {}
    for s in effectful:
        sig = sig_of(s["action"], s["args"])
        intended_counts[sig] = intended_counts.get(sig, 0) + 1
    committed_counts = {}
    for e in tool.ledger:
        if e["workflow_id"] != workflow_id:
            continue
        sig = sig_of(e["action"], e["args"])
        committed_counts[sig] = committed_counts.get(sig, 0) + 1
    duplicates = sum(max(0, committed_counts.get(sig, 0) - c)
                     for sig, c in intended_counts.items())
    duplicates += sum(c for sig, c in committed_counts.items()
                      if sig not in intended_counts)

    calls = tool.calls[call_base:]
    return {
        "episode": episode_idx,
        "workflow_id": workflow_id,
        "landing": landing,
        "crashed": crashed,
        "duplicates": duplicates,
        "zombie_committed": zombie_committed,
    }, calls


def classify_duplicates(episode_rec, calls):
    """For each duplicate episode, find the offending call(s) and classify
    (a) same-key retry vs (b) fresh-key zombie."""
    wid = episode_rec["workflow_id"]
    # committed keys in order
    seen = {}
    offending = []
    for c in calls:
        if c["result"] != "committed":
            continue
        key = c["key"]
        sig = tuple(c["sig"])
        if key in seen:
            # same key committed twice — should not happen (idempotent)
            offending.append({**c, "class": "a-same-key-recommit",
                              "prior": seen[key]})
        else:
            # check if this is a semantic duplicate: same sig already committed
            for k2, prior in seen.items():
                if tuple(prior["sig"]) == sig:
                    # same semantic effect, different key
                    cls = ("b-fresh-key-zombie" if c["caller"] == "zombie"
                           else "b-fresh-key-other")
                    offending.append({**c, "class": cls, "prior": prior})
                    break
            seen[key] = c
    return offending


def main():
    t0 = time.time()
    rng = random.Random(SEED)
    tool = TracingToolServer()
    dup_episodes = 0
    class_counts = {"a-same-key-recommit": 0, "b-fresh-key-zombie": 0,
                    "b-fresh-key-other": 0}
    worked_example = None
    total_offending = 0

    for i in range(EPISODES):
        rec, calls = run_episode_traced(rng, tool, i)
        if rec["duplicates"] > 0:
            dup_episodes += 1
            off = classify_duplicates(rec, calls)
            total_offending += len(off)
            for o in off:
                class_counts[o["class"]] = class_counts.get(o["class"], 0) + 1
            if worked_example is None and off:
                # prefer a clean single-offense zombie case
                z = [o for o in off if o["class"] == "b-fresh-key-zombie"]
                if z:
                    worked_example = {
                        "episode": rec["episode"],
                        "workflow_id": rec["workflow_id"],
                        "landing": rec["landing"],
                        "full_call_sequence": [
                            {k: c[k] for k in
                             ("caller", "step_uid", "action", "sig", "key",
                              "epoch", "result")}
                            for c in calls],
                        "offending": z[0],
                    }

    summary = {
        "seed": SEED,
        "episodes": EPISODES,
        "condition": "no_fencing (claim log kept, epoch fencing removed)",
        "episodes_with_duplicates": dup_episodes,
        "duplicate_episode_rate": round(dup_episodes / EPISODES, 4),
        "offending_call_classes": class_counts,
        "total_offending_calls": total_offending,
        "worked_example": worked_example,
        "elapsed_s": round(time.time() - t0, 1),
    }
    with open(RESULTS, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"episodes={EPISODES} dup_episodes={dup_episodes} "
          f"classes={class_counts}")
    if worked_example:
        o = worked_example["offending"]
        p = o["prior"]
        print(f"worked example ep={worked_example['episode']} "
              f"landing={worked_example['landing']}")
        print(f"  prior : caller={p['caller']} key={p['key'][:24]}... "
              f"epoch={p['epoch']} result={p['result']}")
        print(f"  zombie: caller={o['caller']} key={o['key'][:24]}... "
              f"epoch={o['epoch']} result={o['result']} class={o['class']}")
    print(f"wrote {RESULTS}")


if __name__ == "__main__":
    sys.exit(main())
