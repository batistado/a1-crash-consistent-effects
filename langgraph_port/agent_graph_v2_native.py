#!/usr/bin/env python3
"""E1: native-persistence baseline — v2 graph with LangGraph's own checkpointer.

Reviewer ask (§3): baseline using native persistence + documented task
boundaries + durable operation identities + same receiver contract.

This is the v2 'research-assistant' graph compiled with LangGraph's
SqliteSaver checkpointer (file-backed, survives SIGKILL). No claim log,
no manual recover_node, no epoch fencing. Tool calls use deterministic
positional keys (the "durable operation identities"). Recovery is a fresh
process that resumes from the checkpointer (same thread_id) — the
framework's native crash-recovery path.

Task boundaries (what the checkpointer persists): the graph's node
boundaries — plan, supervisor, dispatch, worker_sub (per effect:
w_claim/w_execute/w_commit), aggregate, esc_claim/esc_execute/esc_commit,
finalize.

The condition reuses the 'deterministic' key-derivation path in
agent_graph_v2 (no claim log); the difference from the stock
'deterministic' condition is ONLY the recovery mechanism: checkpointer
resume vs manual branch-done-file replay.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langgraph.graph import START, END
from langgraph.checkpoint.sqlite import SqliteSaver

import agent_graph_v2 as ag
from agent_graph_v2 import (
    plan_node, supervisor_node, sup_router, dispatch_node, dispatch_router,
    worker_sub_node, aggregate_node, esc_claim_node, esc_execute_node,
    esc_commit_node, finalize_node,
)
from langgraph.graph import StateGraph


def build_graph_v2_native(checkpointer):
    """Same v2 topology, but START goes straight to plan (fresh only).
    Recovery never enters through START — it resumes from the checkpointer,
    so there is no manual recover_node and no epoch fencing."""
    g = StateGraph(ag.AgentStateV2)
    g.add_node("plan", plan_node)
    g.add_node("supervisor", supervisor_node)
    g.add_node("dispatch", dispatch_node)
    g.add_node("worker_sub", worker_sub_node)
    g.add_node("aggregate", aggregate_node)
    g.add_node("esc_claim", esc_claim_node)
    g.add_node("esc_execute", esc_execute_node)
    g.add_node("esc_commit", esc_commit_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "plan")
    g.add_edge("plan", "supervisor")
    g.add_conditional_edges("supervisor", sup_router,
                            {"fan_out": "dispatch",
                             "escalate": "esc_claim",
                             "done": "finalize"})
    g.add_conditional_edges("dispatch", dispatch_router,
                            {"aggregate": "aggregate"})
    g.add_edge("worker_sub", "aggregate")
    g.add_edge("aggregate", "supervisor")
    g.add_edge("esc_claim", "esc_execute")
    g.add_edge("esc_execute", "esc_commit")
    g.add_edge("esc_commit", "aggregate")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)
