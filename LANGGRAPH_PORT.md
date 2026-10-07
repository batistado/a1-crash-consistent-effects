# A1 LangGraph Production Port

Companion to the scripted sandbox (`src/sandbox.py`): the same fault model
and protocol, executed by a **real LangGraph `StateGraph` agent** with
**real side effects** and **real `SIGKILL` crash injection**. Exists so TPDS
reviewers cannot dismiss the result as "not productionalized."

Code: `langgraph_port/` — `README.md` (setup/run/repro), `config.json`
(seeded crash schedule), `requirements.txt` (pinned).

## Architecture (text diagram)

```
                        +------------------- crash_harness.py -------------------+
                        | episode driver (own process)                            |
                        |  - deterministic crash schedule (config seed)           |
                        |  - spawns agent subprocesses                            |
                        |  - watchdog thread: polls progress.log -> SIGKILL       |
                        |  - zombie probes (stale epoch) after recovery           |
                        |  - scores duplicates from tool-side ledgers             |
                        +----------+--------------------------------+-----------+
                                   | spawns                       | spawns
                    +--------------v-------------+  +-------------v--------------+
                    | agent_run.py --mode fresh  |  | agent_run.py --mode recover|
                    | LangGraph StateGraph       |  | NEW process, epoch+1       |
                    |                            |  |                            |
                    | plan -> claim -> execute   |  | recover -> plan -> claim   |
                    |   -> commit -> checkpoint  |  |   -> execute -> commit     |
                    |         (per step loop)    |  |   -> checkpoint (per step) |
                    +------+------+-------------+  +----------------------------+
                           |      |
              +------------v-+  +-v-----------------------+
              | file tool    |  | tool_server.py          |
              | append to    |  | (separate OS process,   |
              | scratch/     |  |  stdlib http.server)    |
              | audit.log    |  | atomic check-and-commit |
              | (idempotent, |  | per-workflow seen-keys  |
              |  fenced)     |  | fencing epochs          |
              +--------------+  durable ledger.jsonl      |
                                +------------------------+
```

**Durable state** — the only thing that survives the `SIGKILL`:

| Artifact | Where | Discipline |
|---|---|---|
| Effect-claim log | `runs/<cond>/<wf>/claim.log` | append-only JSONL, fsync per CLAIM/COMMIT (record shape = `measure_overhead.py`) |
| Checkpoint | `runs/<cond>/<wf>/checkpoint.json` | atomic temp+fsync+rename; advances only past COMMITted claims (log-fenced) |
| Fencing epoch | `runs/<cond>/<wf>/epoch.json`, `tool_epoch.json` | +1 per recovery; registered with the tool server before reconcile |
| Plan | `runs/<cond>/<wf>/plan.json` | atomic write at plan time (recovery resumes the same plan) |
| HTTP-side ledger | tool server `ledger.jsonl` | append+fsync per commit; ground truth for scoring |
| File-side ledger | `runs/<cond>/<wf>/scratch/audit.log` | keyed lines; ground truth for scoring |

**Crash injection.** The watchdog is an external observer: it polls the
agent's `progress.log` and sends `SIGKILL` when the scheduled marker
appears (`STEP <uid> CLAIM` / `TOOL_CALLED` / `CHECKPOINT`). The agent is
oblivious to the crash plan. After each marker the agent sleeps
`marker_sleep_ms` (chaos-instrumentation, 30 ms) so the kill lands
deterministically inside the intended stage — the standard "watch a log
line, then `kill -9`" chaos practice. Crash landings follow the sandbox's
75/15/10 weights (in-window / post-checkpoint / pre-step), drawn from the
seeded RNG in `config.json`.

**Recovery.** A brand-new process (`--mode recover`) with `epoch+1`:
fence acquisition with the tool server first, then reconcile-first replay
of every uncommitted claim with its **original** key, then log-fenced
checkpoint advance, then resume of remaining steps. Post-recovery
replanning nondeterminism (reword args P=0.5, plan shift P=0.3) mirrors the
sandbox, so the keys-alone conditions face the same re-derivation stress.

## Results

180 episodes (60/condition), seed 20261010, real SIGKILL per episode.
`results_langgraph.json` (per-episode rows included).

| Condition | Episodes | Duplicate-effect rate | Exactly-once rate | Zombie probes fenced |
|---|---|---|---|---|
| wal (claim log + fencing) | 60 | **0.0000** | **1.0000** | 60/60 HTTP, 60/60 file |
| baseline (no keys, no log) | 60 | 0.8333 (= 50/60 in-window, all duplicated) | 0.1667 | 60/60 HTTP, 60/60 file |
| deterministic keys | 60 | 0.2333 (≈ 0.75 × 0.3 shift rate) | 0.7667 | 60/60 HTTP, 60/60 file |

Crash landings drawn 75/15/10 (wal: 41 in-window / 8 pre_step / 11
post_checkpoint; 60/60 SIGKILLs delivered, 0 missed, 0 recovery failures).
The in-window fault reproduces in the production port (baseline 0.83), the
key re-derivation failure reproduces (deterministic 0.23 ≈ sandbox 0.21),
and the WAL+fencing condition holds at **0 duplicates / exactly-once 1.0**.

(Scripted-sandbox reference, 1,500 eps/cond: baseline 0.7687,
content-hash 0.3667, deterministic 0.2113, wal **0.0000** — the production
port reproduces the same ordering and magnitudes.)

Method note: the wal+baseline rows were rescored from durable on-disk
state (`rescore.py`, zombie probes re-executed) after the episode driver
was silently reaped at deterministic ep 40 of the first full run; the
deterministic condition was then re-run clean (fresh run dirs, tool-server
identity verification). Per-episode rows in `results_langgraph.json` are
marked `"rescored": true` where applicable. No episode's outcome was
altered — the rescore recomputes the identical scoring function from the
same ledgers.

## What's real vs simulated

**Real** — the parts a reviewer could otherwise hand-wave away:

1. **The agent is a genuine LangGraph `StateGraph`** (`agent_graph.py`):
   six nodes (`plan`, `recover`, `claim`, `execute`, `commit`,
   `checkpoint`), conditional entry on run mode, per-step loop with a
   step router. No mocks in the graph.
2. **Real tool side effects.** The HTTP tool is a real POST to a real
   separate OS process (`tool_server.py`, stdlib `ThreadingHTTPServer`);
   the file tool really appends to the filesystem. Both survive the agent's
   death and serve as ground-truth ledgers.
3. **Real durable claim log.** Append-only JSONL, `fsync` per CLAIM/COMMIT
   record — the same record shape and discipline measured in
   `OVERHEAD.md` (~52 ms/step durable cost).
4. **Real crashes.** `SIGKILL` delivered by an external watchdog process to
   the agent's PID. The "crash" is not a simulated branch — the process
   actually dies mid-graph; only durable files survive.
5. **Real epoch fencing.** Recovery increments a durable epoch, registers
   it with the tool server *before* reconciling, and both tool paths
   reject stale-epoch calls (verified by zombie probes every episode).
6. **Real checkpointing discipline.** Atomic checkpoint writes, fenced
   behind log commits; recovery reconciles before resuming.

**Simulated / scoped** — honest limitations, each justified:

1. **Task plans are scripted, not LLM-generated.** Justification: the
   fault under study is *harness-side crash consistency* — whether the
   claim log survives a process crash and reconciles correctly. Agent
   cognition (what plan to make) is not the variable; the LLM-driven
   validation (`llm_validation*.py`, 70 episodes × 2 models, 0 duplicates)
   already covers the cognition side. A deterministic planner removes a
   confounder and costs $0. The recovery nondeterminism that *does* matter
   for the mechanism (reword/shift breaking key re-derivation) is still
   modeled, with the same probabilities as the sandbox.
2. **The tool server is local, not a real external service.** It implements
   exactly the atomic-idempotent-receiver contract the paper assumes
   (DESIGN.md §2, FORMAL_MODEL.md A1) — the same idealization LIMBO uses
   for the tool contract. The experiment isolates the harness side by
   design; a flaky tool would confound the measurement.
3. **One crash per episode, benign crash-stop only.** Matches the paper's
   fault model (chaos/HPC checkpoint-restart tradition); no Byzantine
   behavior, no tool-side crashes.
4. **Post-marker sleep (30 ms) is test instrumentation**, not protocol: it
   gives the watchdog a deterministic window to land the kill after
   observing a marker. It does not change the commit/checkpoint ordering
   the window is defined by.

## Why the crash/recovery path is faithful to a production deployment

- The crash boundary is the **OS process**, the same boundary a production
  harness crash (OOM-kill, node failure, container eviction) presents:
  all volatile state (LangGraph in-memory state, Python heap) is
  destroyed; only fsync'd files and the surviving tool service remain.
- Recovery is a **cold start**: a new process that must rebuild everything
  from durable state, exactly as a restarted harness pod would. It cannot
  "remember" the pre-crash plan except via `plan.json`, cannot re-derive
  keys except via the claim log.
- The watchdog never signals the agent and never shares memory with it;
  the kill decision uses only externally observable durable signals
  (progress markers), like a chaos controller watching logs.
- Fencing mirrors production fencing-token practice: the new generation
  registers its epoch with the tool *before* doing work, so any late
  duplicate delivery from the dead generation is rejected rather than
  committed.

## Reproducing

See `langgraph_port/README.md`. Crash schedule is seeded
(`config.json`, seed 20261010); per-episode rows are in
`langgraph_port/results_langgraph.json`.
