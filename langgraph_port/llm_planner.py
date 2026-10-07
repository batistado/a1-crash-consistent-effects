#!/usr/bin/env python3
"""Real-LLM supervisor planner for the A1 LangGraph v2 run.

Replaces the scripted round-1 routing decision (fan_out vs escalate) with a
gpt-4o-mini judgment call. Approved design constraints (2026-10-07):

- The model plans ROUTES only. It NEVER sees the raw claim log.
- It is consulted with the reconciled remaining work: in fresh mode, the
  completed round-0 branch state; in recover mode, the branch state AFTER
  deterministic reconciliation (recover_node) has already run.
- temperature=0 for reproducibility; 3 retries with backoff; deterministic
  fallback ("fan_out") on persistent failure, logged as fallback.
- Per-episode EVIDENCE (2026-10-07 fix): the original prompt showed the model
  identical evidence every episode (3 branches, 1 finding each), so fan_out
  was the only rational answer and temperature could not fix it. Now the
  prompt carries a seeded per-episode evidence profile (unanimous
  corroboration vs divergent findings vs 2-of-3 split) via evidence_summary(),
  deterministic in plan_seed so fresh and recover generations judge identical
  evidence. The model still decides; we report the resulting distribution.
- Spend guard: cumulative usage tracked per run dir in llm_spend.json;
  the call aborts above $4.50 (campaign hard stop is $5; expected ~$0.02).

Auth via the connected custom.openai credential surrogate -- never handles
a raw key (same pattern as the openai skill's paraphrase.py).

Round 0 stays structural (always fan_out, as in the scripted scenario); the
only genuine routing decision in this scenario is round 1's.
"""
import json
import os
import random
import sys
import time
import urllib.request

sys.path.insert(0, "/opt/hatch/skills/skill-creator/bin")
import dynamic_credentials as dc

API_URL = "https://api.openai.com/v1/chat/completions"
ALLOWED = ["api.openai.com"]
MODEL = "gpt-4o-mini"
# Sampling temperature: 0.0 = deterministic (reproducible); raise via the
# LLM_PLANNER_TEMP env var (e.g. 1.0) when a genuine mixed route
# distribution is wanted instead of the model's argmax choice.
TEMPERATURE = float(os.environ.get("LLM_PLANNER_TEMP", "0.0"))
MAX_TOKENS = 20
TIMEOUT_S = 60
MAX_ATTEMPTS = 3
# gpt-4o-mini list prices ($/1M tokens); noted for the spend ledger.
PRICE_IN_PER_M = 0.15
PRICE_OUT_PER_M = 0.60
SPEND_GUARD_USD = 4.50
FALLBACK_ROUTE = "fan_out"

PROMPT = (
    "You are the supervisor of a two-round evidence-gathering agent.\n\n"
    "Situation:\n"
    "- Round 0 is complete: the agent fanned out over 3 source branches; each "
    "branch recorded its finding (a non-idempotent HTTP effect) and logged its "
    "source (a non-idempotent file append). Settled branches: {branches}.\n"
    "- Round-0 findings:\n{evidence}\n"
    "{recovery_note}"
    "- Now you must route round 1. Two options:\n"
    '  - "fan_out": dispatch 3 more source branches for deeper evidence '
    "(6 more non-idempotent effects).\n"
    '  - "escalate": send a single alert effect and conclude the investigation.\n\n'
    "Decide: reply with exactly one word, either fan_out or escalate.\n"
    "Weigh two things: (1) whether the round-0 evidence is sufficient to "
    "conclude and act now; (2) the cost of another round -- fan_out fires 6 "
    "more non-idempotent effects and delays incident resolution, while "
    "escalate concludes the investigation immediately. Escalate when the "
    "evidence is sufficient to act on; fan out only when the evidence leaves "
    "genuine uncertainty that deeper coverage could resolve."
)


def evidence_summary(plan_seed):
    """Seeded per-episode round-0 evidence profile for the supervisor prompt.

    Deterministic in plan_seed with a domain-separated RNG stream, so the
    fresh and recover generations of an episode see IDENTICAL evidence (the
    crash must not change what the supervisor judges). Gives the model a
    genuine, episode-varying judgment: unanimous corroboration argues for
    escalate, divergent findings for fan_out, 2-of-3 as the judgment call.
    The model sees only investigative findings -- never the claim log.
    """
    rng = random.Random(plan_seed ^ 0xE41D)
    causes = ["expired TLS certificate on api-gw-3",
              "connection-pool exhaustion on db-primary",
              "DNS misconfiguration for cdn-edge-7"]
    profile = rng.random()
    if profile < 0.35:
        # Strong: all three branches corroborate one root cause.
        cause = rng.choice(causes)
        lines = [
            f"  - branch {b}: {cause} "
            f"(corroborated by {', '.join('branch ' + str(x) for x in range(3) if x != b)})"
            for b in range(3)]
        assessment = ("Assessment: all 3 branches corroborate a single root "
                      "cause with matching details.")
    elif profile < 0.70:
        # Weak: divergent findings, no consensus.
        picked = rng.sample(causes, 3)
        lines = [f"  - branch {b}: {picked[b]}" for b in range(3)]
        assessment = ("Assessment: the 3 branches report divergent findings "
                      "with no consensus on the root cause.")
    else:
        # Mixed: 2 of 3 corroborate; the third diverges.
        cause = rng.choice(causes)
        other = rng.choice([c for c in causes if c != cause])
        holdout = rng.randrange(3)
        agreers = [x for x in range(3) if x != holdout]
        lines = []
        for b in range(3):
            if b == holdout:
                lines.append(f"  - branch {b}: {other} (diverges)")
            else:
                lines.append(
                    f"  - branch {b}: {cause} "
                    f"(corroborated by branch {agreers[1] if agreers[0] == b else agreers[0]})")
        assessment = (
            f"Assessment: branches {agreers[0]} and {agreers[1]} corroborate "
            f"one root cause; branch {holdout} diverges.")
    return "\n".join(lines) + "\n" + assessment


def _spend_path(run_dir):
    return os.path.join(run_dir, "llm_spend.json")


def _read_spend(run_dir):
    try:
        with open(_spend_path(run_dir)) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"prompt_tokens": 0, "completion_tokens": 0, "usd": 0.0,
                "calls": 0}


def _record_spend(run_dir, prompt_toks, completion_toks):
    s = _read_spend(run_dir)
    s["prompt_tokens"] += prompt_toks
    s["completion_tokens"] += completion_toks
    s["calls"] += 1
    s["usd"] = (s["prompt_tokens"] / 1e6 * PRICE_IN_PER_M
                + s["completion_tokens"] / 1e6 * PRICE_OUT_PER_M)
    tmp = _spend_path(run_dir) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f)
    os.replace(tmp, _spend_path(run_dir))
    return s


def _chat_once(prompt):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }).encode()
    req = urllib.request.Request(
        API_URL, data=body, headers={"Content-Type": "application/json"})
    dc.add_surrogate_to_request(req, "custom.openai", allowed_hosts=ALLOWED)
    resp = urllib.request.urlopen(req, timeout=TIMEOUT_S)
    return dc.read_json_response(resp)


def _parse_route(text):
    t = text.strip().lower().replace("-", "_").replace(" ", "_")
    first = t.split()[0] if t.split() else ""
    if first in ("fan_out", "fanout"):
        return "fan_out"
    if first == "escalate":
        return "escalate"
    return None


def decide_route(round_no, settled_branches, mode, run_dir, evidence):
    """Ask the LLM for round 1's route. Returns (route, meta dict).

    settled_branches: reconciled branch-state keys (never the claim log).
    evidence: per-episode round-0 evidence summary from evidence_summary()
        (seeded by plan_seed; identical in fresh and recover generations).
    """
    recovery_note = ""
    if mode == "recover":
        recovery_note = (
            "- Note: the agent process crashed during round 0 and was recovered; "
            "the branches above are the reconciled settled set after deterministic "
            "claim-log reconciliation. Route the remaining work.\n")
    prompt = PROMPT.format(
        branches=", ".join(sorted(settled_branches)) or "(none)",
        evidence=evidence,
        recovery_note=recovery_note)

    last_err = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            t0 = time.time()
            data = _chat_once(prompt)
            latency = time.time() - t0
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            route = _parse_route(text)
            if route is None:
                last_err = f"unparseable reply: {text!r}"
                time.sleep(2 ** attempt)
                continue
            spend = _record_spend(run_dir, usage.get("prompt_tokens", 0),
                                  usage.get("completion_tokens", 0))
            if spend["usd"] > SPEND_GUARD_USD:
                raise RuntimeError(
                    f"LLM spend guard tripped at ${spend['usd']:.4f}")
            return route, {"fallback": False, "latency_s": round(latency, 3),
                           "raw_reply": text.strip()[:80],
                           "prompt_tokens": usage.get("prompt_tokens", 0),
                           "completion_tokens": usage.get("completion_tokens", 0)}
        except Exception as e:  # noqa: BLE001 — retry then fall back
            last_err = f"{type(e).__name__}: {e}"
            if "spend guard" in str(e):
                raise
            time.sleep(2 ** attempt)
    # Deterministic fallback: fan_out (scripted majority class), logged.
    return FALLBACK_ROUTE, {"fallback": True, "latency_s": None,
                            "raw_reply": None, "error": str(last_err)[:200],
                            "prompt_tokens": 0, "completion_tokens": 0}
