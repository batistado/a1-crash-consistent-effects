# A1 Second-Model LLM Validation — gpt-4.1-mini

**Date:** 2026-10-06 ~23:20 PDT · **Script:** `src/llm_validation_gpt41mini.py`
(copy of `src/llm_validation_tightprompt.py`; only `MODEL`, `RESULTS`,
pricing constants, and docstring changed)
**Config:** 70 episodes, seed 20261008 (same crash schedule as the
gpt-4o-mini runs), temp 0.7, productive<12 / attempts<48 split counters,
tight recovery prompt. Ran detached (setsid nohup), completed clean (~5 min).
**Results:** `llm_validation_results_gpt41mini.json`.

## Why this model

The task called for a *different* model than gpt-4o-mini. Available
connectors on this VM are only `custom.openai` and `custom.typesafe`
(Jev). Jev is a structured-decision model, not a text generator, so it
cannot drive the claim-JSON harness as a drop-in replacement. No
Anthropic/Google/non-OpenAI connector exists. Honest note: gpt-4.1-mini
is a **distinct model but the same model family and vendor** — this tests
cross-model robustness, not cross-vendor generalization.

- Exact model id: `gpt-4.1-mini` (chat completions endpoint).
- Pricing used: $0.40 / $1.60 per 1M in/out tokens.

## Results

| Metric | gpt-4o-mini (tight) | gpt-4.1-mini (tight) |
|---|---|---|
| Episodes | 70 | 70 |
| Seed / crash schedule | 20261008 | 20261008 (same) |
| Duplicate effects | 0 | **0** |
| Episodes w/ missing effects | 0 | **0** |
| Exactly-once rate | 100% (70/70) | **100% (70/70)** |
| Episodes w/ any re-emission | 1 | **0** |
| Total re-emissions | 18 | **0** |
| Claim adherence (step / episode) | 100% / 100% | **100% / 100%** |
| Plan shifts / order deviations / rewords | 0 / — / 0 | **0 / 0 / 0** |
| LLM calls | 296 | **278** |
| Spend | $0.0188 | **$0.0465** |

Crash landings (gpt-4.1-mini): 54 in-window, 9 post-checkpoint, 7 pre-step —
same schedule as the tight-prompt baseline (seed fixed).

## Verdict

**Safety generalizes beyond the first model.** gpt-4.1-mini reproduced the
headline result exactly: 0 duplicates, 100% exactly-once, 100% claim
adherence. It actually cooperated *better* than gpt-4o-mini — zero
re-emissions at all (vs 18 in one gpt-4o-mini episode), meaning the tight
prompt's explicit remaining-list fully eliminated the re-emission pathology
on the second model too.

Honest caveats for the paper:
- **Same family, same vendor.** This is two data points from OpenAI's
  small-model line, not cross-lab generalization. The safety guarantee
  itself is model-independent by construction (WAL + fencing suppresses
  duplicates regardless of what the model emits), and both models confirm
  the liveness side, but reviewers will read "two OpenAI models" as such.
- The perfect score (0 re-emissions) may partly reflect gpt-4.1-mini's
  stronger instruction-following on the explicit remaining-list prompt —
  a model-behavior observation, not a protocol property. The protocol
  property (0 duplicates) is the one that transfers.
- One-model × one-prompt × 70 episodes each is still a small empirical
  base; the LangGraph production port (pre-approved) gives a third,
  independent confirmation surface.

Spend $0.0465 — within the one-time ~$50 A1 exception, under the $1 hard cap.
