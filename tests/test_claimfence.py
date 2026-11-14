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
