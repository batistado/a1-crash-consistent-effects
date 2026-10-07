#!/usr/bin/env python3
"""A1 scripted sandbox: crash-consistent checkpointing for exactly-once agent effects.

Fault model (benign chaos-style fault injection, like HPC checkpoint/restart
studies -- NOT security/adversarial; there is no attacker here):
  * A scripted agent executes a multi-step workflow against MOCKED tools.
  * At a randomized point the harness *process* crashes: all in-memory agent
    state is discarded; only durable state (checkpoints, and -- in condition
    (iii) -- the write-ahead effect-claim log) survives. The agent then resumes
    from the last checkpoint.
  * The critical fault is a crash landing IN THE WINDOW between a tool-effect
    commit and the harness checkpoint write ("double refund" window).

Conditions:
  (i)    baseline: resume-from-checkpoint, no idempotency keys.
  (ii-a) + idempotency keys, content-hash derived: key = sha256(action, args).
         Reproduces the known failure: if the recovered agent rewords the
         arguments on retry, the key changes and the tool cannot dedup.
  (ii-b) + idempotency keys, deterministic: key = (workflow_id, step_index,
         action_type). Immune to rewording, but fragile to replan-structure
         changes: if the recovered agent's plan shifts step indices (e.g. it
         inserts a diagnostic read after recovery), the re-derived key misses.
  (iii)  + write-ahead effect-claim log: the harness durably logs (claim, key)
         BEFORE invoking the tool; checkpoints are fenced by the log (a
         checkpoint only advances past a log COMMIT); recovery reconciles
         against the log first, replaying each uncommitted claim with its
         ORIGINAL key (independent of how the agent re-derives keys); and a
         fencing epoch rejects calls from stale (pre-crash) writers.

The tool is modeled as an atomic idempotent receiver (check-and-commit are
atomic), the same assumption LIMBO's analysis uses for the tool contract.
Ground truth for duplicates is the append-only effect ledger: a duplicate is
any effectful step whose effect is committed more than once.

Stdlib only. No network, no LLM calls, $0 compute.
"""

import hashlib
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results.json"

SEED = 20261007
EPISODES_PER_CONDITION = 1500

# Crash-landing distribution: fraction of crashes that strike in the
# commit->checkpoint window vs. at safe points.
P_IN_WINDOW = 0.75
P_POST_CHECKPOINT = 0.15  # remainder -> pre-step (safe: effect never committed)

# Recovery replanning nondeterminism (models LLM re-synthesis after restore).
P_REWORD_ARGS = 0.50   # recovered agent rewords args of the retried step
P_PLAN_SHIFT = 0.30    # recovered agent inserts a diagnostic read, shifting indices

EFFECTFUL_ACTIONS = ["issue_refund", "send_email", "update_record"]
READ_ACTION = "read_record"


class FencedError(Exception):
    """Raised when a tool call carries a stale fencing epoch."""


class ToolServer:
    """Mocked external tools. The effect ledger is the durable 'real world':
    it survives harness-process crashes. `seen_keys` makes the tool an atomic
    idempotent receiver: if the key was seen, the effect is NOT re-committed.

    Idempotency keys are scoped per workflow (the realistic model: keys are
    issued per client/workflow). Without scoping, identical (action, args)
    across unrelated workflows would collide -- a real hazard of unscoped
    content-hash keys, but a different failure mode from the one under test,
    so it is deliberately excluded here (see DESIGN.md)."""

    def __init__(self):
        self.ledger = []          # durable: every committed effect, append-only
        self.seen_keys = {}       # durable: workflow_id -> set of seen keys
        self.max_epoch = {}       # durable: per-workflow fencing epoch
        self.fenced_rejections = 0

    def _seen(self, workflow_id):
        return self.seen_keys.setdefault(workflow_id, set())

    def fence_epoch(self, workflow_id, epoch):
        """Recovery announces a new authoritative generation for a workflow
        (cf. fencing-token registration). Calls bearing an older epoch are
        stale writers and will be rejected from now on."""
        self.max_epoch[workflow_id] = max(
            self.max_epoch.get(workflow_id, 0), epoch)

    def call(self, workflow_id, step_uid, action, args, key, epoch):
        if epoch < self.max_epoch.get(workflow_id, 0):
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


def content_hash_key(action, args):
    h = hashlib.sha256()
    h.update(action.encode())
    h.update(json.dumps(args, sort_keys=True).encode())
    return "ch:" + h.hexdigest()[:32]


def deterministic_key(workflow_id, step_index, action):
    return f"det:{workflow_id}:{step_index}:{action}"


def reword_args(args):
    """Simulate the recovered agent rewording arguments on retry.

    Only the cosmetic 'note' payload is reworded -- the stable identity
    fields ('target'/'record') never change, because a reworded retry of the
    same intended effect is still ONE logical effect. (Rewording the identity
    would make the retry a genuinely different effect, which would corrupt
    the ground-truth scoring.)
    """
    out = dict(args)
    if isinstance(out.get("note"), str) and out["note"]:
        out["note"] = out["note"] + " (revised after recovery)"
    return out


def make_plan(rng):
    n = rng.randint(4, 8)
    plan = []
    for i in range(n):
        if rng.random() < 0.6:
            action = rng.choice(EFFECTFUL_ACTIONS)
            # target is unique per step: claim identity (action, target) can
            # never collide between two distinct intended steps in one plan.
            args = {"target": f"customer-{rng.randint(1000, 9999)}-s{i}",
                    "note": f"step {i} payload"}
        else:
            action = READ_ACTION
            args = {"record": f"rec-{rng.randint(100, 999)}"}
        plan.append({"uid": i, "action": action, "args": args})
    # guarantee at least 2 effectful steps so the crash fault is meaningful
    eff = [s for s in plan if s["action"] != READ_ACTION]
    if len(eff) < 2:
        for s in plan[:2]:
            s["action"] = rng.choice(EFFECTFUL_ACTIONS)
            s["args"] = {"target": f"customer-{rng.randint(1000, 9999)}-s{s['uid']}",
                         "note": f"step {s['uid']} payload"}
    return plan


def run_episode(rng, tool, condition):
    """Run one episode. Returns a result dict. `condition` in
    {'baseline', 'content_hash', 'deterministic', 'wal'}."""
    workflow_id = f"wf-{rng.randint(0, 1 << 60):016x}"
    plan = make_plan(rng)
    effectful = [s for s in plan if s["action"] != READ_ACTION]
    crash_step = rng.choice(effectful)  # step_uid where the crash strikes
    r = rng.random()
    if r < P_IN_WINDOW:
        landing = "in_window"        # after commit, before checkpoint write
    elif r < P_IN_WINDOW + P_POST_CHECKPOINT:
        landing = "post_checkpoint"  # after checkpoint write (safe)
    else:
        landing = "pre_step"         # before the tool call (safe)

    # ---- durable state (survives the crash) ----
    checkpoint = -1            # last completed step index (durable)
    wal = []                   # durable write-ahead log (condition 'wal' only)
    epoch = 0

    def durable_claim(step_uid, action, args, key):
        wal.append({"workflow_id": workflow_id, "step_uid": step_uid,
                    "action": action, "args": args, "key": key,
                    "epoch": epoch, "committed": False})

    def claim_identity(action, args):
        # Claims are matched on the stable business identity of the effect
        # (action + target), not the full payload: a real reconciler must
        # recognize a reworded retry of the same intended effect. This is the
        # architectural difference under test: the durable claim log lets the
        # harness reconcile semantically, while keys alone force all identity
        # into the key presented at call time.
        return (action, args.get("target"), args.get("record"))

    def find_claim(action, args):
        ident = claim_identity(action, args)
        for c in wal:
            if claim_identity(c["action"], c["args"]) == ident:
                return c
        return None

    crashed = False
    zombie_probes_fenced = 0

    def execute_step(step, step_index, key_fn):
        """Execute one effectful step. Returns True if a crash was injected."""
        nonlocal checkpoint, crashed
        action, args = step["action"], step["args"]
        uid = step["uid"]
        if condition == "wal":
            claim = find_claim(action, args)
            if claim is None:
                key = deterministic_key(workflow_id, uid, action)
                durable_claim(uid, action, args, key)
                claim = wal[-1]
            elif claim["committed"]:
                if uid > checkpoint:
                    checkpoint = uid
                return False  # already done; skip
            # else: uncommitted claim exists -> replay it below with live epoch
            key = claim["key"]
        else:
            key = key_fn(uid, action, args) if key_fn else None

        is_crash_step = (uid == crash_step["uid"])
        pre_step_crash = is_crash_step and landing == "pre_step" and not crashed
        if pre_step_crash:
            crashed = True
            return True  # crash before the tool call; effect never committed

        # --- invoke the tool (the effect COMMITS here) ---
        # Always called with the live fencing epoch: a resumed generation
        # replays with the new epoch, so the tool never fences a legitimate
        # retry; only genuinely stale (pre-crash) writers are rejected.
        tool.call(workflow_id, uid, action, args, key, epoch)

        in_window_crash = is_crash_step and landing == "in_window" and not crashed
        if in_window_crash:
            crashed = True
            return True  # crash in the window: commit happened, checkpoint not written

        # --- durable commit markers (checkpoint write happens here) ---
        if condition == "wal":
            claim["committed"] = True
        checkpoint = uid

        post_crash = is_crash_step and landing == "post_checkpoint" and not crashed
        if post_crash:
            crashed = True
            return True
        return False

    def key_fn(uid, action, args):
        if condition == "content_hash":
            return content_hash_key(action, args)
        if condition == "deterministic":
            return deterministic_key(workflow_id, uid, action)
        return None

    # ---- first attempt: execute the plan in order ----
    for step in plan:
        if step["action"] == READ_ACTION:
            continue
        if execute_step(step, step["uid"], key_fn):
            break

    # ---- recovery: the process "restarts"; only durable state survives ----
    if crashed:
        epoch += 1  # new fencing epoch; stale writers are now fenced
        if condition == "wal":
            # Fence acquisition: the new generation registers its epoch with
            # the tool BEFORE doing anything else, so any in-flight call
            # from the dead (pre-crash) generation is henceforth stale.
            tool.fence_epoch(workflow_id, epoch)
            # zombie probe: the dead process tries one more call with old epoch.
            # The probe key is unique per workflow so each probe is a genuine
            # fencing test (a reused key would be idempotency-suppressed, not
            # fenced, and would not exercise the fence).
            try:
                tool.call(workflow_id, "zombie", "issue_refund",
                          {"target": "zombie"},
                          f"zombie-key-{workflow_id}", epoch - 1)
            except FencedError:
                zombie_probes_fenced = 1
            # reconcile: replay every uncommitted claim with its ORIGINAL key
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
            # checkpoint is fenced by the log: advance past reconciled claims
            done = [c["step_uid"] for c in wal if c["committed"]]
            if done:
                checkpoint = max(checkpoint, max(done))

        # the recovered agent replans from the checkpoint (with nondeterminism)
        resume_plan = [s for s in plan if s["uid"] > checkpoint]
        shift = rng.random() < P_PLAN_SHIFT
        if shift:
            # agent inserts a diagnostic read; subsequent step indices shift +1
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
            execute_step(rstep, step["uid"],
                         key_fn if condition != "wal" else None)
            # note: in 'wal', execute_step ignores key_fn and reconciles via log

    # ---- scoring against ground truth ----
    # Ground truth is semantic AND reword-invariant: the multiset of intended
    # effects from the ORIGINAL plan vs. the multiset actually committed to
    # the ledger, identified by (action, target/record) -- the stable business
    # identity of each effect. The rewordable "note" fluff is excluded on
    # purpose: a reworded retry of the same intended effect is still ONE
    # logical effect (this is exactly what content-hash keys get wrong, and
    # the metric must not punish the retry itself -- only true double
    # commits). A duplicate is any committed effect beyond the intended
    # count for its identity. This single rule covers both same-key replays
    # and shifted-index replays, with no double counting.
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
                      if sig not in intended_counts)  # wholly unintended effects
    missing = sum(max(0, c - committed_counts.get(sig, 0))
                  for sig, c in intended_counts.items())
    return {
        "landing": landing,
        "crashed": crashed,
        "duplicates": duplicates,
        "missing": missing,
        "exactly_once": (duplicates == 0 and missing == 0),
        "zombie_probes_fenced": zombie_probes_fenced,
    }


def main():
    t0 = time.time()
    rng = random.Random(SEED)
    conditions = ["baseline", "content_hash", "deterministic", "wal"]
    summary = {
        "seed": SEED,
        "episodes_per_condition": EPISODES_PER_CONDITION,
        "p_in_window": P_IN_WINDOW,
        "p_post_checkpoint": P_POST_CHECKPOINT,
        "p_reword_args": P_REWORD_ARGS,
        "p_plan_shift": P_PLAN_SHIFT,
        "conditions": {},
    }
    landings_total = {}
    for cond in conditions:
        tool = ToolServer()  # fresh tool/ledger per condition
        n = EPISODES_PER_CONDITION
        dup_eps = 0
        eo = 0
        tot_dup = 0
        tot_missing = 0
        fenced = 0
        landings = {}
        for _ in range(n):
            res = run_episode(rng, tool, cond)
            landings[res["landing"]] = landings.get(res["landing"], 0) + 1
            landings_total[res["landing"]] = landings_total.get(res["landing"], 0) + 1
            if res["duplicates"] > 0:
                dup_eps += 1
            if res["exactly_once"]:
                eo += 1
            tot_dup += res["duplicates"]
            tot_missing += res["missing"]
            fenced += res["zombie_probes_fenced"]
        summary["conditions"][cond] = {
            "episodes": n,
            "duplicate_effect_rate": round(dup_eps / n, 4),
            "exactly_once_rate": round(eo / n, 4),
            "mean_duplicates_per_episode": round(tot_dup / n, 4),
            "mean_missing_per_episode": round(tot_missing / n, 4),
            "episodes_with_duplicates": dup_eps,
            "zombie_probes_fenced": fenced,
            "crash_landings": landings,
        }
        print(f"[{cond}] dup_rate={dup_eps / n:.4f} "
              f"exactly_once={eo / n:.4f} mean_dup/ep={tot_dup / n:.4f} "
              f"fenced={fenced}", flush=True)

    total_eps = sum(landings_total.values())
    summary["crash_landing_fractions_overall"] = {
        k: round(v / total_eps, 4) for k, v in landings_total.items()
    }
    summary["elapsed_seconds"] = round(time.time() - t0, 1)
    with open(RESULTS, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"wrote {RESULTS} in {summary['elapsed_seconds']}s")


if __name__ == "__main__":
    sys.exit(main())
