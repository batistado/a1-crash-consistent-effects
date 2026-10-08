#!/usr/bin/env python3
"""Crash/recovery episode driver for the A1 LangGraph v2 research-assistant.

One crash per episode, real SIGKILL, external watchdog with a *predicate*
over progress.log (v2's crash windows are positional, not single-marker):

  mid_fanout     — kill when the first WORKER r0 COMMIT appears: some
                   workers committed, others still in flight (partial
                   fan-out completion — the new interesting case).
  post_branch    — kill right after the supervisor's BRANCH marker for
                   round 1: decision made, tool not yet invoked.
  retry_backoff  — kill while a worker sleeps in its retry backoff
                   (RETRY_WAIT): claim exists but uncommitted.

Conditions: wal | baseline | deterministic. 60 episodes/condition.
$0 — scripted planner, local compute only.
"""
import argparse
import json
import os
import random
import re
import signal
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import atomic_write_json, read_json, score_episode
from common_v2 import intended_effects, make_scenario
from common_v2 import canonical_target_v2
from file_tool import FileTool, FencedError

PORT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(PORT_DIR, ".venv", "bin", "python")
COND_OFFSET = {"wal": 0, "baseline": 1, "deterministic": 2, "native": 3,
               "det_shift": 4, "det_content": 5}


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}",
          flush=True)


# --------------------------------------------------------------------------
# tool server lifecycle (separate port from the v1 port)
# --------------------------------------------------------------------------
def start_server(state_dir, host, port):
    proc = subprocess.Popen(
        [VENV_PY, os.path.join(PORT_DIR, "tool_server.py"),
         "--state-dir", state_dir, "--host", host, "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://{host}:{port}"
    for _ in range(200):
        try:
            with urllib.request.urlopen(url + "/health", timeout=1) as r:
                body = json.load(r)
                if r.status == 200:
                    if body.get("state_dir") != state_dir:
                        proc.kill()
                        raise RuntimeError(
                            f"port {port} held by a stale tool server; "
                            f"kill it first")
                    log(f"tool server up at {url}")
                    return proc, url
        except urllib.error.HTTPError:
            raise
        except Exception:
            time.sleep(0.05)
    proc.kill()
    raise RuntimeError("tool server did not become healthy")


# --------------------------------------------------------------------------
# watchdog: external observer -> SIGKILL when predicate(progress lines) fires
# --------------------------------------------------------------------------
class PredicateWatchdog(threading.Thread):
    def __init__(self, proc, progress_path, predicate, poll_s):
        super().__init__(daemon=True)
        self.proc = proc
        self.progress_path = progress_path
        self.predicate = predicate
        self.poll_s = poll_s
        self.fired = False
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.is_set():
            try:
                with open(self.progress_path, "rb") as f:
                    lines = f.read().split(b"\n")
            except FileNotFoundError:
                lines = []
            try:
                hit = self.predicate(lines)
            except Exception:
                hit = False
            if hit:
                try:
                    os.kill(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.fired = True
                return
            time.sleep(self.poll_s)


def pred_mid_fanout(lines):
    # first committed worker effect of round 0 -> kill: partial fan-out
    return any(l.startswith(b"WORKER r0 b") and b" COMMIT" in l
               for l in lines)


def pred_post_branch(lines):
    # supervisor decided round 1's route, before any tool call of that round
    return any(l.startswith(b"BRANCH route=") and b" round=1" in l
               for l in lines)


def pred_retry_backoff(lines):
    # worker sleeping in retry backoff, round 0 branch 0
    return any(l.startswith(b"WORKER r0 b0") and b"RETRY_WAIT" in l
               for l in lines)


CRASH_PREDS = {"mid_fanout": pred_mid_fanout,
               "post_branch": pred_post_branch,
               "retry_backoff": pred_retry_backoff}


# --------------------------------------------------------------------------
# zombie probes (stale-epoch calls must be fenced)
# --------------------------------------------------------------------------
def probe_http_stale(server_url, workflow_id):
    body = json.dumps({"workflow_id": workflow_id, "step_uid": "zombie",
                       "action": "issue_refund", "target": "zombie",
                       "note": "zombie", "key": f"zombie-{workflow_id}",
                       "epoch": -1}).encode()
    req = urllib.request.Request(server_url + "/tool", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.load(r)
            return resp.get("status") == "fenced"
    except urllib.error.HTTPError as e:
        if e.code == 409:
            return json.load(e).get("status") == "fenced"
        return False


def probe_file_stale(run_dir):
    try:
        FileTool(run_dir).append("append_audit", "zombie-probe", "z",
                                 "zombie-key", epoch=-1)
        return False
    except FencedError:
        return True


# --------------------------------------------------------------------------
# partial fan-out analysis: how many round-0 branches had committed at kill
# --------------------------------------------------------------------------
COMMIT_RE = re.compile(rb"WORKER r0 b(\d+) e\d+ COMMIT")


def partial_fanout_stats(run_dir):
    try:
        with open(os.path.join(run_dir, "progress.log"), "rb") as f:
            content = f.read()
    except FileNotFoundError:
        return None
    # Only pre-crash markers count: cut at the recovery boundary, since the
    # recovery generation appends its own COMMIT markers to the same file.
    lines = content.split(b"\n")
    pre = []
    for l in lines:
        if l.startswith(b"RECOVER"):
            break
        pre.append(l)
    committed = set(int(m.group(1)) for l in pre
                    for m in [COMMIT_RE.search(l)] if m)
    disp = read_json(os.path.join(run_dir, "dispatched_r0.json"), {})
    dispatched = set(disp.get("dispatched", []))
    if not dispatched:
        return None
    return {"dispatched": sorted(dispatched),
            "committed_at_kill": sorted(committed & dispatched),
            "partial": 0 < len(committed & dispatched) < len(dispatched),
            "none_committed": len(committed & dispatched) == 0,
            "all_committed": (committed & dispatched) == dispatched}


# --------------------------------------------------------------------------
# LLM-planner ground truth: round-1 route from the episode's actual
# decisions (decisions.jsonl), not from the scripted scenario generator.
# Returns (route1, any_fallback). route1 is None when no decision was
# ever recorded (e.g. recovery failed before round 1).
# --------------------------------------------------------------------------
def _llm_route1_from_decisions(run_dir):
    path = os.path.join(run_dir, "decisions.jsonl")
    route1, any_fb = None, False
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("round") == 1 and d.get("route") in (
                        "fan_out", "escalate"):
                    route1 = d["route"]
                    any_fb = any_fb or bool(d.get("fallback"))
    except FileNotFoundError:
        pass
    return route1, any_fb


# --------------------------------------------------------------------------
# one episode
# --------------------------------------------------------------------------
def run_episode(cfg, server_url, server_state_dir, cond, ep_idx, run_tag,
                planner):
    rng = random.Random(cfg["seed"] + ep_idx * 7919 + COND_OFFSET[cond] * 104729)
    plan_seed = rng.randrange(1 << 60)
    recover_seed = rng.randrange(1 << 60)
    r = rng.random()
    if r < cfg["p_crash_mid_fanout"]:
        crash_type = "mid_fanout"
    elif r < cfg["p_crash_mid_fanout"] + cfg["p_crash_post_branch"]:
        crash_type = "post_branch"
    else:
        crash_type = "retry_backoff"
    wid = f"lgv2-{cond}-{ep_idx:04d}-{plan_seed & 0xffff:04x}"
    run_dir = os.path.join(PORT_DIR, "runs", run_tag, cond, wid)
    os.makedirs(run_dir, exist_ok=True)
    atomic_write_json(os.path.join(run_dir, "run_meta.json"), {
        "workflow_id": wid, "condition": cond, "episode": ep_idx,
        "plan_seed": plan_seed, "recover_seed": recover_seed,
        "crash_type": crash_type, "planner": planner})

    t0 = time.time()
    if cond == "native":
        # E1: native-persistence baseline — dedicated runner with the
        # checkpointer-compiled graph (subset of args; no claim-log flags).
        runner_script = os.path.join(PORT_DIR, "agent_run_v2_native.py")
        base_args = ["--workflow-id", wid, "--run-dir", run_dir,
                     "--server-url", server_url,
                     "--plan-seed", str(plan_seed),
                     "--recover-seed", str(recover_seed),
                     "--marker-sleep-ms", str(cfg["marker_sleep_ms"]),
                     "--retry-backoff-s", str(cfg["retry_backoff_s"])]
    else:
        runner_script = os.path.join(PORT_DIR, "agent_run_v2.py")
        base_args = ["--workflow-id", wid, "--run-dir", run_dir,
                     "--condition", cond, "--server-url", server_url,
                     "--plan-seed", str(plan_seed),
                     "--recover-seed", str(recover_seed),
                     "--marker-sleep-ms", str(cfg["marker_sleep_ms"]),
                     "--retry-backoff-s", str(cfg["retry_backoff_s"]),
                     "--p-reword", str(cfg["p_reword"]),
                     "--p-plan-shift", str(cfg["p_plan_shift"]),
                     "--planner", planner]
        if cfg.get("reword_recovery"):
            base_args.append("--reword-recovery")
    # ---- fresh generation ----
    fresh_out = open(os.path.join(run_dir, "fresh_stdout.log"), "w")
    proc = subprocess.Popen(
        [VENV_PY, runner_script,
         "--mode", "fresh"] + base_args,
        stdout=fresh_out, stderr=subprocess.STDOUT)
    wd = PredicateWatchdog(proc, os.path.join(run_dir, "progress.log"),
                           CRASH_PREDS[crash_type],
                           cfg["watchdog_poll_ms"] / 1000.0)
    wd.start()
    crash_missed = False
    try:
        proc.wait(timeout=cfg["fresh_timeout_s"])
    except subprocess.TimeoutExpired:
        crash_missed = True
        proc.kill()
        proc.wait()
    wd.stop()
    wd.join(timeout=2)
    fresh_out.close()
    crashed = (proc.returncode == -signal.SIGKILL)
    if not wd.fired:
        # the scheduled crash window never materialized — invalid injection
        crash_missed = True

    # ---- recovery generation ----
    rec_out = open(os.path.join(run_dir, "recover_stdout.log"), "w")
    proc2 = subprocess.Popen(
        [VENV_PY, runner_script,
         "--mode", "recover"] + base_args,
        stdout=rec_out, stderr=subprocess.STDOUT)
    recover_ok = True
    try:
        proc2.wait(timeout=cfg["recover_timeout_s"])
        recover_ok = (proc2.returncode == 0)
    except subprocess.TimeoutExpired:
        recover_ok = False
        proc2.kill()
        proc2.wait()
    rec_out.close()

    # ---- zombie probes ----
    z_http = probe_http_stale(server_url, wid)
    z_file = probe_file_stale(run_dir)

    # ---- partial fan-out bookkeeping ----
    pstats = (partial_fanout_stats(run_dir)
              if crash_type == "mid_fanout" else None)

    # ---- ground-truth scoring from the tool-side ledgers ----
    # Scripted planner: the scenario (and hence intended effects) is fully
    # determined by plan_seed. LLM planner: round 1's route came from the
    # model, so intended effects are built from the ACTUAL decisions the
    # episode took. The recovery generation completes the episode, so its
    # round-1 decision (the last one appended) is authoritative.
    gt_fallback = False
    if planner == "llm":
        route1, llm_fb = _llm_route1_from_decisions(run_dir)
        if route1 is None:
            scenario = make_scenario(random.Random(plan_seed))
            gt_fallback = True
        else:
            scenario = {"rounds": [
                {"round": 0, "route": "fan_out", "branches": [0, 1, 2]},
                {"round": 1, "route": route1,
                 "branches": ([0, 1, 2] if route1 == "fan_out" else ["esc"])},
            ]}
    else:
        scenario = make_scenario(random.Random(plan_seed))
        route1, llm_fb = None, False
    intended = intended_effects(scenario)
    committed = []
    ledger_path = os.path.join(server_state_dir, "ledger.jsonl")
    if os.path.exists(ledger_path):
        with open(ledger_path, "rb") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("workflow_id") == wid:
                    tgt = rec.get("target")
                    # E2b: score on the canonical business identity so a
                    # reworded retry counts as the same logical effect.
                    if cfg.get("reword_recovery"):
                        tgt = canonical_target_v2(tgt)
                    committed.append((rec.get("action"), tgt))
    for e in FileTool(run_dir).ledger():
        tgt = e["target"]
        if cfg.get("reword_recovery"):
            tgt = canonical_target_v2(tgt)
        committed.append((e["action"], tgt))
    sc = score_episode(intended, committed)

    rec = {
        "workflow_id": wid, "condition": cond, "episode": ep_idx,
        "plan_seed": plan_seed, "recover_seed": recover_seed,
        "planner": planner, "llm_route1": route1,
        "llm_fallback": llm_fb, "ground_truth_fallback": gt_fallback,
        "crash_type": crash_type,
        "crashed": crashed, "crash_missed": crash_missed,
        "recover_ok": recover_ok,
        "duplicates": sc["duplicates"], "missing": sc["missing"],
        "exactly_once": sc["exactly_once"],
        "zombie_http_fenced": z_http, "zombie_file_fenced": z_file,
        "n_intended": len(intended), "n_committed": len(committed),
        "partial_fanout": pstats,
        "elapsed_s": round(time.time() - t0, 2),
    }
    return rec


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(PORT_DIR, "config_v2.json"))
    ap.add_argument("--conditions", default=None)
    ap.add_argument("--episodes", type=int, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--jsonl-out", default=None)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--run-tag", default="v2",
                    help="run directory tag: runs/<tag>/... (default v2)")
    ap.add_argument("--reword-recovery", action="store_true",
                    help="E2b campaign: recovery replanning rephrases targets")
    ap.add_argument("--planner", choices=["scripted", "llm"],
                    default="scripted",
                    help="round-1 routing decision source")
    args = ap.parse_args()
    cfg = json.load(open(args.config))
    cfg["reword_recovery"] = args.reword_recovery
    if args.conditions:
        cfg["conditions"] = [c.strip() for c in args.conditions.split(",")]
    if args.episodes:
        cfg["episodes_per_condition"] = args.episodes
    if args.overwrite:
        import shutil
        for cond in cfg["conditions"]:
            cdir = os.path.join(PORT_DIR, "runs", args.run_tag, cond)
            if os.path.isdir(cdir):
                shutil.rmtree(cdir)
                log(f"--overwrite: removed stale run dir {cdir}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    server_state_dir = os.path.join(PORT_DIR, "runs", args.run_tag,
                                    "_server", ts)
    server_proc, server_url = start_server(
        server_state_dir, cfg["server_host"], cfg["server_port"])
    out_path = args.out or os.path.join(PORT_DIR, "results_langgraph_v2.json")
    jsonl_path = (args.jsonl_out
                  or os.path.join(PORT_DIR, "results_langgraph_v2.jsonl"))
    episodes = []
    try:
        for cond in cfg["conditions"]:
            n = cfg["episodes_per_condition"]
            log(f"condition={cond} episodes={n}")
            for i in range(n):
                rec = run_episode(cfg, server_url, server_state_dir, cond, i,
                                  args.run_tag, args.planner)
                episodes.append(rec)
                with open(jsonl_path, "a") as jf:
                    jf.write(json.dumps(rec) + "\n")
                if (i + 1) % 10 == 0 or not rec["exactly_once"]:
                    log(f"  [{cond}] {i + 1}/{n} dup={rec['duplicates']} "
                        f"miss={rec['missing']} eo={rec['exactly_once']} "
                        f"crash={rec['crash_type']}")
    finally:
        server_proc.terminate()
        server_proc.wait(timeout=10)

    # ---- overhead: aggregate claim-log per-record latencies (wal only) ----
    latencies = []
    llm_spend_usd = 0.0
    llm_calls = 0
    for e in episodes:
        if e["condition"] != "wal":
            continue
        rd = os.path.join(PORT_DIR, "runs", args.run_tag, "wal",
                          e["workflow_id"])
        for mode in ("fresh", "recover"):
            p = os.path.join(rd, f"claim_timings_v2_{mode}.json")
            doc = read_json(p, [])
            latencies.extend(x["latency_s"] for x in doc if x.get("latency_s"))

    summary = {"config": cfg,
               "run_tag": args.run_tag,
               "planner": args.planner,
               "server_state_dir": server_state_dir,
               "conditions": {}}
    if args.planner == "llm":
        # Aggregate LLM spend + route distribution across all episodes.
        routes = {"fan_out": 0, "escalate": 0}
        fallbacks = 0
        for e in episodes:
            rd = os.path.join(PORT_DIR, "runs", args.run_tag,
                              e["condition"], e["workflow_id"])
            sp = os.path.join(rd, "llm_spend.json")
            try:
                with open(sp) as f:
                    s = json.load(f)
                llm_spend_usd += s.get("usd", 0.0)
                llm_calls += s.get("calls", 0)
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            if e.get("llm_route1") in routes:
                routes[e["llm_route1"]] += 1
            if e.get("llm_fallback"):
                fallbacks += 1
        summary["llm"] = {
            "model": "gpt-4o-mini",
            "total_spend_usd": round(llm_spend_usd, 4),
            "total_calls": llm_calls,
            "route1_distribution": routes,
            "episodes_with_fallback": fallbacks,
            "episodes_ground_truth_fallback": sum(
                1 for e in episodes if e.get("ground_truth_fallback")),
        }
        log(f"LLM planner: spend=${llm_spend_usd:.4f} calls={llm_calls} "
            f"routes={routes} fallbacks={fallbacks}")
    for cond in cfg["conditions"]:
        ce = [e for e in episodes if e["condition"] == cond]
        n = len(ce)
        dup_eps = sum(1 for e in ce if e["duplicates"] > 0)
        eo = sum(1 for e in ce if e["exactly_once"])
        by_crash = {}
        for e in ce:
            b = by_crash.setdefault(e["crash_type"], {"n": 0, "dup_eps": 0,
                                                     "miss_eps": 0})
            b["n"] += 1
            b["dup_eps"] += (e["duplicates"] > 0)
            b["miss_eps"] += (e["missing"] > 0)
        partials = [e["partial_fanout"] for e in ce
                    if e["partial_fanout"]]
        summary["conditions"][cond] = {
            "episodes": n,
            "duplicate_effect_rate": round(dup_eps / n, 4) if n else 0,
            "exactly_once_rate": round(eo / n, 4) if n else 0,
            "mean_duplicates_per_episode": round(
                sum(e["duplicates"] for e in ce) / n, 4) if n else 0,
            "mean_missing_per_episode": round(
                sum(e["missing"] for e in ce) / n, 4) if n else 0,
            "episodes_with_duplicates": dup_eps,
            "crash_missed": sum(1 for e in ce if e["crash_missed"]),
            "recover_failures": sum(1 for e in ce if not e["recover_ok"]),
            "zombie_http_fenced": sum(1 for e in ce if e["zombie_http_fenced"]),
            "zombie_file_fenced": sum(1 for e in ce if e["zombie_file_fenced"]),
            "by_crash_type": by_crash,
            "mid_fanout_partial_rate": round(
                sum(1 for p in partials if p["partial"]) / len(partials), 4)
            if partials else None,
            "mid_fanout_none_committed": sum(
                1 for p in partials if p["none_committed"]),
            "mid_fanout_all_committed": sum(
                1 for p in partials if p["all_committed"]),
        }
        c = summary["conditions"][cond]
        log(f"[{cond}] dup_rate={c['duplicate_effect_rate']} "
            f"exactly_once={c['exactly_once_rate']} "
            f"partial={c['mid_fanout_partial_rate']}")
    if latencies:
        latencies.sort()
        summary["overhead"] = {
            "claim_records": len(latencies),
            "latency_p50_s": round(statistics.median(latencies), 6),
            "latency_p99_s": round(
                latencies[max(0, int(0.99 * len(latencies)) - 1)], 6),
            "latency_max_s": round(max(latencies), 6),
        }
        log(f"claim-log latency p50={summary['overhead']['latency_p50_s']}s "
            f"p99={summary['overhead']['latency_p99_s']}s "
            f"n={len(latencies)}")
    summary["episodes"] = episodes
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    log(f"wrote {out_path}")


if __name__ == "__main__":
    sys.exit(main())
