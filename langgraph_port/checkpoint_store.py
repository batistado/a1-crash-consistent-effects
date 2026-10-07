#!/usr/bin/env python3
"""Durable harness checkpoint store: the last fully-recorded step index.

Written atomically (temp + fsync + rename + fsync dir). In the WAL
condition the checkpoint may only advance past steps whose COMMIT is in the
claim log (log-fenced checkpoint, DESIGN.md §2); the agent enforces this by
advancing the checkpoint only from the checkpoint node, which runs after the
commit node, and the recovery pass, which advances it only past reconciled
(committed) claims.
"""
import os

from common import atomic_write_json, read_json


class CheckpointStore:
    def __init__(self, run_dir):
        self.path = os.path.join(run_dir, "checkpoint.json")

    def get(self):
        d = read_json(self.path, {"checkpoint": -1, "epoch": 0})
        return d

    def set(self, checkpoint, epoch):
        atomic_write_json(self.path, {"checkpoint": checkpoint, "epoch": epoch})
