#!/usr/bin/env python3
"""E7 — two separately-authorized refunds to the same target, then retries
of each across a crash (Phase 7, third-review point 1).

The reviewer asked for a trace/test showing that the newly added
discrimination property holds end to end: two distinct authorized
effects sharing (action, target) with different occurrences must BOTH
commit, and a post-crash retry of EACH must be recognized as equivalent
and suppressed (1 commit per retried identity).

Scripted against the real ClaimLog implementation plus a minimal
in-memory idempotent receiver honoring the paper's tool contract
(atomic check-and-commit; duplicate_suppressed on re-seen key).

The crash is simulated by dropping the in-memory ClaimLog handle and
re-opening the same durable file — exactly the durability boundary
the protocol relies on.

$0 API. Run: python3 e7_two_refunds_retries.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from claim_log import ClaimLog


class MockReceiver:
    """Atomic idempotent receiver (paper §4, A1)."""

    def __init__(self):
        self.seen = set()
        self.ledger = []  # committed effects, ground truth

    def call(self, key, epoch, action, target, occurrence):
        if key in self.seen:
            return "duplicate_suppressed"
        self.seen.add(key)
        self.ledger.append((action, target, occurrence, key))
        return "committed"


def create_or_reuse(log, wid, action, target, occurrence, epoch):
    """Paper's create-or-reuse claim creation: look up the full
    (action, target, occurrence) identity in L; reuse the existing key
    if a durable Claim exists, else mint a fresh key and append durably
    BEFORE any tool call."""
    existing = log.find_by_identity(action, target, occurrence)
    if existing is not None:
        return existing["key"], True  # reuse path
    key = f"k:{wid}:{action}:{target}:occ{occurrence}"
    # fresh keys are unique per (wid, occurrence); a crash between this
    # mint and the durable append can never collide: claim discipline
    # forbids the tool call until the claim is durable.
    log.append_claim(f"uid-{action}-{target}-{occurrence}", action, target,
                     "e7", key, epoch, occurrence=occurrence)
    return key, False


def main():
    tmp = tempfile.mkdtemp(prefix="e7_")
    log = ClaimLog(os.path.join(tmp, "e7.log"))
    recv = MockReceiver()
    wid = "wf-e7"
    trace = []

    # --- generation 0: two SEPARATELY AUTHORIZED refunds, same target ---
    for occ in (0, 1):
        key, reused = create_or_reuse(log, wid, "issue_refund",
                                      "customer-9", occ, epoch=1)
        assert not reused, "fresh identity must not reuse"
        st = recv.call(key, 1, "issue_refund", "customer-9", occ)
        assert st == "committed", st
        for c in log.claims():
            if c["key"] == key:
                log.append_commit(c)
        trace.append({"step": f"auth-refund-occ{occ}", "key": key,
                      "reused": reused, "receiver": st})
    assert len(recv.ledger) == 2, "both authorized refunds must commit"

    # --- CRASH: drop the handle, re-open the durable log ---
    del log
    log = ClaimLog(os.path.join(tmp, "e7.log"))
    trace.append({"event": "crash", "durable_claims": len(log.claims())})

    # --- recovery: reconcile, then the agent retries EACH refund ---
    for occ in (0, 1):
        key, reused = create_or_reuse(log, wid, "issue_refund",
                                      "customer-9", occ, epoch=2)
        assert reused, f"retry of occ={occ} must hit the reuse path"
        st = recv.call(key, 2, "issue_refund", "customer-9", occ)
        assert st == "duplicate_suppressed", st
        trace.append({"step": f"retry-refund-occ{occ}", "key": key,
                      "reused": reused, "receiver": st})
    assert len(recv.ledger) == 2, (
        f"retries must not commit: ledger={len(recv.ledger)}")

    # --- post-recovery: a THIRD authorized refund is a new identity ---
    key, reused = create_or_reuse(log, wid, "issue_refund",
                                  "customer-9", 2, epoch=2)
    assert not reused, "occ=2 is a genuinely new identity"
    st = recv.call(key, 2, "issue_refund", "customer-9", 2)
    assert st == "committed", st
    trace.append({"step": "auth-refund-occ2", "key": key,
                  "reused": reused, "receiver": st})
    assert len(recv.ledger) == 3

    # --- invariant audit (Definition 3) ---
    keys_by_ident = {}
    for a, t, o, k in recv.ledger:
        keys_by_ident.setdefault((a, t, o), set()).add(k)
    assert all(len(ks) == 1 for ks in keys_by_ident.values()), \
        "one durable key per logical identity"
    assert len({k for _, _, _, k in recv.ledger}) == 3, \
        "distinct identities received distinct keys"

    results = {
        "test": "e7-two-refunds-then-retries",
        "pass": True,
        "commits": len(recv.ledger),
        "expected_commits": 3,
        "retries_suppressed": 2,
        "invariant_audit": "one key per identity; distinct identities distinct keys",
        "trace": trace,
    }
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "results_e7_refunds.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=1)
    print(json.dumps({k: v for k, v in results.items() if k != "trace"},
                     indent=1))
    print("wrote", out)


if __name__ == "__main__":
    main()
