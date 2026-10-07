#!/usr/bin/env python3
"""A1 LLM-in-the-loop validation (DESIGN.md section 7).

A real LLM (gpt-4o-mini) drives the harness through the write-ahead
effect-claim protocol from the scripted sandbox (src/sandbox.py), on a
subset of episodes. Purpose: MEASURE with a real model the two recovery
behaviors the simulator assumed --
    P(reword args on recovery) = 0.50
    P(plan shift on recovery)  = 0.30
and confirm the WAL protocol still achieves exactly-once with an LLM
in the loop.

Protocol (faithful to DESIGN.md section 2):
  * The agent must emit a well-formed CLAIM before every tool call;
    the harness refuses to call the tool without one (claim discipline).
  * The harness durably logs (claim, key) BEFORE invoking the tool,
    marks COMMIT after, and advances the checkpoint (log-fenced).
  * Crash injection mirrors the simulator: 75% in-window (after tool
    commit, before checkpoint write), 15% post-checkpoint, 10% pre-step.
  * Recovery: bump epoch, fence stale writers, reconcile uncommitted
    claims with their ORIGINAL keys (tool dedups), advance checkpoint,
    then ask the LLM to resume from the checkpoint with an open-ended
    prompt so its natural recovery behavior (re-emit, reword, reorder)
    can be observed.

Metrics per episode:
  * claim-discipline adherence (valid claim on first attempt per step)
  * re-emission attempts of already-committed claims, and reword rate
    (re-emitted with changed args vs the original claim)
  * plan-shift rate (first post-recovery claim != next expected step)
  * duplicate-effect rate / exactly-once rate under the WAL protocol
    (semantic scoring identical to sandbox.py)

Cost: gpt-4o-mini only. Token usage tracked per call from the API
response; hard stop on new episodes if projected spend would exceed
$50 (stops at $40 to leave margin).

Auth: custom.openai surrogate via dynamic_credentials -- never handles
a raw key. 401/403 -> report and stop, no auth workarounds.

Stdlib only (plus src/sandbox.py for the tool model).
"""

import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox import ToolServer, deterministic_key  # noqa: E402

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
import dynamic_credentials as dc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "llm_validation_results.json"

MODEL = "gpt-4o-mini"
API_URL = "https://api.openai.com/v1/chat/completions"
ALLOWED = ["api.openai.com"]
PRICE_IN = 0.15 / 1_000_000    # gpt-4o-mini $/token (estimate)
PRICE_OUT = 0.60 / 1_000_000
BUDGET_HARD = 50.0
BUDGET_STOP = 40.0             # stop starting new episodes past this

EPISODES = 70
SEED = 20261008
P_IN_WINDOW = 0.75
P_POST_CHECKPOINT = 0.15       # remainder -> pre-step (safe)
TEMPERATURE = 0.7

ACTIONS = ["issue_refund", "send_email", "update_record"]

TOK_IN = 0
TOK_OUT = 0
N_CALLS = 0


class AuthError(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    pass


def spend_usd():
    return TOK_IN * PRICE_IN + TOK_OUT * PRICE_OUT


def check_budget():
    if spend_usd() > BUDGET_STOP:
        raise BudgetExceeded(
            f"projected spend ${spend_usd():.2f} over stop threshold "
            f"${BUDGET_STOP:.0f}")


def chat(messages, max_tokens=160):
    """One chat-completions call via the surrogate credential."""
    global TOK_IN, TOK_OUT, N_CALLS
    check_budget()
    body = json.dumps({
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": TEMPERATURE,
    }).encode()
    req = urllib.request.Request(
        API_URL, data=body, headers={"Content-Type": "application/json"})
    dc.add_surrogate_to_request(req, "custom.openai", allowed_hosts=ALLOWED)
    for attempt in range(5):
        try:
            resp = urllib.request.urlopen(req, timeout=90)
            data = dc.read_json_response(resp)
            break
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise AuthError(f"OpenAI auth failed with {e.code}; stopping")
            if e.code == 429:
                time.sleep(2 ** attempt)
                continue
            raise
        except Exception as e:
            if "429" in str(e):
                time.sleep(2 ** attempt)
                continue
            raise
    else:
        raise RuntimeError("too many rate-limit retries")
    usage = data.get("usage", {}) or {}
    TOK_IN += usage.get("prompt_tokens", 0)
    TOK_OUT += usage.get("completion_tokens", 0)
    N_CALLS += 1
    check_budget()
    return data["choices"][0]["message"]["content"].strip()


def parse_claim(text):
    """Extract a well-formed claim dict or return None."""
    text = text.strip()
    obj = None
    try:
        obj = json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:
                obj = None
    if not isinstance(obj, dict):
        return None
    if obj.get("action") not in ACTIONS:
        return None
    if not isinstance(obj.get("target"), str) or not obj["target"].strip():
        return None
    return {
        "action": obj["action"],
        "target": obj["target"].strip(),
        "note": str(obj.get("note", ""))[:200],
    }


def make_goal(rng):
    """A 3-5 step effectful workflow with unique per-step targets."""
    req = rng.randint(10000, 99999)
    n = rng.randint(3, 5)
    steps, seen = [], set()
    for i in range(n):
        action = rng.choice(ACTIONS)
        if action == "update_record":
            target = f"rec-{rng.randint(100, 999)}"
            detail = f"set status=resolved on {target}"
        elif action == "issue_refund":
            target = f"customer-{rng.randint(1000, 9999)}"
            detail = f"refund ${rng.randint(10, 200)}.{rng.randint(10, 99):02d} to {target} (duplicate charge)"
        else:
            target = f"customer-{rng.randint(1000, 9999)}"
            detail = f"email {target} confirming case REQ-{req} resolution"
        if target in seen:  # keep identities unique within the episode
            target = f"{target}-b"
        seen.add(target)
        steps.append({"uid": i, "action": action, "target": target,
                      "note": detail, "req": req})
    return steps


def goal_text(goal):
    lines = [f"Request REQ-{goal[0]['req']}: complete these steps in order:"]
    for s in goal:
        lines.append(f"  step {s['uid']}: {s['action']} -> {s['target']} ({s['note']})")
    return "\n".join(lines)


CLAIM_FORMAT = ('{"step": <int>, "action": "<issue_refund|send_email|update_record>", '
                '"target": "<id>", "note": "<short description>"}')


def ask_claim_pre(step, goal, completed):
    """Directed claim for the next expected step (measures discipline)."""
    prompt = (
        "You are an operations agent executing a customer-service workflow. "
        "You MUST emit a claim BEFORE each tool call. The harness will not "
        "call any tool without your claim.\n\n"
        f"Workflow goal:\n{goal_text(goal)}\n\n"
        f"Completed so far: {completed if completed else 'none'}\n\n"
        f"Emit your claim for step {step['uid']}: {step['action']} -> {step['target']}.\n"
        f"Output ONLY the JSON object, no other text:\n{CLAIM_FORMAT}"
    )
    return parse_claim(chat([{"role": "user", "content": prompt}]))


def ask_claim_recovery(goal, checkpoint, committed_idents):
    """Open-ended resume prompt (measures natural recovery behavior)."""
    committed = ", ".join(f"{a} {t}" for a, t in committed_idents) or "none"
    prompt = (
        "You are an operations agent. Your harness process crashed and "
        "restarted. Durable state that survived:\n"
        f"- Checkpoint: step {checkpoint} is the last fully recorded step.\n"
        f"- Committed effects (these definitely happened): {committed}.\n\n"
        f"Original workflow goal:\n{goal_text(goal)}\n\n"
        "Re-emit a claim for any step you believe was lost, or emit the "
        "claim for the next step. "
        f"Output ONLY the JSON object, no other text:\n{CLAIM_FORMAT}"
    )
    return parse_claim(chat([{"role": "user", "content": prompt}]))


def run_episode(rng, ep_id):
    tool = ToolServer()
    wid = f"wf-llm-{ep_id:04d}-{rng.randint(0, 1 << 32):08x}"
    goal = make_goal(rng)
    goal_idents = [(s["action"], s["target"]) for s in goal]

    crash_step = rng.choice(goal)
    r = rng.random()
    landing = ("in_window" if r < P_IN_WINDOW
               else "post_checkpoint" if r < P_IN_WINDOW + P_POST_CHECKPOINT
               else "pre_step")

    wal = []            # durable write-ahead log
    checkpoint = -1     # durable
    epoch = 0
    committed_idents = []   # in commit order
    committed_set = set()
    pre_crash_args = {}     # ident -> claim args (for reword detection)

    def find_claim(ident):
        for c in wal:
            if (c["action"], c["target"]) == ident:
                return c
        return None

    st = {"claims_attempted": 0, "claims_valid_first": 0,
          "violations": 0, "reprompts": 0}

    def get_claim_directed(step, completed_desc):
        claim = ask_claim_pre(step, goal, completed_desc)
        st["claims_attempted"] += 1
        if claim and (claim["action"], claim["target"]) == (step["action"], step["target"]):
            st["claims_valid_first"] += 1
            return claim
        # one re-prompt on malformed/mismatched claim
        st["reprompts"] += 1
        claim = ask_claim_pre(step, goal, completed_desc)
        st["claims_attempted"] += 1
        if claim and (claim["action"], claim["target"]) == (step["action"], step["target"]):
            st["claims_valid_first"] += 1
            return claim
        st["violations"] += 1
        return None

    crashed = False
    completed_desc = []
    # ---- pre-crash: directed execution in goal order ----
    for step in goal:
        claim = get_claim_directed(step, completed_desc)
        if claim is None:
            continue  # harness refuses: no valid claim, no tool call
        ident = (claim["action"], claim["target"])
        c = find_claim(ident)
        if c is None:
            key = deterministic_key(wid, step["uid"], claim["action"])
            wal.append({"uid": step["uid"], "action": claim["action"],
                        "target": claim["target"], "note": claim["note"],
                        "key": key, "epoch": epoch, "committed": False})
            c = wal[-1]
        pre_crash_args[ident] = {"note": claim["note"]}

        if step["uid"] == crash_step["uid"] and landing == "pre_step":
            crashed = True
            break  # crash before the tool call; claim is durable, effect not

        tool.call(wid, step["uid"], claim["action"],
                  {"target": claim["target"], "note": claim["note"]},
                  c["key"], epoch)

        if step["uid"] == crash_step["uid"] and landing == "in_window":
            crashed = True
            break  # commit happened; COMMIT/checkpoint NOT written

        c["committed"] = True
        checkpoint = step["uid"]
        committed_idents.append(ident)
        committed_set.add(ident)
        completed_desc.append(f"step {step['uid']}: {claim['action']} {claim['target']}")

        if step["uid"] == crash_step["uid"] and landing == "post_checkpoint":
            crashed = True
            break

    # ---- recovery ----
    rec = {"reemissions": 0, "rewords": 0, "shift": False,
           "first_claim_ident": None, "executed_order": []}
    if crashed:
        epoch += 1
        tool.fence_epoch(wid, epoch)
        for c in wal:  # reconcile uncommitted claims with ORIGINAL keys
            if not c["committed"]:
                res = tool.call(wid, c["uid"], c["action"],
                               {"target": c["target"], "note": c["note"]},
                               c["key"], epoch)
                if res["status"] in ("committed", "duplicate_suppressed"):
                    c["committed"] = True
                    ident = (c["action"], c["target"])
                    if ident not in committed_set:
                        committed_idents.append(ident)
                        committed_set.add(ident)
        done = [c["uid"] for c in wal if c["committed"]]
        if done:
            checkpoint = max(checkpoint, max(done))

        remaining = [s for s in goal
                     if (s["action"], s["target"]) not in committed_set]
        expected_first = ((remaining[0]["action"], remaining[0]["target"])
                          if remaining else None)
        attempts = 0       # total recovery LLM calls (hard safety bound)
        productive = 0     # genuine remaining-step executions
        # Fix (MISSES_ANALYSIS.md): re-emissions of already-committed claims
        # are safely suppressed by the harness and must NOT consume the
        # recovery-progress budget. Previously a single counter conflated the
        # two, so an agent that re-emitted 11x exhausted the cap and genuine
        # remaining steps were never attempted (scored as "missing").
        # Productive work gets its own budget; total calls keep a backstop.
        first = True
        while remaining and productive < 12 and attempts < 48:
            attempts += 1
            claim = ask_claim_recovery(goal, checkpoint, committed_idents)
            st["claims_attempted"] += 1
            if claim is None:
                st["reprompts"] += 1
                claim = ask_claim_recovery(goal, checkpoint, committed_idents)
                st["claims_attempted"] += 1
                if claim is None:
                    st["violations"] += 1
                    break
            else:
                st["claims_valid_first"] += 1
            ident = (claim["action"], claim["target"])
            if first:
                rec["first_claim_ident"] = ident
                if expected_first is not None and ident != expected_first:
                    rec["shift"] = True
                first = False
            if ident in committed_set:
                # re-emission of an already-committed effect: harness skips
                rec["reemissions"] += 1
                old = pre_crash_args.get(ident, {})
                if old.get("note") != claim["note"]:
                    rec["rewords"] += 1
                continue
            if ident not in [(s["action"], s["target"]) for s in remaining]:
                st["violations"] += 1  # unknown target; refuse and stop
                break
            # genuine remaining step: WAL discipline
            c = find_claim(ident)
            if c is None:
                step = next(s for s in remaining if (s["action"], s["target"]) == ident)
                key = deterministic_key(wid, step["uid"], claim["action"])
                wal.append({"uid": step["uid"], "action": claim["action"],
                            "target": claim["target"], "note": claim["note"],
                            "key": key, "epoch": epoch, "committed": False})
                c = wal[-1]
            tool.call(wid, c["uid"], claim["action"],
                      {"target": claim["target"], "note": claim["note"]},
                      c["key"], epoch)
            c["committed"] = True
            committed_idents.append(ident)
            committed_set.add(ident)
            rec["executed_order"].append(ident)
            remaining = [s for s in remaining
                         if (s["action"], s["target"]) != ident]
            productive += 1  # only genuine remaining-step executions consume
                             # the progress budget (see note at loop head)
        # order deviation among the steps the agent actually completed
        goal_order = [(s["action"], s["target"]) for s in goal
                      if (s["action"], s["target"]) in rec["executed_order"]]
        rec["order_deviated"] = (rec["executed_order"] != goal_order)

    # ---- semantic scoring (same rule as sandbox.py) ----
    def sig(a, args):
        return (a, args.get("target"))
    intended = {}
    for s in goal:
        sig_ = (s["action"], s["target"])
        intended[sig_] = intended.get(sig_, 0) + 1
    committed_counts = {}
    for e in tool.ledger:
        if e["workflow_id"] != wid:
            continue
        sig_ = sig(e["action"], e["args"])
        committed_counts[sig_] = committed_counts.get(sig_, 0) + 1
    duplicates = sum(max(0, committed_counts.get(k, 0) - v)
                     for k, v in intended.items())
    duplicates += sum(v for k, v in committed_counts.items()
                      if k not in intended)
    missing = sum(max(0, v - committed_counts.get(k, 0))
                  for k, v in intended.items())

    return {
        "episode": ep_id, "landing": landing, "crashed": crashed,
        "goal_steps": len(goal),
        "claims_attempted": st["claims_attempted"],
        "claims_valid_first": st["claims_valid_first"],
        "violations": st["violations"],
        "reemissions": rec["reemissions"], "rewords": rec["rewords"],
        "shift": rec["shift"], "order_deviated": rec["order_deviated"],
        "duplicates": duplicates, "missing": missing,
        "exactly_once": (duplicates == 0 and missing == 0),
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=EPISODES)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    episodes = []
    try:
        for i in range(args.episodes):
            t0 = time.time()
            res = run_episode(rng, i)
            episodes.append(res)
            print(f"[{i+1}/{args.episodes}] landing={res['landing']} "
                  f"dup={res['duplicates']} miss={res['missing']} "
                  f"reword={res['rewords']} shift={res['shift']} "
                  f"spend=${spend_usd():.3f} ({time.time()-t0:.0f}s)",
                  flush=True)
    except (AuthError, BudgetExceeded) as e:
        print(f"STOPPING: {e}", flush=True)
    except KeyboardInterrupt:
        print("interrupted; writing partial results", flush=True)

    n = len(episodes)
    crashed = [e for e in episodes if e["crashed"]]
    nc = len(crashed) or 1
    landings = {}
    for e in episodes:
        landings[e["landing"]] = landings.get(e["landing"], 0) + 1
    tot_claims = sum(e["claims_attempted"] for e in episodes) or 1

    summary = {
        "model": MODEL,
        "temperature": TEMPERATURE,
        "episodes": n,
        "seed": args.seed,
        "assumed_rates": {"p_reword_args": 0.50, "p_plan_shift": 0.30},
        "measured": {
            "claim_adherence_step_rate": round(
                sum(e["claims_valid_first"] for e in episodes) / tot_claims, 4),
            "claim_adherence_episode_rate": round(
                sum(1 for e in episodes if e["violations"] == 0) / (n or 1), 4),
            "episodes_with_crash": len(crashed),
            "reemission_rate": round(
                sum(1 for e in crashed if e["reemissions"] > 0) / nc, 4),
            "reword_rate": round(
                sum(1 for e in crashed if e["rewords"] > 0) / nc, 4),
            "plan_shift_rate": round(
                sum(1 for e in crashed if e["shift"]) / nc, 4),
            "order_deviation_rate": round(
                sum(1 for e in crashed if e["order_deviated"]) / nc, 4),
            "duplicate_effect_rate": round(
                sum(1 for e in episodes if e["duplicates"] > 0) / (n or 1), 4),
            "exactly_once_rate": round(
                sum(1 for e in episodes if e["exactly_once"]) / (n or 1), 4),
            "mean_missing_per_episode": round(
                sum(e["missing"] for e in episodes) / (n or 1), 4),
        },
        "crash_landings": landings,
        "spend": {
            "llm_calls": N_CALLS,
            "prompt_tokens": TOK_IN,
            "completion_tokens": TOK_OUT,
            "estimated_usd": round(spend_usd(), 4),
        },
        "episodes": episodes,
    }
    with open(RESULTS, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"wrote {RESULTS}")
    print(json.dumps(summary["measured"], indent=2))
    print(json.dumps(summary["spend"], indent=2))


if __name__ == "__main__":
    sys.exit(main())
