#!/usr/bin/env python3
"""Real file-write tool with genuine side effects.

Appends keyed lines to a scratch file in the run's scratch dir. Implements
the atomic-idempotent-receiver contract on the file side:
  * epoch fencing — calls bearing an epoch older than the durable fencing
    epoch (bumped by recovery) are rejected with FencedError;
  * idempotent check-and-append — a line whose key is already present is
    NOT appended again; the call returns duplicate_suppressed.

The single-writer + crash-stop model makes check-then-append adequate here:
recovery runs strictly after the crashed process is dead (SIGKILL), so no
two writers are ever live concurrently. The scratch files are the file-side
ground-truth ledger for duplicate scoring.
"""
import os
import uuid

from common import atomic_write_json, read_json


class FencedError(Exception):
    """Raised when a tool call carries a stale fencing epoch."""


class FileTool:
    def __init__(self, run_dir, filename="audit.log"):
        self.run_dir = run_dir
        self.scratch = os.path.join(run_dir, "scratch")
        os.makedirs(self.scratch, exist_ok=True)
        self.path = os.path.join(self.scratch, filename)
        self.epoch_path = os.path.join(run_dir, "tool_epoch.json")

    # -- fencing ---------------------------------------------------------
    def get_epoch(self):
        return read_json(self.epoch_path, {"epoch": 0})["epoch"]

    def set_epoch(self, epoch):
        """Fence acquisition: called once by recovery before reconciling."""
        atomic_write_json(self.epoch_path, {"epoch": epoch})

    # -- idempotent append -----------------------------------------------
    def append(self, action, target, note, key, epoch):
        if epoch < self.get_epoch():
            raise FencedError(
                f"stale epoch {epoch} < {self.get_epoch()} for file tool")
        if key is None:
            # baseline condition: no key, no dedup possible — but the ledger
            # still needs a unique line identity for ground-truth scoring.
            key = f"nokey:{uuid.uuid4().hex}"
        else:
            if os.path.exists(self.path):
                prefix = (key + "\t").encode()
                with open(self.path, "rb") as f:
                    for line in f:
                        if line.startswith(prefix):
                            return {"status": "duplicate_suppressed",
                                    "key": key}
        rec = f"{key}\t{action}\t{target}\t{note}\n"
        with open(self.path, "ab", buffering=0) as f:
            f.write(rec.encode())
            os.fsync(f.fileno())
        return {"status": "committed", "key": key}

    # -- ground-truth ledger ----------------------------------------------
    def ledger(self):
        """Parse scratch lines -> [{"key","action","target","note"}]."""
        out = []
        if not os.path.exists(self.path):
            return out
        with open(self.path, "rb") as f:
            for line in f:
                parts = line.decode(errors="replace").rstrip("\n").split("\t")
                if len(parts) >= 4:
                    out.append({"key": parts[0], "action": parts[1],
                                "target": parts[2], "note": parts[3]})
        return out
