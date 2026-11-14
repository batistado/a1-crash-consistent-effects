#!/usr/bin/env python3
"""Exhaustive Finite-State Model Checker for Crash-Consistent Effect Protocols.

Explores 100% of reachable asynchronous interleavings via breadth-first search (BFS)
over a two-stage dataflow-dependent workflow (Step 0 -> receipt_token -> Step 1)
with:
  - Primary worker W0 executing against external non-transactional service T
  - Unclean watchdog timeout leaving a paused pre-crash zombie worker W0 that wakes
    up AFTER recovery starts (overlapping generations)
  - Up to two concurrent recovery workers (R1, R2) racing on recovery & Step 1 claim
    creation with claim-time unique keys (UUIDs, per Remark 4)
  - Post-crash LLM argument rewording / step-index shift on unrecorded retries

Verifies three invariants across 100% of reachable and terminal states:
  I1 (At-Most-Once Safety):   t_s0_commits <= 1 and t_s1_commits <= 1 in EVERY state
  I2 (Exact Completion):      t_s0_commits == 1 and t_s1_commits == 1 in EVERY terminal state
  I3 (Payload Continuity):    Step 1 commits with the authentic receipt_token ("tok_1")
                              produced by Step 0 in EVERY terminal state

Evaluates 5 protocol designs:
  1. trajectory_ckpt_only     (Baseline: checkpoint after call, no keys, no fence)
  2. keys_only_mutable        (Idempotent receiver, retry-derived mutable key, no WAL)
  3. ckpt_time_ledger         (REMIT-style: ledger written atomically with checkpoint, post-call)
  4. wal_v1_nonatomic_status  (v1.0 WAL: non-atomic client stored+1 fence, unserialized claim
                               append, status-only dedup without payload replay)
  5. claimfence_full          (ClaimFence v2.0: flock-serialized pre-call WAL + server atomic
                               CAS_inc fence + RIFL payload-preserving reconciliation)
"""

from __future__ import annotations

import collections
import dataclasses
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "results" / "model_checking_results.json"


@dataclasses.dataclass(frozen=True)
class ModelState:
    # W0 pc: 0=init, 1=claimed_s0, 2=called_s0, 3=marked_s0, 4=ckpt_s0, 5=done_all, 6=crashed
    w0_pc: int
    w0_token: Optional[str]
    zombie_pending: bool  # Paused W0 wakes up after watchdog spawns R1 (overlapping gen)

    # Durable ClaimStore state
    wal_s0_claimed: bool
    wal_s0_key: Optional[str]
    wal_s0_committed: bool
    wal_s0_payload: Optional[str]
    wal_s1_key: Optional[str]  # flock-serialized shared claim key for Step 1
    ckpt_s0: bool
    local_epoch_file: int

    # Durable external service T state
    t_max_epoch: int
    t_holder: Optional[str]
    t_s0_commits: int
    t_s1_commits: int
    t_seen_keys: Tuple[Tuple[str, str], ...]
    t_s1_used_valid_token: bool

    # Concurrent recovery workers R1, R2
    # pc: 0=not_started, 05(1)=read_local_epoch, 2=fenced, 3=reconciled_s0,
    #     4=replanned_s0, 5=claimed_s1, 6=done, 9=fenced_aborted
    r1_pc: int
    r1_epoch: int
    r1_token: Optional[str]
    r1_s1_key: Optional[str]

    r2_pc: int
    r2_epoch: int
    r2_token: Optional[str]
    r2_s1_key: Optional[str]


def lookup_seen(seen: Tuple[Tuple[str, str], ...], key: Optional[str]) -> Optional[str]:
    if key is None:
        return None
    for k, tok in seen:
        if k == key:
            return tok
    return None


def add_seen(
    seen: Tuple[Tuple[str, str], ...], key: Optional[str], tok: str
) -> Tuple[Tuple[str, str], ...]:
    if key is None or lookup_seen(seen, key) is not None:
        return seen
    return tuple(sorted(list(seen) + [(key, tok)]))


def invoke_tool(
    st: ModelState,
    protocol: str,
    step_no: int,
    key: Optional[str],
    epoch: int,
    holder: str,
    input_token: Optional[str] = None,
) -> Tuple[ModelState, str, Optional[str]]:
    """Atomic check-and-commit at external service T for Step 0 or Step 1."""
    use_fence = protocol in ("wal_v1_nonatomic_status", "claimfence_full")
    strict_holder = protocol == "claimfence_full"
    return_payload_on_dup = protocol == "claimfence_full"

    if use_fence:
        if epoch < st.t_max_epoch or (
            strict_holder
            and epoch == st.t_max_epoch
            and st.t_holder is not None
            and st.t_holder != holder
        ):
            return st, "fenced", None

    new_max = max(st.t_max_epoch, epoch) if use_fence else st.t_max_epoch
    new_holder = holder if (use_fence and epoch > st.t_max_epoch) else st.t_holder

    existing_tok = lookup_seen(st.t_seen_keys, key)
    if existing_tok is not None:
        ret_tok = existing_tok if return_payload_on_dup else None
        nst = dataclasses.replace(st, t_max_epoch=new_max, t_holder=new_holder)
        return nst, "duplicate_suppressed", ret_tok

    if step_no == 0:
        cid = st.t_s0_commits + 1
        tok = f"tok_{cid}"
        new_seen = add_seen(st.t_seen_keys, key, tok)
        nst = dataclasses.replace(
            st,
            t_max_epoch=new_max,
            t_holder=new_holder,
            t_s0_commits=cid,
            t_seen_keys=new_seen,
        )
        return nst, "committed", tok
    else:
        cid = st.t_s1_commits + 1
        tok = f"s1_rcpt_{cid}"
        valid_tok = (input_token == "tok_1" and st.t_s0_commits == 1)
        new_seen = add_seen(st.t_seen_keys, key, tok)
        nst = dataclasses.replace(
            st,
            t_max_epoch=new_max,
            t_holder=new_holder,
            t_s1_commits=cid,
            t_seen_keys=new_seen,
            t_s1_used_valid_token=(st.t_s1_used_valid_token or valid_tok),
        )
        return nst, "committed", tok


def transitions(st: ModelState, protocol: str) -> List[Tuple[str, ModelState]]:
    out: List[Tuple[str, ModelState]] = []
    has_wal = protocol in ("wal_v1_nonatomic_status", "claimfence_full")
    has_ckpt_ledger = protocol == "ckpt_time_ledger"
    has_keys = protocol != "trajectory_ckpt_only"
    flock_serialized = protocol == "claimfence_full"

    # --- Primary worker W0 ---
    if st.w0_pc < 5:
        if st.w0_pc == 0:
            if has_wal:
                out.append(
                    (
                        "W0_claim_s0(k_orig)",
                        dataclasses.replace(
                            st, w0_pc=1, wal_s0_claimed=True, wal_s0_key="k_orig"
                        ),
                    )
                )
            else:
                out.append(("W0_prepare_s0", dataclasses.replace(st, w0_pc=1)))

        elif st.w0_pc == 1:
            k = "k_orig" if has_keys else None
            nst, status, tok = invoke_tool(st, protocol, 0, k, epoch=0, holder="W0")
            out.append(
                (
                    f"W0_call_s0({k})->{status}",
                    dataclasses.replace(nst, w0_pc=2, w0_token=tok),
                )
            )
            out.append(
                ("CRASH_pre_call", dataclasses.replace(st, w0_pc=6, zombie_pending=False))
            )
            out.append(
                (
                    "PAUSE_watchdog_timeout_zombie",
                    dataclasses.replace(st, w0_pc=6, zombie_pending=True),
                )
            )

        elif st.w0_pc == 2:
            # Crash inside W(s) = (t_commit, t_ckpt)!
            out.append(
                (
                    "CRASH_in_window_W(s)",
                    dataclasses.replace(st, w0_pc=6, w0_token=None, zombie_pending=False),
                )
            )
            out.append(
                (
                    "CRASH_in_window_with_zombie",
                    dataclasses.replace(st, w0_pc=6, w0_token=None, zombie_pending=True),
                )
            )
            if has_wal:
                out.append(
                    (
                        "W0_commit_log_s0",
                        dataclasses.replace(
                            st,
                            w0_pc=3,
                            wal_s0_committed=True,
                            wal_s0_payload=st.w0_token if protocol == "claimfence_full" else None,
                        ),
                    )
                )
            elif has_ckpt_ledger:
                out.append(
                    (
                        "W0_tx_ckpt_and_ledger_s0",
                        dataclasses.replace(
                            st,
                            w0_pc=4,
                            ckpt_s0=True,
                            wal_s0_claimed=True,
                            wal_s0_committed=True,
                            wal_s0_key="k_orig",
                            wal_s0_payload=st.w0_token,
                        ),
                    )
                )
            else:
                out.append(("W0_ckpt_s0", dataclasses.replace(st, w0_pc=4, ckpt_s0=True)))

        elif st.w0_pc == 3:
            out.append(
                (
                    "CRASH_between_log_and_ckpt",
                    dataclasses.replace(st, w0_pc=6, w0_token=None),
                )
            )
            out.append(("W0_log_fenced_ckpt_s0", dataclasses.replace(st, w0_pc=4, ckpt_s0=True)))

        elif st.w0_pc == 4:
            # Either crash post-checkpoint before Step 1, or complete Step 1 cleanly
            out.append(
                ("CRASH_post_ckpt_before_s1", dataclasses.replace(st, w0_pc=6, w0_token=None))
            )
            k1 = "k_s1_w0" if has_keys else None
            nst, status, _ = invoke_tool(
                st, protocol, 1, k1, epoch=0, holder="W0", input_token=st.w0_token
            )
            out.append(
                (
                    f"W0_clean_finish_s1->{status}",
                    dataclasses.replace(nst, w0_pc=5, r1_pc=9, r2_pc=9),
                )
            )

    # --- Overlapping Zombie Writer Arrival (fires AFTER R1 has acquired recovery fence: r1_pc >= 2) ---
    if st.w0_pc == 6 and st.zombie_pending and st.r1_pc >= 2:
        z_key = "k_zombie_fresh" if has_keys else None
        nst, z_status, _ = invoke_tool(st, protocol, 0, z_key, epoch=0, holder="W0")
        out.append(
            (
                f"ZOMBIE_late_arrival({z_key},e=0)->{z_status}",
                dataclasses.replace(nst, zombie_pending=False),
            )
        )

    # --- Recovery Workers R1 and R2 (when W0 crashed/timed out: w0_pc == 6) ---
    if st.w0_pc == 6:
        for rid in (1, 2):
            pc = st.r1_pc if rid == 1 else st.r2_pc
            ep = st.r1_epoch if rid == 1 else st.r2_epoch
            rtok = st.r1_token if rid == 1 else st.r2_token
            rs1k = st.r1_s1_key if rid == 1 else st.r2_s1_key
            holder = f"R{rid}"

            def set_r(
                base: ModelState,
                new_pc: int,
                new_ep: int = ep,
                new_tok: Optional[str] = rtok,
                new_s1k: Optional[str] = rs1k,
            ) -> ModelState:
                if rid == 1:
                    return dataclasses.replace(
                        base, r1_pc=new_pc, r1_epoch=new_ep, r1_token=new_tok, r1_s1_key=new_s1k
                    )
                return dataclasses.replace(
                    base, r2_pc=new_pc, r2_epoch=new_ep, r2_token=new_tok, r2_s1_key=new_s1k
                )

            if pc == 0:
                if rid == 2 and st.r1_pc == 0:
                    continue
                if protocol == "claimfence_full":
                    # Single atomic server RPC: epoch <- t_max_epoch + 1
                    alloc_ep = st.t_max_epoch + 1
                    nst = dataclasses.replace(
                        st,
                        t_max_epoch=alloc_ep,
                        t_holder=holder,
                        local_epoch_file=alloc_ep,
                    )
                    out.append((f"{holder}_atomic_CAS_fence(e={alloc_ep})", set_r(nst, 2, alloc_ep)))
                elif protocol == "wal_v1_nonatomic_status":
                    # Step 1a of non-atomic client read-increment-write: read local_epoch_file
                    read_ep = st.local_epoch_file + 1
                    out.append((f"{holder}_read_local_epoch->{read_ep}", set_r(st, 1, read_ep)))
                else:
                    out.append((f"{holder}_start_unfenced", set_r(st, 2, 0)))

            elif pc == 1:
                # Step 1b of wal_v1_nonatomic_status: write local_epoch_file and register max(cur, ep)
                nst = dataclasses.replace(
                    st,
                    local_epoch_file=ep,
                    t_max_epoch=max(st.t_max_epoch, ep),
                )
                out.append((f"{holder}_register_client_fence(e={ep})", set_r(nst, 2, ep)))

            elif pc == 2:
                # Reconciliation-first pass
                if has_wal and st.wal_s0_claimed and not st.wal_s0_committed:
                    nst, status, tok = invoke_tool(
                        st, protocol, 0, st.wal_s0_key, epoch=ep, holder=holder
                    )
                    if status == "fenced":
                        out.append((f"{holder}_reconcile_fenced", set_r(nst, 9)))
                    else:
                        nst2 = dataclasses.replace(
                            nst,
                            wal_s0_committed=True,
                            wal_s0_payload=tok if protocol == "claimfence_full" else nst.wal_s0_payload,
                            ckpt_s0=True,
                        )
                        out.append((f"{holder}_reconcile_s0->{status}", set_r(nst2, 3, ep, tok)))
                else:
                    cached = st.wal_s0_payload if (has_wal or has_ckpt_ledger) else None
                    out.append((f"{holder}_reconcile_noop", set_r(st, 3, ep, cached)))

            elif pc == 3:
                # Resume Step 0 if not settled
                if st.ckpt_s0 or st.wal_s0_committed:
                    tok = rtok or st.wal_s0_payload
                    out.append((f"{holder}_skip_settled_s0", set_r(st, 4, ep, tok)))
                else:
                    if has_wal:
                        # Create-or-reuse s0
                        s0k = st.wal_s0_key or f"k_s0_{holder}"
                        nst0 = (
                            dataclasses.replace(st, wal_s0_claimed=True, wal_s0_key=s0k)
                            if (flock_serialized or not st.wal_s0_claimed)
                            else st
                        )
                        use_k = nst0.wal_s0_key if flock_serialized else f"k_s0_{holder}"
                        nst, status, tok = invoke_tool(
                            nst0, protocol, 0, use_k, epoch=ep, holder=holder
                        )
                        if status == "fenced":
                            out.append((f"{holder}_s0_fenced", set_r(nst, 9)))
                        else:
                            nst2 = dataclasses.replace(
                                nst,
                                wal_s0_committed=True,
                                wal_s0_payload=tok if protocol == "claimfence_full" else None,
                                ckpt_s0=True,
                            )
                            out.append((f"{holder}_exec_s0->{status}", set_r(nst2, 4, ep, tok)))
                    else:
                        retry_k = f"k_replan_{holder}" if has_keys else None
                        nst, status, tok = invoke_tool(
                            st, protocol, 0, retry_k, epoch=ep, holder=holder
                        )
                        nst2 = dataclasses.replace(nst, ckpt_s0=True)
                        out.append(
                            (f"{holder}_replan_s0({retry_k})->{status}", set_r(nst2, 4, ep, tok))
                        )

            elif pc == 4:
                # Claim Step 1 (with claim-time UUID key per Remark 4)
                if flock_serialized:
                    s1k = st.wal_s1_key or f"uuid_s1_{holder}"
                    nst = dataclasses.replace(st, wal_s1_key=s1k)
                    out.append((f"{holder}_flock_claim_s1({s1k})", set_r(nst, 5, ep, rtok, s1k)))
                else:
                    # Without flock create-or-reuse, concurrent writers each mint their own key
                    s1k = f"uuid_s1_{holder}" if has_keys else None
                    out.append((f"{holder}_mint_s1({s1k})", set_r(st, 5, ep, rtok, s1k)))

            elif pc == 5:
                nst, status, _ = invoke_tool(
                    st, protocol, 1, rs1k, epoch=ep, holder=holder, input_token=rtok
                )
                if status == "fenced":
                    out.append((f"{holder}_s1_fenced", set_r(nst, 9)))
                else:
                    out.append((f"{holder}_call_s1(tok={rtok})->{status}", set_r(nst, 6)))

    # Allow single-recovery completion (R2 never triggered) once R1 finishes and zombie (if any) drained
    if st.w0_pc == 6 and not st.zombie_pending and st.r1_pc in (6, 9) and st.r2_pc == 0:
        out.append(("single_recovery_complete", dataclasses.replace(st, r2_pc=9)))

    return out


def check_protocol(protocol: str) -> Dict[str, Any]:
    t0 = time.perf_counter()
    init = ModelState(
        w0_pc=0,
        w0_token=None,
        zombie_pending=False,
        wal_s0_claimed=False,
        wal_s0_key=None,
        wal_s0_committed=False,
        wal_s0_payload=None,
        wal_s1_key=None,
        ckpt_s0=False,
        local_epoch_file=0,
        t_max_epoch=0,
        t_holder=None,
        t_s0_commits=0,
        t_s1_commits=0,
        t_seen_keys=(),
        t_s1_used_valid_token=False,
        r1_pc=0,
        r1_epoch=0,
        r1_token=None,
        r1_s1_key=None,
        r2_pc=0,
        r2_epoch=0,
        r2_token=None,
        r2_s1_key=None,
    )

    visited: Set[ModelState] = {init}
    parent: Dict[ModelState, Tuple[Optional[ModelState], str]] = {init: (None, "INIT")}
    queue = collections.deque([init])

    edges = 0
    terminal_states = 0
    safety_violations = 0
    liveness_violations = 0
    payload_violations = 0
    first_ce: Dict[str, List[str]] = {}

    def reconstruct(s: ModelState) -> List[str]:
        trace = []
        cur: Optional[ModelState] = s
        while cur is not None:
            prev, act = parent[cur]
            if prev is not None:
                trace.append(act)
            cur = prev
        trace.reverse()
        return trace

    while queue:
        cur = queue.popleft()
        succs = transitions(cur, protocol)
        edges += len(succs)

        if cur.t_s0_commits > 1 or cur.t_s1_commits > 1:
            safety_violations += 1
            if "I1_duplicate_commit" not in first_ce:
                first_ce["I1_duplicate_commit"] = reconstruct(cur)

        if not succs:
            terminal_states += 1
            if cur.t_s0_commits != 1 or cur.t_s1_commits != 1:
                liveness_violations += 1
                if "I2_exact_completion" not in first_ce:
                    first_ce["I2_exact_completion"] = reconstruct(cur)
            if not cur.t_s1_used_valid_token:
                payload_violations += 1
                if "I3_payload_continuity" not in first_ce:
                    first_ce["I3_payload_continuity"] = reconstruct(cur)

        for act, nxt in succs:
            if nxt not in visited:
                visited.add(nxt)
                parent[nxt] = (cur, act)
                queue.append(nxt)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return {
        "protocol": protocol,
        "reachable_states": len(visited),
        "transitions_explored": edges,
        "terminal_states": terminal_states,
        "safety_duplicate_states": safety_violations,
        "terminal_exact_once_violations": liveness_violations,
        "terminal_payload_loss_violations": payload_violations,
        "all_invariants_hold": (
            safety_violations == 0
            and liveness_violations == 0
            and payload_violations == 0
        ),
        "shortest_counterexamples": first_ce,
        "elapsed_ms": round(elapsed_ms, 2),
    }


def main() -> None:
    os.makedirs(OUT_PATH.parent, exist_ok=True)
    protocols = [
        "trajectory_ckpt_only",
        "keys_only_mutable",
        "ckpt_time_ledger",
        "wal_v1_nonatomic_status",
        "claimfence_full",
    ]
    results = []
    for p in protocols:
        res = check_protocol(p)
        results.append(res)
        print(
            f"[{p:24s}] states={res['reachable_states']:5d} edges={res['transitions_explored']:5d} "
            f"term={res['terminal_states']:3d} "
            f"dup_states={res['safety_duplicate_states']:4d} "
            f"eo_viol={res['terminal_exact_once_violations']:3d} "
            f"payload_viol={res['terminal_payload_loss_violations']:3d} "
            f"PASS={res['all_invariants_hold']}"
        )
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"models": results}, f, indent=2)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
