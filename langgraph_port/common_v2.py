#!/usr/bin/env python3
"""Scenario definition for the v2 'research-assistant' agent.

A two-round evidence-gathering task with a branching supervisor, parallel
worker fan-out (LangGraph Send), an escalation branch, and a retry-with-
backoff path for transient tool failures:

  Round 0: supervisor -> fan_out over 3 source branches. Each worker
           records a finding (HTTP POST, non-idempotent) and logs the
           source (file append, non-idempotent).
  Round 1: supervisor decision — fan_out again (p=0.6) or escalate (p=0.4:
           a single alert effect).
  Then: finalize.

All planner/supervisor decisions are scripted from the episode's plan_seed.
Honest scoping (see DESIGN_V2.md): the fault under study is harness-side
crash consistency — branch/fan-out/retry crash windows — not agent
cognition, so a deterministic planner is the right cost/validity trade
(no API spend, fully reproducible).
"""
import random

HTTP_FINDING = "record_finding"   # effectful, via the tool-server process
FILE_SOURCE = "append_audit"      # effectful, via the local file tool
ALERT = "send_alert"              # effectful, via the tool-server process

N_BRANCHES = 3
P_ROUND1_FANOUT = 0.6


def make_scenario(rng, n_branches=None):
    """Deterministic scenario generator. Shared by the agent (plan node) and
    the crash harness (which regenerates it from the same seed to compute
    ground-truth intended effects without the agent cooperating).
    n_branches defaults to N_BRANCHES; the A1_N_BRANCHES env var (E3a scale
    experiment) overrides when n_branches is None."""
    import os
    if n_branches is None:
        n_branches = int(os.environ.get("A1_N_BRANCHES", N_BRANCHES))
    n = n_branches
    route1 = "fan_out" if rng.random() < P_ROUND1_FANOUT else "escalate"
    return {"rounds": [
        {"round": 0, "route": "fan_out",
         "branches": list(range(n))},
        {"round": 1, "route": route1,
         "branches": (list(range(n)) if route1 == "fan_out"
                      else ["esc"])},
    ]}


def worker_effects(round_no, branch):
    return [
        {"action": HTTP_FINDING, "target": f"finding-r{round_no}-b{branch}"},
        {"action": FILE_SOURCE, "target": f"source-r{round_no}-b{branch}"},
    ]


def escalate_effect():
    return {"action": ALERT, "target": "alert-escalation"}


def intended_effects(scenario):
    """Ground-truth (action, target) multiset the episode must commit."""
    out = []
    for rd in scenario["rounds"]:
        if rd["route"] == "fan_out":
            for b in rd["branches"]:
                for e in worker_effects(rd["round"], b):
                    out.append((e["action"], e["target"]))
        else:
            e = escalate_effect()
            out.append((e["action"], e["target"]))
    return out


def claim_uid(round_no, branch, eff_idx):
    return f"r{round_no}b{branch}e{eff_idx}"


def branch_key(round_no, branch):
    return f"r{round_no}b{branch}"


def claim_key_v2(workflow_id, round_no, branch, eff_idx, action):
    """Durable claim identity: per (round, branch, effect, action).
    wal: derived once at claim time, stored in the log, never re-derived.
    deterministic: re-derived at call time (fragile only if the recovery
    recomputation changes branch identities — v2 keeps them stable, which
    is itself an informative contrast with v1)."""
    return f"det:{workflow_id}:r{round_no}:b{branch}:e{eff_idx}:{action}"


def content_key_v2(action, target):
    """Content-hash key: binds identity to the exact (action, target)
    strings. Breaks when recovery rewords targets (E2b)."""
    import hashlib
    h = hashlib.sha256(f"{action}|{target}".encode()).hexdigest()[:16]
    return f"ch:{h}"


def reword_target_v2(target):
    """Fixed invertible paraphrase: models an LLM replanning agent
    rephrasing effect targets across recovery (E2b). Deterministic, $0."""
    return target.replace("-", "_") + "_rpl"


def canonical_target_v2(target):
    """Inverse of reword_target_v2: the business identity. Identity for
    targets that were never reworded (no-op on normal runs)."""
    if target.endswith("_rpl"):
        target = target[:-4]
    return target.replace("_", "-")


def is_transient_scripted(round_no, branch, attempt):
    """Scripted transient tool failure: branch 0's first attempt of every
    round fails transiently WITHOUT committing, exercising the retry/backoff
    path in every episode. The backoff sleep and the retry loop in the graph
    are real; only the failure injection is scripted (chaos-instrumentation,
    like the crash schedule itself)."""
    return attempt == 0 and branch == 0


def supervisor_route(scenario, round_no):
    if round_no >= len(scenario["rounds"]):
        return "done"
    return scenario["rounds"][round_no]["route"]
