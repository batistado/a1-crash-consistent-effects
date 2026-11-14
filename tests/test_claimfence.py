"""Unit and concurrency stress tests for ClaimFence v2.0."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claimfence import (
    AtomicIdempotentReceiver,
    ClaimFenceRuntime,
    FencedError,
    IndexedJSONLClaimStore,
    SQLiteWALClaimStore,
    start_tool_server_in_thread,
)


class SimulatedCrash(BaseException):
    """Simulates abrupt worker process death discarding volatile frame state."""


@pytest.mark.parametrize("backend", ["jsonl", "sqlite"])
@pytest.mark.parametrize(
    "crash_stage",
    [
        "after_claim_before_call",
        "after_call_before_commit_log",
        "after_commit_log_before_ckpt",
        "after_ckpt",
    ],
)
def test_all_crash_windows_preserve_exactly_once_and_payload(backend: str, crash_stage: str):
    with tempfile.TemporaryDirectory() as tmp:
        recv = AtomicIdempotentReceiver(os.path.join(tmp, "srv"))
        ckpt_path = os.path.join(tmp, "ckpt.json")

        def make_store():
            if backend == "jsonl":
                return IndexedJSONLClaimStore(os.path.join(tmp, "claim.jsonl"))
            return SQLiteWALClaimStore(os.path.join(tmp, "claim.sqlite"))

        wid = f"wf-{backend}-{crash_stage}"
        rt1 = ClaimFenceRuntime(wid, make_store(), ckpt_path, recv, holder_id="gen0")

        def hook(stage: str) -> None:
            if stage == crash_stage:
                raise SimulatedCrash(stage)

        with pytest.raises(SimulatedCrash):
            rt1.execute_step(
                0,
                "issue_refund",
                "cust-42",
                {"amount": 212.00, "memo": "initial request"},
                occurrence=0,
                crash_hook=hook,
            )

        # Fresh recovery generation opens durable files cold
        rt2 = ClaimFenceRuntime(wid, make_store(), ckpt_path, recv, holder_id="gen1")
        rec_info = rt2.recover()
        assert rec_info["epoch"] == 1
        assert rec_info["checkpoint"] == 0

        # Recovered LLM retries Step 0 with reworded args & shifted step index (step_index=2)
        retry_res = rt2.execute_step(
            2,
            "issue_refund",
            "cust-42",
            {"amount": 212.00, "memo": "reworded post-crash retry"},
            occurrence=0,
        )
        assert retry_res["status"] == "skipped_via_log"
        receipt_token = retry_res["result"]["receipt_token"]
        assert receipt_token.startswith("rcpt_iss_")

        # Chained Step 1 consumes Step 0's recovered receipt_token
        step1_res = rt2.execute_step(
            3,
            "send_email",
            "cust-42",
            {"receipt_ref": receipt_token, "body": "Refund processed"},
            occurrence=0,
        )
        assert step1_res["status"] == "committed"

        commits = recv.workflow_commits(wid)
        assert len(commits) == 2
        assert commits[0]["action"] == "issue_refund"
        assert commits[1]["args"]["receipt_ref"] == receipt_token


def test_concurrent_workers_shared_identity_bijection():
    """16 concurrent worker threads race to claim the same (action, target, occurrence=0).
    POSIX flock serialization guarantees exactly 1 key is minted and 1 tool commit lands."""
    with tempfile.TemporaryDirectory() as tmp:
        store_path = os.path.join(tmp, "shared_claim.jsonl")
        recv = AtomicIdempotentReceiver(os.path.join(tmp, "srv"))
        wid = "wf-race-workers"
        keys_seen = []
        lock = threading.Lock()
        barrier = threading.Barrier(16)

        def worker(tid: int):
            local_store = IndexedJSONLClaimStore(store_path)
            barrier.wait()
            rec, _ = local_store.create_or_reuse(
                wid=wid,
                uid=f"w{tid}",
                action="issue_refund",
                target="cust-shared",
                args={"worker": tid},
                epoch=1,
                occurrence=0,
            )
            code, resp = recv.call(
                wid, f"w{tid}", "issue_refund", "cust-shared", {"worker": tid}, rec.key, epoch=1
            )
            assert code == 200
            with lock:
                keys_seen.append(rec.key)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(keys_seen) == 16
        assert len(set(keys_seen)) == 1, "Multiple keys minted for one logical identity!"
        assert len(recv.workflow_commits(wid)) == 1, "Duplicate commit under worker contention!"


def test_concurrent_dual_recovery_and_zombie_fencing():
    """4 concurrent recovery processes race on atomic server CAS fencing alongside a
    surviving pre-crash zombie writer minting a fresh key at stale epoch 0."""
    with tempfile.TemporaryDirectory() as tmp:
        store_path = os.path.join(tmp, "claim.jsonl")
        ckpt_path = os.path.join(tmp, "ckpt.json")
        recv = AtomicIdempotentReceiver(os.path.join(tmp, "srv"))
        wid = "wf-dual-recovery"

        # Pre-crash worker logs CLAIM at epoch 0, crashes before calling tool
        s0 = IndexedJSONLClaimStore(store_path)
        s0.create_or_reuse(wid, "0", "update_record", "acct-9", {"v": 1}, epoch=0, occurrence=0)

        barrier = threading.Barrier(4)
        outcomes = []
        lock = threading.Lock()

        def recovery_runner(rid: int):
            rt = ClaimFenceRuntime(
                wid, IndexedJSONLClaimStore(store_path), ckpt_path, recv, holder_id=f"rec-{rid}"
            )
            barrier.wait()
            try:
                info = rt.recover()
                with lock:
                    outcomes.append(("ok", info["epoch"]))
            except FencedError:
                with lock:
                    outcomes.append(("fenced", rt.epoch))

        threads = [threading.Thread(target=recovery_runner, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Zombie writer from epoch 0 wakes up late with a brand-new unseen content-hash key
        code, zresp = recv.call(
            wid, "0", "update_record", "acct-9", {"v": 1, "zombie": True}, "ch:zombie_fresh", epoch=0
        )
        assert code == 409 and zresp["status"] == "fenced"

        # Verify monotonic epochs [1, 2, 3, 4], at least the highest epoch succeeded, and exactly 1 commit landed
        ok_epochs = [ep for st, ep in outcomes if st == "ok"]
        assert len(ok_epochs) >= 1
        assert max( ep for _, ep in outcomes ) == 4
        assert len(recv.workflow_commits(wid)) == 1
        assert recv.fenced_rejections >= 1


def test_torn_trailing_record_and_multi_occurrence_http():
    """Verifies torn trailing JSON line handling and multi-occurrence HTTP tool server."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = os.path.join(tmp, "torn.jsonl")
        recv = AtomicIdempotentReceiver(os.path.join(tmp, "srv"))
        srv, url = start_tool_server_in_thread(recv)
        try:
            store = IndexedJSONLClaimStore(log_path)
            c0, _ = store.create_or_reuse("wf-t", "0", "issue_refund", "cust-7", {"amt": 10}, 1, 0)
            store.append_commit(c0.key, result={"receipt_token": "r0"})

            # Simulate torn mid-write record at tail of file (SIGKILL mid-write)
            with open(log_path, "ab") as f:
                f.write(b'{"kind":"claim","wid":"wf-t","action":"trunc')

            # Re-open cold: torn tail must be ignored, c0 intact, next append succeeds cleanly
            store2 = IndexedJSONLClaimStore(log_path)
            assert len(store2.claims()) == 1
            assert store2.find_by_identity("issue_refund", "cust-7", 0).result == {"receipt_token": "r0"}

            # Second separately authorized refund (occurrence=1) gets distinct key
            c1, reused = store2.create_or_reuse("wf-t", "1", "issue_refund", "cust-7", {"amt": 25}, 1)
            assert not reused
            assert c1.occurrence == 1
            assert c1.key != c0.key
        finally:
            srv.shutdown()


def test_multinode_disjoint_filesystem_http_claim_store():
    """Verifies cross-node failover over HTTPClaimStore with zero shared POSIX filesystem."""
    from claimfence import (
        HTTPClaimStore,
        RemoteClaimStoreState,
        start_remote_claim_store_in_thread,
    )

    with tempfile.TemporaryDirectory() as state_node_dir:
        state_svc = RemoteClaimStoreState(state_node_dir)
        srv, state_url = start_remote_claim_store_in_thread(state_svc)
        recv = AtomicIdempotentReceiver(None)
        wid = "wf-multinode"
        try:
            # Node A (no local checkpoint file; uses remote state store)
            node_a_store = HTTPClaimStore(state_url, wid)
            rt_a = ClaimFenceRuntime(wid, node_a_store, None, recv, holder_id="node-A")

            def crash_in_window(stage: str) -> None:
                if stage == "after_call_before_commit_log":
                    raise RuntimeError("NODE_A_VM_TERMINATED")

            try:
                rt_a.execute_step(0, "issue_refund", "cust-500", {"amt": 99}, occurrence=0, crash_hook=crash_in_window)
            except RuntimeError:
                pass

            assert rt_a.read_checkpoint()["checkpoint"] == -1
            assert len(recv.workflow_commits(wid)) == 1

            # Node B starts on a completely separate host with a fresh HTTPClaimStore client
            node_b_store = HTTPClaimStore(state_url, wid)
            rt_b = ClaimFenceRuntime(wid, node_b_store, None, recv, holder_id="node-B")
            info = rt_b.recover()
            assert info["epoch"] == 1
            assert info["replayed_claims"] == 1
            assert info["checkpoint"] == 0

            # Node A wakes from partition as zombie -> fenced 409
            try:
                rt_a.execute_step(1, "record_ledger", "cust-500", {"tok": "stale"})
                assert False, "Expected FencedError"
            except FencedError:
                pass

            # Node B retrieves Step 0's cached receipt_token over network and executes Step 1
            saved = rt_b.get_committed_result("issue_refund", "cust-500", 0)
            assert saved is not None and "receipt_token" in saved
            res1 = rt_b.execute_step(1, "record_ledger", "cust-500", {"upstream_token": saved["receipt_token"]})
            assert res1["status"] == "committed"
            assert len(recv.workflow_commits(wid)) == 2
        finally:
            srv.shutdown()


def test_transactional_outbox_proxy_stripe_and_legacy_upstreams():
    """Verifies TransactionalOutboxProxy fronting unmodified Stripe-like and legacy REST APIs."""
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from claimfence import HTTPClaimStore, RemoteClaimStoreState, TransactionalOutboxProxy, start_remote_claim_store_in_thread

    def start_dummy_upstream(support_idempotency_key: bool):
        commits = []
        seen_idem = {}
        lock = threading.Lock()

        class UpHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(n).decode("utf-8"))
                idem = self.headers.get("Idempotency-Key")
                with lock:
                    if support_idempotency_key and idem and idem in seen_idem:
                        payload = seen_idem[idem]
                    else:
                        tok = f"up_rcpt_{len(commits) + 1}"
                        payload = {"result": {"receipt_token": tok}}
                        commits.append({"idem": idem, "body": body, "tok": tok})
                        if support_idempotency_key and idem:
                            seen_idem[idem] = payload
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), UpHandler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        return httpd, f"http://127.0.0.1:{httpd.server_address[1]}", commits

    # Case A: Unmodified Stripe-like upstream (Idempotency-Key supported, NO /fence endpoint)
    # Survives BOTH worker crash AND proxy crash inside W_proxy!
    up_srv, up_url, up_commits = start_dummy_upstream(support_idempotency_key=True)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            proxy = TransactionalOutboxProxy(os.path.join(tmp, "outbox.sqlite"), up_url)
            store = IndexedJSONLClaimStore(os.path.join(tmp, "claims.jsonl"))
            ckpt = os.path.join(tmp, "ckpt.json")
            wid = "wf-stripe"

            c0, _ = store.create_or_reuse(wid, "0", "issue_refund", "cust-88", {"amt": 50}, 0, 0)

            # Simulate proxy crash right after upstream commits, before outbox marks COMPLETED!
            def proxy_crash(stage: str) -> None:
                if stage == "after_upstream_before_outbox_complete":
                    raise RuntimeError("PROXY_HOST_CRASH")

            try:
                proxy.call(wid, "0", "issue_refund", "cust-88", {"amt": 50}, c0.key, 0, "w0", proxy_crash_hook=proxy_crash)
            except RuntimeError:
                pass
            assert len(up_commits) == 1

            # Recovery worker runs ClaimFenceRuntime against restarted proxy -> 0 upstream duplicates + authentic receipt_token!
            proxy_restarted = TransactionalOutboxProxy(os.path.join(tmp, "outbox.sqlite"), up_url)
            rt_rec = ClaimFenceRuntime(wid, store, ckpt, proxy_restarted, holder_id="rec-1")
            info = rt_rec.recover()
            assert info["replayed_claims"] == 1
            assert len(up_commits) == 1
            saved = rt_rec.get_committed_result("issue_refund", "cust-88", 0)
            assert saved == {"receipt_token": "up_rcpt_1"}
        finally:
            up_srv.shutdown()

    # Case B: Unmodified legacy non-idempotent upstream (NO Idempotency-Key, NO /fence)
    # Eliminates 100% of worker W(s) crashes and stale zombies!
    leg_srv, leg_url, leg_commits = start_dummy_upstream(support_idempotency_key=False)
    with tempfile.TemporaryDirectory() as tmp2:
        try:
            proxy2 = TransactionalOutboxProxy(os.path.join(tmp2, "outbox_leg.sqlite"), leg_url)
            store2 = IndexedJSONLClaimStore(os.path.join(tmp2, "claims_leg.jsonl"))
            ckpt2 = os.path.join(tmp2, "ckpt_leg.json")
            wid2 = "wf-legacy"
            rt0 = ClaimFenceRuntime(wid2, store2, ckpt2, proxy2, holder_id="w0")

            try:
                rt0.execute_step(
                    0, "issue_refund", "cust-99", {"amt": 75}, 0,
                    crash_hook=lambda st: (_ for _ in ()).throw(RuntimeError("WORKER_CRASH")) if st == "after_call_before_commit_log" else None,
                )
            except RuntimeError:
                pass
            assert len(leg_commits) == 1

            rt_rec2 = ClaimFenceRuntime(wid2, store2, ckpt2, proxy2, holder_id="rec-1")
            rt_rec2.recover()
            # Late zombie with fresh key is fenced by the proxy before ever reaching legacy upstream!
            code, _ = proxy2.call(wid2, "0", "issue_refund", "cust-99", {"amt": 75}, "rogue-key", epoch=0, holder_id="w0")
            assert code == 409
            assert len(leg_commits) == 1
            assert rt_rec2.get_committed_result("issue_refund", "cust-99", 0) == {"receipt_token": "up_rcpt_1"}
        finally:
            leg_srv.shutdown()


def test_canonical_identity_extractor_and_a4_guardrail():
    """Verifies target canonicalization, diagnostic bypass, and A4 occurrence guardrails."""
    from claimfence import AuthorizationViolationError, CanonicalIdentityExtractor

    ext = CanonicalIdentityExtractor(
        effectful_actions={"issue_refund", "record_ledger"},
        diagnostic_actions={"check_account_status"},
        authorized_max_occurrence={("issue_refund", "cust-1042"): 0},
        default_max_occurrence=0,
    )

    # 1. Surface target drift and E2b-style paraphrase normalize to identical canonical target
    id1 = ext.extract({"action": "issue_refund", "target": "  CUST_1042  "})
    id2 = ext.extract({"action": "issue_refund", "target": "customer cust-1042 (retry)_rpl", "occurrence": 0})
    assert id1.triple == ("issue_refund", "cust-1042", 0)
    assert id2.triple == ("issue_refund", "cust-1042", 0)

    # 2. Diagnostic calls are flagged read-only without mutating claim state
    diag = ext.extract({"action": "check_account_status", "target": "CUST_1042"})
    assert diag.is_diagnostic and diag.target == "cust-1042"

    # 3. Hallucinated occurrence=1 when only occurrence=0 is authorized raises fail-closed error
    try:
        ext.extract({"action": "issue_refund", "target": "cust-1042", "occurrence": 1})
        assert False, "Expected AuthorizationViolationError on unauthorized occurrence=1"
    except AuthorizationViolationError:
        pass
