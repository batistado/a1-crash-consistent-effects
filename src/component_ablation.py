#!/usr/bin/env python3
"""A1 component ablation: is each piece of the crash-consistency protocol load-bearing?

Derived from src/sandbox.py -- it imports sandbox's pure helpers
(make_plan, reword_args, key-derivation fns, fault probabilities) so the
stochastic model is identical, and re-implements only the harness/tool
plumbing needed for the ablation conditions and the new zombie fault.

Conditions (1,500 episodes each, seeded RNG, $0):
  full         the full protocol as-is: write-ahead claim log + log-fenced
               checkpoints + epoch fencing  (== sandbox.py condition (iii))
  no_fencing   claim log + log-fenced checkpoints kept; epoch fencing REMOVED
               (the tool accepts calls with any/old epoch)
  no_log       epoch fencing kept; claim log REMOVED -- recovery falls back
               to deterministic position keys re-derived by the agent
               (== sandbox.py condition (ii-b) mechanism)
  neither      no log, no fencing, no keys (== sandbox.py baseline (i))

Fault model: two independent fault dimensions, applied uniformly to every
condition (faults are the treatment-invariant part of the experiment).
  F1  checkpoint-window crash: same landing distribution as sandbox.py --
      75% in-window (after tool commit, before checkpoint write),
      15% post-checkpoint (safe), 10% pre-tool-call (safe).
  F2  writer-zombie: with probability P_ZOMBIE the pre-crash harness process
      instance *survives* the crash and, AFTER recovery has begun with a new
      epoch, retries the in-flight step with its OLD epoch. The zombie
      re-derives the call the way a stale at-least-once agent would: a fresh
      content-hash key over its (possibly reworded) args -- a key from a
      keyspace the new generation never saw. The tool's idempotency check
      cannot suppress it (unseen key); only the epoch fence can reject it.
      This is the precise stale-writer hazard fencing tokens exist for.
        - fencing on  (full, no_log): FencedError -> counted zombie_fenced
        - fencing off (no_fencing, neither): accepted, commits -> exactly one
          semantic duplicate of the in-flight effect -> counted zombie_committed

Ground-truth scoring is the same semantic, reword-invariant rule as
sandbox.py: duplicates are committed effects beyond the intended count per
(action, target/record) identity.

Stdlib only. No network, no LLM calls, $0 compute.
"""

import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox import (
    FencedError,
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
RESULTS = ROOT / "component_ablation_results.json"

SEED = 20261009
EPISODES_PER_CONDITION = 1500

# F2 writer-zombie fault: fraction of crashed episodes where the pre-crash
# process instance survives and retries with a stale epoch after recovery.
P_ZOMBIE = 0.5


class ToolServer:
    """Same atomic idempotent receiver as sandbox.py, plus an explicit
    fencing_enabled switch: with fencing off, the tool accepts calls bearing
    any (even stale) epoch -- the fence_epoch registration is skipped too."""

    def __init__(self, fencing_enabled=True):
        self.ledger = []          # durable: every committed effect, append-only
        self.seen_keys = {}       # durable: workflow_id -> set of seen keys
        self.max_epoch = {}       # durable: per-workflow fencing epoch
        self.fenced_rejections = 0
        self.fencing_enabled = fencing_enabled

    def _seen(self, workflow_id):
        return self.seen_keys.setdefault(workflow_id, set())

    def fence_epoch(self, workflow_id, epoch):
        if not self.fencing_enabled:
            return
        self.max_epoch[workflow_id] = max(
            self.max_epoch.get(workflow_id, 0), epoch)

    def call(self, workflow_id, step_uid, action, args, key, epoch):
        if self.fencing_enabled and epoch < self.max_epoch.get(workflow_id, 0):
            self.fenced_rejections += 1
            raise FencedError(f"stale epoch {epoch} for {workflow_id}")
        self.max_epoch[workflow_id] = max(self.max_epoch.get(workflow_id, 0), epoch)
        seen = self._seen(workflow_id)
        if key is not None and key in seen:
            return {"status": "duplicate_suppressed", "key": key}
        # atomic check-and-commit
        self.ledger.append({
            "workflow_id": workflow_id,
            "step_uid": step_uid,
            "action": action,
            "args": args,
            "key": key,
        })
        if key is not None:
            seen.add(key)
        return {"status": "committed", "key": key}


def run_episode(rng, tool, condition):
    """Run one episode. `condition` in {'full','no_fencing','no_log','neither'}."""
    use_log = condition in ("full", "no_fencing")
    use_fencing = condition in ("full", "no_log")

    workflow_id = f"wf-{rng.randint(0, 1 << 60):016x}"
    plan = make_plan(rng)
    effectful = [s for s in plan if s["action"] != READ_ACTION]
    crash_step = rng.choice(effectful)  # step_uid where the F1 crash strikes
    r = rng.random()
    if r < P_IN_WINDOW:
        landing = "in_window"
    elif r < P_IN_WINDOW + P_POST_CHECKPOINT:
        landing = "post_checkpoint"
    else:
        landing = "pre_step"

    # ---- durable state (survives the crash) ----
    checkpoint = -1
    wal = []                   # durable write-ahead log (log conditions only)
    epoch = 0

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
    zombie_fenced = 0
    zombie_committed = 0

    def execute_step(step, key_fn):
        """Execute one effectful step. Returns True if a crash was injected."""
        nonlocal checkpoint, crashed
        action, args = step["action"], step["args"]
        uid = step["uid"]
        if use_log:
            claim = find_claim(action, args)
            if claim is None:
                key = deterministic_key(workflow_id, uid, action)
                durable_claim(uid, action, args, key)
                claim = wal[-1]
            elif claim["committed"]:
                if uid > checkpoint:
                    checkpoint = uid
                return False  # already done; skip
            key = claim["key"]
        else:
            key = key_fn(uid, action, args) if key_fn else None

        is_crash_step = (uid == crash_step["uid"])
        pre_step_crash = is_crash_step and landing == "pre_step" and not crashed
        if pre_step_crash:
            crashed = True
            return True

        tool.call(workflow_id, uid, action, args, key, epoch)

        in_window_crash = is_crash_step and landing == "in_window" and not crashed
        if in_window_crash:
            crashed = True
            return True

        if use_log:
            claim["committed"] = True
        checkpoint = uid

        post_crash = is_crash_step and landing == "post_checkpoint" and not crashed
        if post_crash:
            crashed = True
            return True
        return False

    def key_fn(uid, action, args):
        # 'no_log' falls back to deterministic position keys re-derived by the
        # agent (same mechanism as sandbox.py condition (ii-b));
        # 'neither' uses no keys at all (== sandbox.py baseline (i)).
        if condition == "no_log":
            return deterministic_key(workflow_id, uid, action)
        return None

    # ---- first attempt ----
    for step in plan:
        if step["action"] == READ_ACTION:
            continue
        if execute_step(step, key_fn):
            break

    # ---- recovery ----
    if crashed:
        epoch += 1  # new fencing epoch
        if use_fencing:
            tool.fence_epoch(workflow_id, epoch)
        if use_log:
            for claim in wal:
                if not claim["committed"]:
                    try:
                        res = tool.call(workflow_id, claim["step_uid"],
                                        claim["action"], claim["args"],
                                        claim["key"], epoch)
                    except FencedError:
                        res = {"status": "fenced"}
                    if res["status"] in ("committed", "duplicate_suppressed"):
                        claim["committed"] = True
            done = [c["step_uid"] for c in wal if c["committed"]]
            if done:
                checkpoint = max(checkpoint, max(done))

        # the recovered agent replans from the checkpoint (with nondeterminism)
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
            rstep = {"uid": step["uid"], "action": step["action"], "args": args}
            execute_step(rstep, key_fn)

        # ---- F2 writer-zombie: the pre-crash process instance survived and,
        # AFTER recovery began with the new epoch, retries the in-flight step
        # with its OLD epoch and a freshly derived (unseen) key ----
        if rng.random() < P_ZOMBIE:
            z_args = dict(crash_step["args"])
            if rng.random() < P_REWORD_ARGS:
                z_args = reword_args(z_args)
            z_key = content_hash_key(crash_step["action"], z_args)
            try:
                zres = tool.call(workflow_id, crash_step["uid"],
                                 crash_step["action"], z_args, z_key, epoch - 1)
                if zres["status"] == "committed":
                    zombie_committed = 1
            except FencedError:
                zombie_fenced = 1

    # ---- scoring against ground truth (same semantic rule as sandbox.py) ----
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
    missing = sum(max(0, c - committed_counts.get(sig, 0))
                  for sig, c in intended_counts.items())
    return {
        "landing": landing,
        "crashed": crashed,
        "duplicates": duplicates,
        "missing": missing,
        "exactly_once": (duplicates == 0 and missing == 0),
        "zombie_fenced": zombie_fenced,
        "zombie_committed": zombie_committed,
    }


def main():
    t0 = time.time()
    rng = random.Random(SEED)
    conditions = ["full", "no_fencing", "no_log", "neither"]
    summary = {
        "seed": SEED,
        "episodes_per_condition": EPISODES_PER_CONDITION,
        "p_in_window": P_IN_WINDOW,
        "p_post_checkpoint": P_POST_CHECKPOINT,
        "p_reword_args": P_REWORD_ARGS,
        "p_plan_shift": P_PLAN_SHIFT,
        "p_zombie": P_ZOMBIE,
        "conditions": {},
    }
    for cond in conditions:
        fencing_on = cond in ("full", "no_log")
        tool = ToolServer(fencing_enabled=fencing_on)
        n = EPISODES_PER_CONDITION
        dup_eps = 0
        eo = 0
        tot_dup = 0
        tot_missing = 0
        z_fenced = 0
        z_committed = 0
        landings = {}
        for _ in range(n):
            res = run_episode(rng, tool, cond)
            landings[res["landing"]] = landings.get(res["landing"], 0) + 1
            if res["duplicates"] > 0:
                dup_eps += 1
            if res["exactly_once"]:
                eo += 1
            tot_dup += res["duplicates"]
            tot_missing += res["missing"]
            z_fenced += res["zombie_fenced"]
            z_committed += res["zombie_committed"]
        summary["conditions"][cond] = {
            "episodes": n,
            "duplicate_effect_rate": round(dup_eps / n, 4),
            "exactly_once_rate": round(eo / n, 4),
            "mean_duplicates_per_episode": round(tot_dup / n, 4),
            "mean_missing_per_episode": round(tot_missing / n, 4),
            "episodes_with_duplicates": dup_eps,
            "zombie_probes_fenced": z_fenced,
            "zombie_probes_committed": z_committed,
            "tool_fenced_rejections": tool.fenced_rejections,
            "crash_landings": landings,
        }
        print(f"[{cond}] dup_rate={dup_eps / n:.4f} "
              f"exactly_once={eo / n:.4f} mean_dup/ep={tot_dup / n:.4f} "
              f"zombie_fenced={z_fenced} zombie_committed={z_committed}",
              flush=True)

    summary["elapsed_seconds"] = round(time.time() - t0, 1)
    with open(RESULTS, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"wrote {RESULTS} in {summary['elapsed_seconds']}s")


if __name__ == "__main__":
    sys.exit(main())
