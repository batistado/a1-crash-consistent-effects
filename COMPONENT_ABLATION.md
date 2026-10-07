# A1 Component Ablation — is each protocol piece load-bearing?

Scripted harness, $0 API spend. Script: `src/component_ablation.py`
(derives from `src/sandbox.py`; imports its pure helpers so the stochastic
model — plans, reword/shift, key derivation, crash landings — is identical).
Results: `component_ablation_results.json`. Seed 20261009,
1,500 episodes/condition, ~1.2 s wall clock.

## Conditions

| Condition | Claim log | Log-fenced checkpoints | Epoch fencing | Keys |
|---|---|---|---|---|
| (iii-full) | ✅ | ✅ | ✅ | deterministic claim keys |
| (a) no-fencing | ✅ | ✅ | ❌ removed | deterministic claim keys |
| (b) no-log | ❌ removed | ❌ n/a | ✅ | deterministic position keys, re-derived by agent (== sandbox `(ii-b)`) |
| (c) neither | ❌ | ❌ | ❌ | none (== sandbox baseline `(i)`) |

## Faults (applied uniformly to every condition)

- **F1 — checkpoint-window crash** (same as sandbox.py): 75% in-window
  (after tool commit, before checkpoint write), 15% post-checkpoint (safe),
  10% pre-tool-call (safe).
- **F2 — writer-zombie** (new, stresses fencing): with P=0.5 the pre-crash
  harness process instance *survives* and, **after** recovery has begun with
  a new epoch, retries the in-flight step with its **old epoch**. The zombie
  re-derives the call the way a stale at-least-once agent would — a fresh
  content-hash key over its (possibly reworded) args — i.e. a key from a
  keyspace the new generation never saw. The tool's idempotency check cannot
  suppress it (unseen key); only the epoch fence can reject it. This is the
  precise stale-writer hazard fencing tokens exist for.

## Results

| Condition | Dup rate | Δ vs full | Exactly-once | Mean dup/ep | Zombie fenced | Zombie committed |
|---|---|---|---|---|---|---|
| (iii-full) | **0.0000** | — | 1.0000 | 0.0000 | 749 | 0 |
| (a) no-fencing | 0.4927 | **+0.4927** | 0.5073 | 0.4927 | 0 | 739 |
| (b) no-log | 0.2333 | **+0.2333** | 0.7667 | 0.2333 | 746 | 0 |
| (c) neither | 0.8767 | **+0.8767** | 0.1233 | 1.2547 | 0 | 753 |

(Mean missing/episode = 0.0000 in all conditions — nothing goes missing, the
failure mode is purely duplication. Crash-landing fractions verified
≈ 0.75/0.15/0.10 in every condition.)

## Reading the table

- **Removing fencing (a): 0.0000 → 0.4927 (Δ +0.49).** The claim log alone
  handles the checkpoint window perfectly (zero window-attributable
  duplicates), but every surviving zombie's retry is *accepted* and commits —
  739/739 accepted zombie probes became duplicates. Fencing is the only thing
  standing between a stale generation and the tool: idempotency keys cannot
  help because the zombie presents a key the new generation never saw.
- **Removing the log (b): 0.0000 → 0.2333 (Δ +0.23).** Recovery falls back to
  agent re-derived deterministic position keys; the duplicate rate (0.2333)
  reproduces sandbox.py's `(ii-b)` (0.2113) within noise — the ablation
  preserved the key mechanism faithfully. Zombies are still fenced (746
  rejections), so all duplicates here are the known key re-derivation
  failure (plan-shift × in-window), not zombies.
- **Neither (c): 0.8767.** Decomposes cleanly into the two failure modes:
  window component ≈ 0.75 (reproduces baseline `(i)` 0.7687 — the no-log,
  no-fencing, no-key mechanism is identical) **plus** the zombie component
  ≈ 0.5 × 0.25 (safe landings) ≈ 0.125 → 0.875 expected, 0.8767 measured.
  Mean 1.25 duplicates/episode: in-window episodes routinely commit the
  effect three times (pre-crash + agent re-execution + zombie).
- **Fencing rejection counts** are the mirror image: ~750/1500 zombie probes
  fenced wherever fencing is on (`full`, `no_log`), exactly 0 where it is
  removed — the fence fires if and only if the component is present.

## Verdict

**Both components are load-bearing, against disjoint failure modes.**
The write-ahead log defeats key re-derivation after recovery (Δ +0.23 when
removed); the epoch fence defeats stale generations the log cannot see
(Δ +0.49 when removed). Neither subsumes the other: the log is blind to
writes from superseded generations, and fencing is blind to retries the
current generation mis-keys. The paper's necessity argument holds
empirically — each piece removed visibly raises the duplicate rate, and
removing both reproduces baseline plus the unfenced-zombie cost.
