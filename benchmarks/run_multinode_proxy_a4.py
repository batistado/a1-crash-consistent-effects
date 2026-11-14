#!/usr/bin/env python3
"""Empirical evaluation of the three distributed scope boundaries:
1. Disaggregated Multi-Node Failover (`HTTPClaimStore` over TCP HTTP/1.1, zero shared FS):
   - Per-step RPC latency breakdown (CLAIM, COMMIT, remote log-fenced CKPT, N=10^4 lookup)
   - 500 multi-node failover workflows (Node A crashes in W(s), Node B + racing R2 recover)
2. Unmodified Third-Party & Legacy API `TransactionalOutboxProxy` (500 workflows x 3 modes):
   - Mode P1: Commercial Idempotent API (Idempotency-Key header only, no /fence) + 20% proxy crash
   - Mode P2: Legacy Non-Idempotent API (no Idempotency-Key, no /fence), worker crashes/zombies/dual-rec
   - Mode P3: Legacy Non-Idempotent API + 20% simultaneous proxy-host crash inside W_proxy
3. Identity Extractor & Assumption (A4) Sensitivity (500 workflows x 3 regimes):
   - Regime A1: Surface target paraphrase + 3x LLM re-emissions + 25% authorized occ=1
   - Regime A2: Uncalibrated planner violating A4 (30% false occ=0->1 increment on retry), no guardrail
   - Regime A3: Same A4-violating planner + CanonicalIdentityExtractor max-occurrence guardrail
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claimfence import (
    AtomicIdempotentReceiver,
    AuthorizationViolationError,
    CanonicalIdentityExtractor,
    ClaimFenceRuntime,
    FencedError,
    HTTPClaimStore,
    IndexedJSONLClaimStore,
    RemoteClaimStoreState,
    TransactionalOutboxProxy,
    start_remote_claim_store_in_thread,
)


def pct(vals: List[float], q: float) -> float:
    return float(np.percentile(vals, q))


def bench_multinode_http_claim_store(bench_dir: str) -> Dict[str, Any]:
    """Measure persistent NVMe-backed HTTPClaimStore per-step latency and 500-ep failover."""
    state_dir = os.path.join(bench_dir, "remote_state")
    state_svc = RemoteClaimStoreState(state_dir)
    srv, state_url = start_remote_claim_store_in_thread(state_svc)
    recv = AtomicIdempotentReceiver(None)

    try:
        # 1. Per-step RPC latency breakdown over 400 steps on persistent NVMe
        wid_lat = "wf-net-lat"
        client = HTTPClaimStore(state_url, wid_lat)
        # Warm keep-alive socket
        client.read_remote_checkpoint()

        t_claim, t_commit, t_ckpt, t_total = [], [], [], []
        for i in range(400):
            t0 = time.perf_counter()
            c, _ = client.create_or_reuse(
                wid_lat, str(i), "issue_refund", f"cust-{i}", {"amt": 42}, 1, 0
            )
            t1 = time.perf_counter()
            client.append_commit(c.key, result={"receipt_token": f"rcpt_{i}"})
            t2 = time.perf_counter()
            client.advance_remote_checkpoint(step_index=i, epoch=1, claim_key=c.key)
            t3 = time.perf_counter()
            t_claim.append((t1 - t0) * 1000.0)
            t_commit.append((t2 - t1) * 1000.0)
            t_ckpt.append((t3 - t2) * 1000.0)
            t_total.append((t3 - t0) * 1000.0)

        # Populate up to N=10,000 claims in wid_10k to measure remote O(log N) lookup over TCP
        wid_10k = "wf-net-10k"
        _, _, _ = state_svc._get_wf(wid_10k)
        # Fast bulk seed directly into SQLite on server for N=10,000, then measure client RPC lookup
        lk, st_sql, _ = state_svc._get_wf(wid_10k)
        with lk:
            st_sql._conn.execute("PRAGMA synchronous=NORMAL;")
            st_sql._conn.execute("BEGIN IMMEDIATE;")
            for j in range(10000):
                st_sql._conn.execute(
                    """
                    INSERT INTO claims (wid, uid, action, target, occurrence, args_json, key, epoch, committed, result_json)
                    VALUES (?, ?, 'issue_refund', ?, 0, '{"amt":10}', ?, 1, 1, '{"receipt_token":"r"}');
                    """,
                    (wid_10k, str(j), f"cust-{j}", f"cf:{wid_10k}:issue_refund:cust-{j}:occ0"),
                )
            st_sql._conn.execute("COMMIT;")
            st_sql._conn.execute("PRAGMA synchronous=FULL;")

        client_10k = HTTPClaimStore(state_url, wid_10k)
        client_10k.find_by_identity("issue_refund", "cust-0", 0)
        rng_q = random.Random(42)
        t_lookup = []
        for _ in range(300):
            q_idx = rng_q.randint(0, 9999)
            t0 = time.perf_counter()
            rec = client_10k.find_by_identity("issue_refund", f"cust-{q_idx}", 0)
            t1 = time.perf_counter()
            assert rec is not None
            t_lookup.append((t1 - t0) * 1000.0)

        # 2. 500 Disjoint-Node Failover Workflows (2-step chained workflow, zombies + dual-rec)
        rng = random.Random(20261115)
        dup_eps = 0
        strict_ok = 0
        fenced_cnt = 0
        n_eps = 500
        for ep in range(n_eps):
            wid = f"mn-{ep}"
            cust = f"cust-{1000 + ep}"
            store_a = HTTPClaimStore(state_url, wid)
            rt_a = ClaimFenceRuntime(wid, store_a, None, recv, holder_id=f"nodeA-{ep}")

            # Crash Node A in W(s_0)
            try:
                rt_a.execute_step(
                    0,
                    "issue_refund",
                    cust,
                    {"amt": 100},
                    occurrence=0,
                    crash_hook=lambda st: (_ for _ in ()).throw(RuntimeError("CRASH"))
                    if st == "after_call_before_commit_log"
                    else None,
                )
            except RuntimeError:
                pass

            # Dual recovery on Node B1 and Node B2 (25% rate) or single recovery on Node B1
            if rng.random() < 0.25:
                rt_b1 = ClaimFenceRuntime(
                    wid, HTTPClaimStore(state_url, wid), None, recv, holder_id=f"nodeB1-{ep}"
                )
                rt_b2 = ClaimFenceRuntime(
                    wid, HTTPClaimStore(state_url, wid), None, recv, holder_id=f"nodeB2-{ep}"
                )
                f1 = recv.acquire_fence_atomic(wid, holder_id=rt_b1.holder_id)
                rt_b1.epoch = f1["epoch"]
                rt_b2.recover()
                for c in rt_b1.store.uncommitted():
                    recv.call(wid, c.uid, c.action, c.target, c.args, c.key, rt_b1.epoch, rt_b1.holder_id)
                active_rt = rt_b2
            else:
                rt_b = ClaimFenceRuntime(
                    wid, HTTPClaimStore(state_url, wid), None, recv, holder_id=f"nodeB-{ep}"
                )
                rt_b.recover()
                active_rt = rt_b

            # Delayed zombie from Node A (30% rate)
            if rng.random() < 0.30:
                code, _ = recv.call(
                    wid, "0", "issue_refund", cust, {"amt": 100, "z": 1}, f"rogue-{ep}", 0, f"nodeA-{ep}"
                )
                if code == 409:
                    fenced_cnt += 1

            # Execute dependent Step 1 on active recovery node using Step 0's cached receipt_token
            s0_res = active_rt.get_committed_result("issue_refund", cust, 0)
            tok = s0_res["receipt_token"] if s0_res else None
            active_rt.execute_step(1, "record_ledger", cust, {"upstream_token": tok}, occurrence=0)

            commits = recv.workflow_commits(wid)
            c0 = [c for c in commits if c["action"] == "issue_refund"]
            c1 = [c for c in commits if c["action"] == "record_ledger"]
            if len(c0) > 1 or len(c1) > 1:
                dup_eps += 1
            if (
                len(c0) == 1
                and len(c1) == 1
                and c1[0]["args"].get("upstream_token") == c0[0]["result"]["receipt_token"]
            ):
                strict_ok += 1

        return {
            "latency_ms": {
                "claim_p50_ms": round(pct(t_claim, 50), 3),
                "commit_p50_ms": round(pct(t_commit, 50), 3),
                "ckpt_p50_ms": round(pct(t_ckpt, 50), 3),
                "step_total_p50_ms": round(pct(t_total, 50), 3),
                "step_total_p99_ms": round(pct(t_total, 99), 3),
                "lookup_10k_p50_ms": round(pct(t_lookup, 50), 3),
            },
            "failover_500": {
                "episodes": n_eps,
                "duplicate_ep_rate": round(dup_eps / n_eps, 4),
                "strict_e2e_rate": round(strict_ok / n_eps, 4),
                "fenced_zombie_probes": fenced_cnt,
            },
        }
    finally:
        srv.shutdown()


def _start_upstream_server(support_idem_key: bool):
    commits_by_wid: Dict[str, List[Dict[str, Any]]] = {}
    idem_cache: Dict[str, Dict[str, Any]] = {}
    lock = threading.Lock()
    seq = [0]

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            return

        def do_POST(self):
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n).decode("utf-8"))
            idem = self.headers.get("Idempotency-Key")
            wid = str(body["workflow_id"])
            with lock:
                if support_idem_key and idem and idem in idem_cache:
                    payload = idem_cache[idem]
                else:
                    seq[0] += 1
                    tok = f"up_tok_{seq[0]}"
                    payload = {"result": {"receipt_token": tok}}
                    commits_by_wid.setdefault(wid, []).append(
                        {
                            "action": body["action"],
                            "target": body["target"],
                            "args": body.get("args") or {},
                            "tok": tok,
                        }
                    )
                    if support_idem_key and idem:
                        idem_cache[idem] = payload
            raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(raw)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}", commits_by_wid


def bench_outbox_proxy_modes(bench_dir: str) -> Dict[str, Any]:
    """Evaluate TransactionalOutboxProxy across P1 (Stripe-like), P2 (Legacy, worker faults),
    and P3 (Legacy + 20% simultaneous proxy-host crash in W_proxy)."""
    configs = [
        ("stripe_idem_upstream_with_proxy_crash", True, 0.20),
        ("legacy_non_idem_worker_faults_only", False, 0.00),
        ("legacy_non_idem_with_proxy_crash", False, 0.20),
    ]
    out: Dict[str, Any] = {}
    n_eps = 300

    for label, support_idem, p_proxy_crash in configs:
        up_srv, up_url, commits_by_wid = _start_upstream_server(support_idem)
        db_path = os.path.join(bench_dir, f"{label}.sqlite")
        proxy = TransactionalOutboxProxy(db_path, up_url)
        rng = random.Random(20261116)
        dup_eps = 0
        strict_ok = 0

        try:
            for ep in range(n_eps):
                wid = f"{label}-{ep}"
                cust = f"cust-{ep}"
                ep_dir = os.path.join(bench_dir, f"ep_{label}_{ep}")
                os.makedirs(ep_dir, exist_ok=True)
                store_p = os.path.join(ep_dir, "claims.jsonl")
                ckpt_p = os.path.join(ep_dir, "ckpt.json")

                st0 = IndexedJSONLClaimStore(store_p)
                c0, _ = st0.create_or_reuse(wid, "0", "issue_refund", cust, {"amt": 50}, 0, 0)

                proxy_dies = rng.random() < p_proxy_crash
                worker_dies = True  # 100% worker crash in W(s_0) unless proxy died first

                try:
                    code, resp = proxy.call(
                        wid,
                        "0",
                        "issue_refund",
                        cust,
                        {"amt": 50},
                        c0.key,
                        epoch=0,
                        holder_id="w0",
                        proxy_crash_hook=(
                            (
                                lambda stage: (_ for _ in ()).throw(RuntimeError("PROXY_CRASH"))
                                if (proxy_dies and stage == "after_upstream_before_outbox_complete")
                                else None
                            )
                        ),
                    )
                    if not worker_dies:
                        st0.append_commit(c0.key, result=resp.get("result"))
                except RuntimeError:
                    pass

                # Zombie retry with fresh key from stale epoch 0 after recovery acquires fence
                rt_rec = ClaimFenceRuntime(
                    wid, IndexedJSONLClaimStore(store_p), ckpt_p, proxy, holder_id="rec1"
                )
                rt_rec.recover()

                if rng.random() < 0.30:
                    proxy.call(
                        wid, "0", "issue_refund", cust, {"amt": 50, "z": 1}, f"z-{ep}", epoch=0, holder_id="w0"
                    )

                s0_res = rt_rec.get_committed_result("issue_refund", cust, 0)
                tok = s0_res.get("receipt_token") if s0_res else None
                rt_rec.execute_step(1, "record_ledger", cust, {"upstream_token": tok}, occurrence=0)

                u_commits = commits_by_wid.get(wid, [])
                c0_list = [x for x in u_commits if x["action"] == "issue_refund"]
                c1_list = [x for x in u_commits if x["action"] == "record_ledger"]
                if len(c0_list) > 1 or len(c1_list) > 1:
                    dup_eps += 1
                if (
                    len(c0_list) == 1
                    and len(c1_list) == 1
                    and c1_list[0]["args"].get("upstream_token") == c0_list[0]["tok"]
                ):
                    strict_ok += 1

            out[label] = {
                "episodes": n_eps,
                "upstream_supports_idempotency_key": support_idem,
                "proxy_crash_prob_in_w_proxy": p_proxy_crash,
                "duplicate_ep_rate": round(dup_eps / n_eps, 4),
                "strict_e2e_rate": round(strict_ok / n_eps, 4),
            }
        finally:
            up_srv.shutdown()

    return out


def bench_a4_extractor_regimes(bench_dir: str) -> Dict[str, Any]:
    """Evaluate CanonicalIdentityExtractor under target drift, re-emissions, and A4 violations."""
    n_eps = 500
    regimes = [
        ("a4_compliant_paraphrase_and_reemit", False, True),
        ("a4_violated_false_occ_increment_unguarded", True, False),
        ("a4_violated_false_occ_increment_policy_guarded", True, True),
    ]
    out: Dict[str, Any] = {}

    for label, inject_false_occ, enable_policy_guard in regimes:
        rng = random.Random(20261117)
        recv = AtomicIdempotentReceiver(None)
        dup_eps = 0
        strict_ok = 0
        policy_blocks = 0

        for ep in range(n_eps):
            wid = f"{label}-{ep}"
            cust = f"cust-{2000 + ep}"
            two_refunds = rng.random() < 0.25
            max_refund_occ = 1 if two_refunds else 0

            ext = CanonicalIdentityExtractor(
                effectful_actions={"issue_refund", "record_ledger"},
                diagnostic_actions={"check_account_status"},
                authorized_max_occurrence=(
                    {("issue_refund", cust): max_refund_occ, ("record_ledger", cust): 0}
                    if enable_policy_guard
                    else None
                ),
            )

            ep_dir = os.path.join(bench_dir, f"a4_{label}_{ep}")
            os.makedirs(ep_dir, exist_ok=True)
            store_p = os.path.join(ep_dir, "claims.jsonl")
            ckpt_p = os.path.join(ep_dir, "ckpt.json")

            # Worker 0 crashes inside W(s_0) after T commits primary refund (occ=0)
            rt0 = ClaimFenceRuntime(wid, IndexedJSONLClaimStore(store_p), ckpt_p, recv, holder_id="w0")
            try:
                rt0.execute_step(
                    0,
                    "issue_refund",
                    cust,
                    {"amt": 120},
                    occurrence=0,
                    crash_hook=lambda st: (_ for _ in ()).throw(RuntimeError("CRASH"))
                    if st == "after_call_before_commit_log"
                    else None,
                )
            except RuntimeError:
                pass

            # Recovery worker reconciles first
            rt_rec = ClaimFenceRuntime(
                wid, IndexedJSONLClaimStore(store_p), ckpt_p, recv, holder_id="rec1"
            )
            rt_rec.recover()

            # Post-recovery LLM planner emits noisy/paraphrased calls:
            # 1) Diagnostic call (ignored cleanly)
            _ = ext.extract({"action": "check_account_status", "target": cust.upper()})

            # 2) Superfluous re-emission of Step 0 with surface target drift (CUST_XXXX_rpl)
            #    In A4-violating regimes, 30% of episodes falsely set occurrence=1 on a 1-refund case!
            hallucinated_occ = (
                1 if (inject_false_occ and not two_refunds and rng.random() < 0.30) else 0
            )
            noisy_target = f"  {cust.upper().replace('-', '_')}_rpl  "
            try:
                id_reemit = ext.extract(
                    {"action": "issue_refund", "target": noisy_target, "occurrence": hallucinated_occ}
                )
                rt_rec.execute_step(
                    0,
                    id_reemit.action,
                    id_reemit.target,
                    {"amt": 120, "memo": "re-emitted"},
                    occurrence=id_reemit.occurrence,
                )
            except AuthorizationViolationError:
                policy_blocks += 1

            # 3) Dependent Step 1 (`record_ledger`) + optional legitimate 2nd refund (`occ=1`)
            s0_res = rt_rec.get_committed_result("issue_refund", cust, 0)
            tok = s0_res["receipt_token"] if s0_res else None
            id_s1 = ext.extract({"action": "record_ledger", "target": noisy_target, "occurrence": 0})
            rt_rec.execute_step(1, id_s1.action, id_s1.target, {"upstream_token": tok}, id_s1.occurrence)

            if two_refunds:
                id_s2 = ext.extract({"action": "issue_refund", "target": noisy_target, "occurrence": 1})
                rt_rec.execute_step(2, id_s2.action, id_s2.target, {"amt": 15}, id_s2.occurrence)

            commits = recv.workflow_commits(wid)
            ref_commits = [c for c in commits if c["action"] == "issue_refund"]
            led_commits = [c for c in commits if c["action"] == "record_ledger"]
            expected_refs = 2 if two_refunds else 1
            if len(ref_commits) > expected_refs or len(led_commits) > 1:
                dup_eps += 1
            if (
                len(ref_commits) == expected_refs
                and len(led_commits) == 1
                and led_commits[0]["args"].get("upstream_token") == ref_commits[0]["result"]["receipt_token"]
            ):
                strict_ok += 1

        out[label] = {
            "episodes": n_eps,
            "duplicate_ep_rate": round(dup_eps / n_eps, 4),
            "strict_e2e_rate": round(strict_ok / n_eps, 4),
            "policy_blocked_hallucinations": policy_blocks,
        }

    return out


def main() -> None:
    bench_dir = str(ROOT / "results" / "_multinode_proxy_bench")
    if os.path.exists(bench_dir):
        shutil.rmtree(bench_dir)
    os.makedirs(bench_dir, exist_ok=True)

    t0 = time.time()
    try:
        mn = bench_multinode_http_claim_store(bench_dir)
        px = bench_outbox_proxy_modes(bench_dir)
        a4 = bench_a4_extractor_regimes(bench_dir)
    finally:
        shutil.rmtree(bench_dir, ignore_errors=True)

    payload = {
        "elapsed_sec": round(time.time() - t0, 2),
        "multinode_http_claim_store": mn,
        "outbox_proxy_evaluation": px,
        "a4_extractor_evaluation": a4,
    }
    out_path = ROOT / "results" / "multinode_proxy_a4_results.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
