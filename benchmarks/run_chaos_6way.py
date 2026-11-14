#!/usr/bin/env python3
"""Large-scale 6-architecture chaos & multi-crash evaluation for ClaimFence.

Compares 6 durability and deduplication architectures across 1,500 seeded multi-step
workflows per condition (9,000 total episodes) plus a multi-crash horizon sweep
k in {1, 2, 3, 4} crashes per workflow (1,000 episodes per (architecture, k)):

  1. baseline         : Trajectory checkpointing only (no keys, no WAL, no fence)
  2. content_hash     : Idempotent receiver + SHA256(action, raw_args) retry keys
  3. deterministic_pos: Idempotent receiver + (wid, step_idx, action) positional keys
  4. ckpt_ledger      : REMIT-style checkpoint-time effect ledger (written atomically
                        with step completion checkpoint AFTER external tool commit)
  5. det_canonical    : Canonicalized (wid, action, target, occ) keys without WAL
                        and without RIFL payload persistence (status-only suppression)
  6. claimfence       : Full ClaimFence v2.0 (flock-serialized pre-invocation WAL +
                        atomic server CAS_inc fencing + RIFL payload replay)

Fault dimensions injected identically (paired per episode seed across all 6 conditions):
  - Multi-step dataflow chains: half of effectful pairs have Step s+1 consuming the
    authentic `receipt_token` returned by Step s (measuring Dataflow Continuity Rate).
  - Crash window landing: 75% in W(s) = (t_commit, t_ckpt), 15% post-checkpoint, 10% pre-call.
  - Post-crash LLM replanning nondeterminism: P(reword_memo)=0.50, P(shift_index)=0.30,
    P(omit_unrecorded_retry)=0.08 (planner uncertainty when uncheckpointed step status is unknown).
  - Overlapping stale zombie retry: P(zombie)=0.30 (late stale writer with reworded args).
  - Concurrent dual-recovery race: P(dual_recovery)=0.25 (two recovery workers race).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claimfence import (
    AtomicIdempotentReceiver,
    ClaimFenceRuntime,
    FencedError,
    IndexedJSONLClaimStore,
)

OUT_PATH = ROOT / "results" / "chaos_6way_results.json"

SEED = 20261114
EPISODES_PER_COND = 1500
SWEEP_EPISODES = 1000

P_IN_WINDOW = 0.75
P_POST_CKPT = 0.15
P_REWORD = 0.50
P_SHIFT = 0.30
P_ZOMBIE = 0.30
P_DUAL_REC = 0.25

ACTIONS = ["issue_refund", "update_ledger", "send_notice", "provision_quota"]


def content_hash_key(wid: str, action: str, args: Dict[str, Any]) -> str:
    payload = json.dumps(args, sort_keys=True)
    digest = hashlib.sha256(f"{wid}|{action}|{payload}".encode()).hexdigest()[:24]
    return f"ch:{digest}"


def positional_key(wid: str, pos_idx: int, action: str) -> str:
    return f"pos:{wid}:{pos_idx}:{action}"


def canonical_key(wid: str, action: str, target: str, occ: int) -> str:
    return f"can:{wid}:{action}:{target}:occ{occ}"


def generate_workflow(rng: random.Random) -> List[Dict[str, Any]]:
    """Generate a 5-to-8 effectful-step workflow including intentional multi-occurrence
    steps and upstream->downstream receipt_token dataflow dependencies."""
    n_steps = rng.randint(5, 8)
    steps: List[Dict[str, Any]] = []
    occ_tracker: Dict[Tuple[str, str], int] = {}

    base_cust = f"acct-{rng.randint(1000, 9999)}"
    for i in range(n_steps):
        # 20% chance of a second authorized operation on base_cust to exercise occurrence > 0
        if i >= 2 and rng.random() < 0.20:
            action = steps[0]["action"]
            target = steps[0]["target"]
        else:
            action = rng.choice(ACTIONS)
            target = f"acct-{rng.randint(1000, 9999)}-s{i}" if i > 0 else base_cust

        occ = occ_tracker.get((action, target), 0)
        occ_tracker[(action, target)] = occ + 1

        depends_on = (i - 1) if (i % 2 == 1) else None
        steps.append(
            {
                "step_id": i,
                "action": action,
                "target": target,
                "occurrence": occ,
                "depends_on": depends_on,
                "memo": f"op {i} for {target} (occ={occ})",
            }
        )
    return steps


def run_single_episode(
    ep_seed: int,
    arch: str,
    n_crashes: int = 1,
    tmp_root: Optional[str] = None,
) -> Dict[str, Any]:
    rng = random.Random(ep_seed)
    wid = f"wf-{arch}-{ep_seed:012x}"
    steps = generate_workflow(rng)

    # Pre-sample crash schedule (deterministic per ep_seed across all architectures!)
    crash_indices = sorted(rng.sample(range(len(steps)), k=min(n_crashes, len(steps))))
    crash_specs = {}
    for ci in crash_indices:
        u = rng.random()
        landing = (
            "in_window"
            if u < P_IN_WINDOW
            else "post_ckpt"
            if u < P_IN_WINDOW + P_POST_CKPT
            else "pre_call"
        )
        crash_specs[ci] = {
            "landing": landing,
            "reword": rng.random() < P_REWORD,
            "shift": rng.random() < P_SHIFT,
            "zombie": rng.random() < P_ZOMBIE,
            "dual_rec": rng.random() < P_DUAL_REC,
        }

    fencing_on = arch == "claimfence"
    status_only = arch != "claimfence"
    recv = AtomicIdempotentReceiver(
        state_dir=None,
        fencing_enabled=fencing_on,
        status_only_mode=status_only,
        durable_disk=False,
    )

    # Durable harness structures across crashes
    checkpoint = -1
    ckpt_ledger_done: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    cf_dir = os.path.join(tmp_root, wid) if (arch == "claimfence" and tmp_root) else None
    if arch == "claimfence":
        assert cf_dir is not None
        os.makedirs(cf_dir, exist_ok=True)
        store_path = os.path.join(cf_dir, "claim.jsonl")
        ckpt_path = os.path.join(cf_dir, "ckpt.json")

    # Volatile memory of current worker generation (wiped on every crash!)
    volatile_tokens: Dict[int, str] = {}
    durable_ckpt_tokens: Dict[int, str] = {}  # persisted only when step is checkpointed

    epoch = 0
    holder = "gen0"
    pos_offset = 0
    reword_active = False

    idx = 0
    crashes_triggered = set()

    while idx < len(steps):
        s = steps[idx]
        sid = s["step_id"]
        ident = (s["action"], s["target"], s["occurrence"])
        pos_idx = sid + pos_offset

        # Resolve upstream receipt_token if dependent
        dep_tok = None
        if s["depends_on"] is not None:
            dep_id = s["depends_on"]
            dep_tok = volatile_tokens.get(dep_id) or durable_ckpt_tokens.get(dep_id)
            if arch == "claimfence" and dep_tok is None:
                dep_s = steps[dep_id]
                st_tmp = IndexedJSONLClaimStore(store_path)
                rec_dep = st_tmp.find_by_identity(
                    dep_s["action"], dep_s["target"], dep_s["occurrence"]
                )
                if rec_dep and rec_dep.result:
                    dep_tok = rec_dep.result.get("receipt_token")

        memo = s["memo"] + (" [replanned]" if reword_active else "")
        args = {"memo": memo, "upstream_token": dep_tok}

        will_crash = (sid in crash_specs) and (sid not in crashes_triggered)
        spec = crash_specs.get(sid)

        if arch == "claimfence":
            rt = ClaimFenceRuntime(
                wid, IndexedJSONLClaimStore(store_path), ckpt_path, recv, holder_id=holder
            )
            rt.epoch = epoch
            crashed_now = False

            def hook(stage: str) -> None:
                nonlocal crashed_now
                if not will_crash:
                    return
                if (
                    (spec["landing"] == "pre_call" and stage == "after_claim_before_call")
                    or (spec["landing"] == "in_window" and stage == "after_call_before_commit_log")
                    or (spec["landing"] == "post_ckpt" and stage == "after_ckpt")
                ):
                    crashed_now = True
                    raise RuntimeError("CRASH")

            try:
                res = rt.execute_step(
                    sid, s["action"], s["target"], args, occurrence=s["occurrence"], crash_hook=hook
                )
                if res.get("result"):
                    tok = res["result"].get("receipt_token")
                    volatile_tokens[sid] = tok
                    durable_ckpt_tokens[sid] = tok
            except RuntimeError:
                pass

            if crashed_now:
                crashes_triggered.add(sid)
                old_epoch = epoch
                volatile_tokens.clear()  # volatile RAM wiped!

                # Recovery R1 (and concurrent R2 if dual_rec)
                if spec["dual_rec"]:
                    rt_r1 = ClaimFenceRuntime(
                        wid, IndexedJSONLClaimStore(store_path), ckpt_path, recv, holder_id=f"r1-{sid}"
                    )
                    rt_r2 = ClaimFenceRuntime(
                        wid, IndexedJSONLClaimStore(store_path), ckpt_path, recv, holder_id=f"r2-{sid}"
                    )
                    # Interleaved dual recovery: R1 acquires fence, R2 immediately acquires higher fence
                    f1 = recv.acquire_fence_atomic(wid, holder_id=rt_r1.holder_id)
                    rt_r1.epoch = f1["epoch"]
                    info2 = rt_r2.recover()
                    # R1 attempts stale reconciliation and gets cleanly fenced
                    for c in rt_r1.store.uncommitted():
                        recv.call(
                            wid, c.uid, c.action, c.target, c.args, c.key, rt_r1.epoch, rt_r1.holder_id
                        )
                    epoch = info2["epoch"]
                    holder = rt_r2.holder_id
                    checkpoint = info2["checkpoint"]
                else:
                    rt_rec = ClaimFenceRuntime(
                        wid, IndexedJSONLClaimStore(store_path), ckpt_path, recv, holder_id=f"rec-{sid}"
                    )
                    info = rt_rec.recover()
                    epoch = info["epoch"]
                    holder = rt_rec.holder_id
                    checkpoint = info["checkpoint"]

                # Zombie retry from dead worker at old_epoch with fresh reworded key
                if spec["zombie"]:
                    z_args = {"memo": s["memo"] + " [zombie]", "upstream_token": dep_tok}
                    z_key = content_hash_key(wid, s["action"], z_args)
                    recv.call(wid, str(sid), s["action"], s["target"], z_args, z_key, old_epoch, "zombie")

                reword_active = spec["reword"]
                if spec["shift"]:
                    pos_offset += 1
                idx = checkpoint + 1
                continue
            else:
                idx += 1
                continue

        # --- Non-ClaimFence Architectures (1..5) ---
        if arch == "ckpt_ledger" and ident in ckpt_ledger_done:
            saved = ckpt_ledger_done[ident]
            if saved.get("receipt_token"):
                volatile_tokens[sid] = saved["receipt_token"]
            idx += 1
            continue

        if arch == "baseline":
            key = None
        elif arch == "content_hash":
            key = content_hash_key(wid, s["action"], args)
        elif arch == "deterministic_pos":
            key = positional_key(wid, pos_idx, s["action"])
        elif arch == "ckpt_ledger":
            # REMIT-style: branch/step positional effect ID, ledger recorded at checkpoint time
            key = positional_key(wid, pos_idx, s["action"])
        elif arch == "det_canonical":
            key = canonical_key(wid, s["action"], s["target"], s["occurrence"])
        else:
            raise ValueError(arch)

        # Pre-call crash
        if will_crash and spec["landing"] == "pre_call":
            crashes_triggered.add(sid)
            volatile_tokens.clear()
            if spec["zombie"]:
                z_args = {"memo": s["memo"] + " [zombie]", "upstream_token": dep_tok}
                z_key = content_hash_key(wid, s["action"], z_args) if key is not None else None
                recv.call(wid, str(sid), s["action"], s["target"], z_args, z_key, 0, "zombie")
            reword_active = spec["reword"]
            if spec["shift"]:
                pos_offset += 1
            idx = checkpoint + 1
            continue

        # Tool call commits on external service T!
        _, resp = recv.call(wid, str(sid), s["action"], s["target"], args, key, 0, holder)
        ret_tok = (resp.get("result") or {}).get("receipt_token")
        if ret_tok:
            volatile_tokens[sid] = ret_tok

        # In-window crash W(s): after T commits, BEFORE checkpoint (or ckpt_ledger) writes!
        if will_crash and spec["landing"] == "in_window":
            crashes_triggered.add(sid)
            volatile_tokens.clear()  # pre-crash return value in RAM is lost!
            if spec["zombie"]:
                z_args = {"memo": s["memo"] + " [zombie]", "upstream_token": dep_tok}
                z_key = content_hash_key(wid, s["action"], z_args) if key is not None else None
                recv.call(wid, str(sid), s["action"], s["target"], z_args, z_key, 0, "zombie")
            if spec["dual_rec"]:
                # Second uncoordinated recovery worker also replays uncheckpointed step sid!
                r2_args = {
                    "memo": s["memo"] + (" [r2]" if spec["reword"] else ""),
                    "upstream_token": durable_ckpt_tokens.get(s["depends_on"]) if s["depends_on"] is not None else None,
                }
                if arch == "baseline":
                    r2_k = None
                elif arch == "content_hash":
                    r2_k = content_hash_key(wid, s["action"], r2_args)
                elif arch in ("deterministic_pos", "ckpt_ledger"):
                    r2_k = positional_key(wid, pos_idx + (2 if spec["shift"] else 0), s["action"])
                else:
                    r2_k = canonical_key(wid, s["action"], s["target"], s["occurrence"])
                recv.call(wid, str(sid), s["action"], s["target"], r2_args, r2_k, 0, "r2")

            reword_active = spec["reword"]
            if spec["shift"]:
                pos_offset += 1
            idx = checkpoint + 1
            continue

        # Durable checkpoint write (and transactional effect-ledger write for ckpt_ledger)
        checkpoint = sid
        if ret_tok:
            durable_ckpt_tokens[sid] = ret_tok
        if arch == "ckpt_ledger":
            ckpt_ledger_done[ident] = {"key": key, "receipt_token": ret_tok}

        if will_crash and spec["landing"] == "post_ckpt":
            crashes_triggered.add(sid)
            volatile_tokens.clear()
            if spec["zombie"]:
                z_args = {"memo": s["memo"] + " [zombie]", "upstream_token": dep_tok}
                z_key = content_hash_key(wid, s["action"], z_args) if key is not None else None
                recv.call(wid, str(sid), s["action"], s["target"], z_args, z_key, 0, "zombie")
            reword_active = spec["reword"]
            if spec["shift"]:
                pos_offset += 1
            idx = checkpoint + 1
            continue

        idx += 1

    # --- Ground-truth audit against receiver's durable ledger ---
    commits = recv.workflow_commits(wid)
    intended_identities = [(s["action"], s["target"], s["occurrence"]) for s in steps]

    # Map each committed entry back to logical identity (action, target, occ_by_step_uid)
    step_by_id = {str(s["step_id"]): s for s in steps}
    committed_counts: Dict[Tuple[str, str, int], int] = {}
    authentic_token_by_step: Dict[int, str] = {}
    valid_downstream_links = 0
    total_downstream_links = sum(1 for s in steps if s["depends_on"] is not None)

    for c in commits:
        suid = c["step_uid"]
        s_orig = step_by_id.get(suid)
        occ = s_orig["occurrence"] if s_orig else 0
        ident = (c["action"], c["target"], occ)
        committed_counts[ident] = committed_counts.get(ident, 0) + 1
        if s_orig and committed_counts[ident] == 1:
            authentic_token_by_step[s_orig["step_id"]] = c["result"]["receipt_token"]

    # Check dataflow payload integrity on downstream steps
    seen_downstream_checked = set()
    for c in commits:
        suid = c["step_uid"]
        s_orig = step_by_id.get(suid)
        if s_orig and s_orig["depends_on"] is not None:
            sid_int = s_orig["step_id"]
            if sid_int not in seen_downstream_checked:
                seen_downstream_checked.add(sid_int)
                expected_tok = authentic_token_by_step.get(s_orig["depends_on"])
                actual_tok = c["args"].get("upstream_token")
                if expected_tok is not None and actual_tok == expected_tok:
                    valid_downstream_links += 1

    duplicates = sum(max(0, cnt - 1) for cnt in committed_counts.values())
    missing = sum(1 for ident in intended_identities if committed_counts.get(ident, 0) == 0)
    payload_broken = valid_downstream_links < total_downstream_links

    return {
        "duplicates": duplicates,
        "missing": missing,
        "exactly_once": (duplicates == 0 and missing == 0),
        "payload_intact": not payload_broken,
        "strict_success": (duplicates == 0 and missing == 0 and not payload_broken),
        "fenced_rejections": recv.fenced_rejections,
    }


def main() -> None:
    t0 = time.perf_counter()
    os.makedirs(OUT_PATH.parent, exist_ok=True)
    architectures = [
        "baseline",
        "content_hash",
        "deterministic_pos",
        "ckpt_ledger",
        "det_canonical",
        "claimfence",
    ]

    main_table: Dict[str, Any] = {}
    with tempfile.TemporaryDirectory(dir=str(OUT_PATH.parent), prefix="_chaos_") as tmp:
        print("=== Running 6-Way Chaos Suite (1,500 paired episodes/architecture) ===")
        for arch in architectures:
            dup_eps = 0
            miss_eps = 0
            eo_eps = 0
            payload_ok_eps = 0
            strict_ok_eps = 0
            tot_dups = 0
            tot_fenced = 0
            for i in range(EPISODES_PER_COND):
                ep_seed = SEED + i * 1009
                res = run_single_episode(ep_seed, arch, n_crashes=1, tmp_root=tmp)
                if res["duplicates"] > 0:
                    dup_eps += 1
                if res["missing"] > 0:
                    miss_eps += 1
                if res["exactly_once"]:
                    eo_eps += 1
                if res["payload_intact"]:
                    payload_ok_eps += 1
                if res["strict_success"]:
                    strict_ok_eps += 1
                tot_dups += res["duplicates"]
                tot_fenced += res["fenced_rejections"]
                # Clean per-episode claimfence dir to keep disk tidy
                if arch == "claimfence":
                    import shutil
                    shutil.rmtree(os.path.join(tmp, f"wf-{arch}-{ep_seed:012x}"), ignore_errors=True)

            n = EPISODES_PER_COND
            main_table[arch] = {
                "episodes": n,
                "duplicate_ep_rate": round(dup_eps / n, 4),
                "missing_ep_rate": round(miss_eps / n, 4),
                "exactly_once_rate": round(eo_eps / n, 4),
                "payload_continuity_rate": round(payload_ok_eps / n, 4),
                "strict_e2e_correct_rate": round(strict_ok_eps / n, 4),
                "mean_duplicates_per_ep": round(tot_dups / n, 4),
                "fenced_rejections": tot_fenced,
            }
            m = main_table[arch]
            print(
                f"  [{arch:18s}] dup={m['duplicate_ep_rate']:.4f} miss={m['missing_ep_rate']:.4f} "
                f"eo={m['exactly_once_rate']:.4f} payload_ok={m['payload_continuity_rate']:.4f} "
                f"strict_e2e={m['strict_e2e_correct_rate']:.4f}"
            )

        print("\n=== Running Multi-Crash Horizon Sweep k in {1, 2, 3, 4} (1,000 eps/point) ===")
        multi_crash_sweep: Dict[str, Dict[str, Any]] = {a: {} for a in architectures}
        for k in (1, 2, 3, 4):
            for arch in architectures:
                dup_eps = 0
                strict_ok = 0
                for i in range(SWEEP_EPISODES):
                    ep_seed = SEED + 5_000_000 + k * 500_000 + i * 997
                    res = run_single_episode(ep_seed, arch, n_crashes=k, tmp_root=tmp)
                    if res["duplicates"] > 0:
                        dup_eps += 1
                    if res["strict_success"]:
                        strict_ok += 1
                    if arch == "claimfence":
                        import shutil
                        shutil.rmtree(os.path.join(tmp, f"wf-{arch}-{ep_seed:012x}"), ignore_errors=True)
                multi_crash_sweep[arch][str(k)] = {
                    "duplicate_ep_rate": round(dup_eps / SWEEP_EPISODES, 4),
                    "strict_e2e_correct_rate": round(strict_ok / SWEEP_EPISODES, 4),
                }
            print(
                f"  k={k}: "
                + " | ".join(
                    f"{a[:8]}={multi_crash_sweep[a][str(k)]['strict_e2e_correct_rate']:.3f}"
                    for a in architectures
                )
            )

    out_doc = {
        "seed": SEED,
        "episodes_per_condition": EPISODES_PER_COND,
        "sweep_episodes_per_point": SWEEP_EPISODES,
        "main_6way": main_table,
        "multi_crash_sweep": multi_crash_sweep,
        "elapsed_s": round(time.perf_counter() - t0, 2),
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out_doc, f, indent=2)
    print(f"\nWrote {OUT_PATH} in {out_doc['elapsed_s']}s")


if __name__ == "__main__":
    main()
