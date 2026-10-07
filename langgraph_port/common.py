#!/usr/bin/env python3
"""Shared helpers for the A1 LangGraph production port.

Mirrors the scripted sandbox (src/sandbox.py) semantics:
- plan generation (effectful HTTP actions, effectful file action, no-op reads)
- semantic claim identity (action, target) — reword-invariant
- deterministic key derivation *at claim time*
- semantic ground-truth scoring (intended vs committed effect multisets)
"""
import json
import os
import tempfile
from collections import Counter

EFFECTFUL_HTTP_ACTIONS = ["issue_refund", "send_email", "update_record"]
FILE_ACTION = "append_audit"          # effectful, via the local file tool
READ_ACTION = "read_record"          # no side effect; never claimed

P_EFFECTFUL = 0.6
P_FILE_OF_EFFECTFUL = 0.25


def make_plan(rng, n_min=4, n_max=8):
    """Deterministic plan generator. Shared by the agent (plan node) and the
    crash harness (which regenerates the plan from the same seed to learn the
    crash-step uid without the agent cooperating)."""
    n = rng.randint(n_min, n_max)
    plan = []
    for i in range(n):
        if rng.random() < P_EFFECTFUL:
            if rng.random() < P_FILE_OF_EFFECTFUL:
                action = FILE_ACTION
            else:
                action = rng.choice(EFFECTFUL_HTTP_ACTIONS)
            # target is unique per step: claim identity (action, target) can
            # never collide between two distinct intended steps in one plan.
            args = {"target": f"customer-{rng.randint(1000, 9999)}-s{i}",
                    "note": f"step {i} payload"}
        else:
            action = READ_ACTION
            args = {"record": f"rec-{rng.randint(100, 999)}"}
        plan.append({"uid": i, "action": action, "args": args})
    # guarantee at least 2 effectful steps so the crash fault is meaningful
    eff = [s for s in plan if is_effectful(s)]
    if len(eff) < 2:
        for s in plan[:2]:
            s["action"] = rng.choice(EFFECTFUL_HTTP_ACTIONS)
            s["args"] = {"target": f"customer-{rng.randint(1000, 9999)}-s{s['uid']}",
                         "note": f"step {s['uid']} payload"}
    return plan


def is_effectful(step):
    return step["action"] != READ_ACTION


def is_file_action(step):
    return step["action"] == FILE_ACTION


def claim_identity(action, args):
    """Stable business identity of an effect. Reword-invariant: the cosmetic
    'note' payload is excluded on purpose."""
    return (action, args.get("target"))


def deterministic_key(workflow_id, uid, action):
    return f"det:{workflow_id}:{uid}:{action}"


def reword_args(args):
    """Model the recovered agent rewording arguments on retry (cf. sandbox
    P_REWORD_ARGS). Only the cosmetic note changes; identity is preserved."""
    out = dict(args)
    if isinstance(out.get("note"), str) and out["note"]:
        out["note"] = out["note"] + " (revised after recovery)"
    return out


def atomic_write_json(path, obj):
    """Crash-safe JSON write: temp file + fsync + rename + fsync dir."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        dirfd = os.open(d, os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def score_episode(intended_sigs, committed_sigs):
    """Semantic ground-truth scoring, identical rule to src/sandbox.py:
    a duplicate is any committed effect beyond the intended count for its
    (action, target) identity. Reworded retries are not punished — only true
    double commits are."""
    intended = Counter(intended_sigs)
    committed = Counter(committed_sigs)
    duplicates = sum(max(0, committed.get(s, 0) - c)
                     for s, c in intended.items())
    duplicates += sum(c for s, c in committed.items()
                      if s not in intended)  # wholly unintended effects
    missing = sum(max(0, c - committed.get(s, 0))
                  for s, c in intended.items())
    return {"duplicates": duplicates, "missing": missing,
            "exactly_once": (duplicates == 0 and missing == 0)}
