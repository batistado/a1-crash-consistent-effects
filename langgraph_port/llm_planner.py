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
- Spend guard: cumulative usage tracked per run dir in llm_spend.json;
  the call aborts above $4.50 (campaign hard stop is $5; expected ~$0.02).

Auth via the connected custom.openai credential surrogate -- never handles
a raw key (same pattern as the openai skill's paraphrase.py).

Round 0 stays structural (always fan_out, as in the scripted scenario); the
only genuine routing decision in this scenario is round 1's.
"""
import json
import os
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
    "branch recorded one finding (a non-idempotent HTTP effect) and logged its "
    "source (a non-idempotent file append). Settled branches: {branches}.\n"
    "{recovery_note}"
    "- Now you must route round 1. Two options:\n"
    '  - "fan_out": dispatch 3 more source branches for deeper evidence '
    "(6 more non-idempotent effects).\n"
    '  - "escalate": send a single alert effect and conclude the investigation.\n\n'
    "Decide: reply with exactly one word, either fan_out or escalate.\n"
    "Escalate only if the evidence gathered so far appears sufficient to "
    "conclude; otherwise fan out for deeper coverage."
)


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


def decide_route(round_no, settled_branches, mode, run_dir):
    """Ask the LLM for round 1's route. Returns (route, meta dict).

    settled_branches: reconciled branch-state keys (never the claim log).
    """
    recovery_note = ""
    if mode == "recover":
        recovery_note = (
            "- Note: the agent process crashed during round 0 and was recovered; "
            "the branches above are the reconciled settled set after deterministic "
            "claim-log reconciliation. Route the remaining work.\n")
    prompt = PROMPT.format(
        branches=", ".join(sorted(settled_branches)) or "(none)",
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
