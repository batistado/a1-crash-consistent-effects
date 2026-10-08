#!/usr/bin/env python3
"""E6 — identity-consistency tests for the (action, target, occurrence)
logical effect identity (Phase 6, reviewer point 2).

Two scripted tests against the real ClaimLog implementation plus a
minimal in-memory idempotent receiver honoring the paper's tool
contract (atomic check-and-commit; duplicate_suppressed on re-seen
key; per-workflow seen-key set):

  (a) suppression of equivalent retries: the same logical identity
      INCLUDING occurrence, retried after a simulated crash, must
      commit exactly once (the retry is recognized as equivalent
      and skipped);
  (b) distinct authorized effects sharing (action, target) with
      DIFFERENT occurrences must BOTH execute (the old
      (action,target)-only skip logic would wrongly collapse them
      to one — this test fails on the old logic).

The crash is simulated by dropping the in-memory ClaimLog handle
and re-opening the same durable file, exactly the durability
boundary the protocol relies on.

$0 API. Run: python3 e6_identity_tests.py
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


def fresh_claim(log, recv, wid, action, target, occurrence, epoch=1):
    """Normal-path claim -> call -> commit for one intended effect."""
    existing = log.find_by_identity(action, target, occurrence)
    assert existing is None, f"unexpected existing claim for {(action, target, occurrence)}"
    key = f"k:{wid}:{action}:{target}:occ{occurrence}"
    occ = log.next_occurrence(action, target)
    assert occ == occurrence, f"occurrence mismatch: harness assigned {occ}, intended {occurrence}"
    log.append_claim(f"uid-{action}-{target}-{occurrence}", action, target,
                     "e6", key, epoch, occurrence=occurrence)
    st = recv.call(key, epoch, action, target, occurrence)
    assert st == "committed", st
    for c in log.claims():
        if c["key"] == key:
            log.append_commit(c)
    return key


def recovery_retry(log, recv, wid, action, target, occurrence, epoch=2):
    """Post-crash retry path: reconcile-first skip lookup, then the
    agent's post-recovery step check. Returns (skipped, key_used)."""
    existing = log.find_by_identity(action, target, occurrence)
    if existing is not None:
        if log.is_committed(existing):
            return True, existing["key"]  # equivalent retry -> skip
        st = recv.call(existing["key"], epoch, action, target, occurrence)
        for c in log.claims():
            if c["key"] == existing["key"]:
                log.append_commit(c)
        return False, existing["key"]
    # genuinely new identity -> fresh claim
    key = f"k:{wid}:{action}:{target}:occ{occurrence}"
    occ = log.next_occurrence(action, target)
    log.append_claim(f"uid-retry-{action}-{target}-{occurrence}", action,
                     target, "e6-retry", key, epoch, occurrence=occurrence)
    st = recv.call(key, epoch, action, target, occurrence)
    for c in log.claims():
        if c["key"] == key:
            log.append_commit(c)
    return False, key


def test_a_suppression(tmp):
    log = ClaimLog(os.path.join(tmp, "a.log"))
    recv = MockReceiver()
    wid = "wf-e6a"
    # fresh generation commits the refund
    fresh_claim(log, recv, wid, "issue_refund", "customer-1", 0)
    # CRASH: drop the handle, re-open the durable log
    del log
    log = ClaimLog(os.path.join(tmp, "a.log"))
    # recovery retries the SAME logical identity (incl. occurrence 0)
    skipped, key = recovery_retry(log, recv, wid, "issue_refund",
                                  "customer-1", 0)
    assert skipped, "equivalent retry was NOT suppressed"
    assert len(recv.ledger) == 1, f"expected exactly 1 commit, got {len(recv.ledger)}"
    # key-identity invariant: the retry reused the durable key
    assert key == "k:wf-e6a:issue_refund:customer-1:occ0"
    return {"test": "a-suppression", "pass": True,
            "commits": len(recv.ledger), "retry_skipped": skipped}


def test_b_distinct_occurrences(tmp):
    log = ClaimLog(os.path.join(tmp, "b.log"))
    recv = MockReceiver()
    wid = "wf-e6b"
    # two SEPARATELY AUTHORIZED refunds to the same customer
    fresh_claim(log, recv, wid, "issue_refund", "customer-1", 0)
    fresh_claim(log, recv, wid, "issue_refund", "customer-1", 1)
    assert len(recv.ledger) == 2, f"expected 2 commits, got {len(recv.ledger)}"
    # distinct identities -> distinct keys (invariant iii)
    keys = [e[3] for e in recv.ledger]
    assert len(set(keys)) == 2, "distinct identities got the same key"
    # the second claim must NOT match the first's identity
    first = log.find_by_identity("issue_refund", "customer-1", 0)
    second = log.find_by_identity("issue_refund", "customer-1", 1)
    assert first["key"] != second["key"]
    return {"test": "b-distinct-occurrences", "pass": True,
            "commits": len(recv.ledger)}


def test_b_old_logic_would_collapse(tmp):
    """Demonstrate the reviewer-identified bug: (action,target)-only
    matching collapses the two distinct effects of test (b)."""
    log = ClaimLog(os.path.join(tmp, "b2.log"))
    log.append_claim("u1", "issue_refund", "customer-1", "e6", "k1", 1,
                     occurrence=0)
    # old logic: find_by_identity(action, target) ignores occurrence
    ident_old = ("issue_refund", "customer-1")
    collapsed = any((c.get("action"), c.get("target")) == ident_old
                    for c in log.claims())
    # new logic: the occ=1 lookup must NOT match the occ=0 claim
    correct = log.find_by_identity("issue_refund", "customer-1", 1) is None
    assert collapsed and correct, "old-vs-new behavior demonstration failed"
    return {"test": "b-old-logic-collapses", "pass": True,
            "old_logic_matches_occ1": collapsed,
            "new_logic_matches_occ1": not correct}


def main():
    tmp = tempfile.mkdtemp(prefix="e6_identity_")
    results = [test_a_suppression(tmp), test_b_distinct_occurrences(tmp),
               test_b_old_logic_would_collapse(tmp)]
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "results_e6_identity.json")
    with open(out, "w") as f:
        json.dump({"results": results,
                   "verdict": "PASS" if all(r["pass"] for r in results) else "FAIL"},
                  f, indent=1)
    for r in results:
        print(f'{r["test"]}: {"PASS" if r["pass"] else "FAIL"}')
    print("wrote", out)


if __name__ == "__main__":
    main()
