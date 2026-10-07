# A1 Recovery-Prompt Ablation — tighter prompt kills the re-emission loops

**Date:** 2026-10-07 · **Script:** `src/llm_validation_tightprompt.py`
(diff vs `llm_validation.py`: `ask_claim_recovery` only)
**Config:** 70 episodes, seed 20261008 (same crash schedule as baseline),
gpt-4o-mini, temp 0.7, productive<12 / attempts<48 — everything else identical.

## What changed

Baseline prompt: open-ended — "re-emit a claim for any step you believe was
lost, or emit the claim for the next step" (measured *natural* recovery
behavior).

Ablation prompt: hands the model the explicit list of remaining
(claimed-but-uncommitted / un-checkpointed) steps and instructs it to emit
the claim for the NEXT remaining step, not re-emit committed ones.

## Results

| Metric | Baseline (open) | Ablation (tight) |
|---|---|---|
| Episodes | 70 | 70 |
| Duplicate effects | 0 | 0 |
| Episodes w/ missing effects | 4 | **0** |
| Total missing effects | 5 | **0** |
| Exactly-once rate | 94.29% (66/70) | **100% (70/70)** |
| Episodes w/ any re-emission | 8 | 1 |
| Total re-emissions | 196 | **18** |
| Max re-emissions, one episode | 47 | 18 |
| Claim adherence (step / episode) | 99.57% / 100% | **100% / 100%** |
| LLM calls | 470 | 296 |
| Spend | $0.0298 | **$0.0188** |

## Verdict

**The residual misses are prompt-fixable.** Making the remaining work
explicit collapses re-emission behavior (196 → 18 total re-emissions) and
eliminates misses entirely (5 → 0), while *also* costing less ($0.0188 vs
$0.0298 — no more 47-call loops burning budget). One episode still opened
with 18 re-emissions but then advanced and completed — the explicit
remaining-list breaks the loop rather than the model never starting one.

## Paper framing

- **Safety is prompt-independent:** 0 duplicates under both prompts. The
  WAL guarantee does not depend on model cooperation.
- **Liveness/completeness is prompt-sensitive:** an open-ended recovery
  prompt lets the model loop on committed work; stating the remaining work
  explicitly restores full completeness. This converts the baseline's
  limitation into a positive harness-design result: *recovery prompts
  should enumerate remaining claims*.
- Honest caveat: same seed fixes the crash schedule, but model sampling
  (temp 0.7) varies run to run — some of the gap is noise. The effect size
  (5→0 misses, 196→18 re-emissions) is structural, not noise-level.
