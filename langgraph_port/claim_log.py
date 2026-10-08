#!/usr/bin/env python3
"""Durable append-only JSONL effect-claim log with fsync per record.

Record shape matches src/measure_overhead.py:
  CLAIM:  {"kind":"claim", "uid","action","target","occurrence","note","key","epoch","committed":False}
  COMMIT: {"kind":"commit", ... same fields ..., "committed":True}
appended as a second record (append-only discipline; the log is never
rewritten in place).

The logical claim identity is (action, target, occurrence) per
Definition 2 of the paper: occurrence disambiguates legitimately
distinct effects sharing an action and target (e.g., two separately
authorized refunds to the same customer). The harness assigns
occurrence at claim time as a per-(action,target) sequence counter
(0 for the first claim of a pair); it is stored durably in the
claim record and therefore survives crashes exactly like the key.

This log is the harness's source of truth for effect identity (DESIGN.md §2,
FORMAL_MODEL.md A2/A5). Only this file, the checkpoint file, the tool-side
ledgers, and the scratch files survive the SIGKILL.
"""
import json
import os

from common import claim_identity


class ClaimLog:
    def __init__(self, path):
        self.path = path
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)

    def _append(self, rec):
        line = (json.dumps(rec, separators=(",", ":")) + "\n").encode()
        # One open/write/fsync/close per record: each record is durable the
        # moment _append returns, so a SIGKILL can never leave a half record
        # the recovery pass cannot detect (see load() torn-tail handling).
        with open(self.path, "ab", buffering=0) as f:
            f.write(line)
            os.fsync(f.fileno())

    def append_claim(self, uid, action, target, note, key, epoch,
                     occurrence=0):
        rec = {"kind": "claim", "uid": uid, "action": action, "target": target,
               "occurrence": occurrence, "note": note, "key": key,
               "epoch": epoch, "committed": False}
        self._append(rec)
        return rec

    def append_commit(self, claim):
        rec = dict(claim)
        rec["kind"] = "commit"
        rec["committed"] = True
        self._append(rec)
        return rec

    def load(self):
        """Read all records. A torn trailing line (crash mid-write) is
        skipped with the rest of the log intact — the standard WAL tail
        discipline. A torn non-trailing line is corruption: raise loudly."""
        if not os.path.exists(self.path):
            return []
        with open(self.path, "rb") as f:
            raw = f.read().split(b"\n")
        # drop the empty string after the final newline
        if raw and raw[-1] == b"":
            raw = raw[:-1]
        recs = []
        for i, line in enumerate(raw):
            if not line.strip():
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                if i == len(raw) - 1:
                    # torn tail: the crashed writer died mid-record; ignore it
                    continue
                raise
        return recs

    def claims(self):
        return [r for r in self.load() if r.get("kind") == "claim"]

    def committed_keys(self):
        return {r["key"] for r in self.load()
                if r.get("kind") == "commit" and r.get("key")}

    def uncommitted(self):
        done = self.committed_keys()
        return [c for c in self.claims() if c["key"] not in done]

    def find_by_identity(self, action, target, occurrence=0):
        """Latest claim with the stable business identity
        (action, target, occurrence). This is what lets recovery recognize
        a reworded/shifted retry of an already-claimed effect instead of
        issuing a fresh claim — while still executing a legitimately
        distinct effect that shares (action, target) under a different
        occurrence."""
        ident = (action, target, occurrence)
        found = None
        for c in self.claims():
            if (c.get("action"), c.get("target"),
                    c.get("occurrence", 0)) == ident:
                found = c
        return found

    def next_occurrence(self, action, target):
        """Per-(action,target) sequence counter for fresh claims: the
        occurrence to assign to the next intentional claim of this pair."""
        return sum(1 for c in self.claims()
                   if (c.get("action"), c.get("target")) == (action, target))

    def is_committed(self, claim):
        return claim["key"] in self.committed_keys()
