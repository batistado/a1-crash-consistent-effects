#!/usr/bin/env python3
"""Crash/recovery episode driver for the A1 LangGraph production port.

For each episode:
  1. Derive a deterministic crash schedule from the config seed
     (crash-step uid + landing drawn 75% in-window / 15% post-checkpoint /
     10% pre-step, mirroring the scripted sandbox fault model).
  2. Launch the fresh agent in its own OS process.
  3. An external watchdog thread polls the agent's progress.log and delivers
     a real SIGKILL the moment the target marker appears. The agent is
     oblivious to the crash plan — the kill is purely observational.
  4. Launch the recovery agent as a NEW process with a new epoch; it
     reconciles and resumes from durable state only.
  5. Send zombie probes (stale epoch) at both tool paths; expect fencing.
  6. Score duplicates/missing against the tool-side ground-truth ledgers
     (HTTP server ledger.jsonl + file scratch audit.log), semantically —
     the same rule as src/sandbox.py.

One crash per episode (same as the sandbox). No LLM calls; $0.
"""
import argparse
import json
import os
import random
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (atomic_write_json, is_effectful, make_plan, read_json,
                    score_episode)
from file_tool import FileTool, FencedError

PORT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PY = os.path.join(PORT_DIR, ".venv", "bin", "python")
COND_OFFSET = {"wal": 0, "baseline": 1, "deterministic": 2}


def log(msg):
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}",
          flush=True)


# --------------------------------------------------------------------------
# tool server lifecycle
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
                    # Identity check: a stale server from a dead run may
                    # still hold the port (its seen-keys would then
                    # idempotency-suppress this run's calls). Refuse it.
                    if body.get("state_dir") != state_dir:
                        proc.kill()
                        raise RuntimeError(
                            f"port {port} is held by a stale tool server "
                            f"(state_dir={body.get('state_dir')}); kill it "
                            f"first — refusing to run against stale keys")
                    log(f"tool server up at {url} "
                        f"(identity verified: {state_dir})")
                    return proc, url
        except urllib.error.HTTPError:
            raise
        except Exception:
            time.sleep(0.05)
    proc.kill()
    raise RuntimeError("tool server did not become healthy")


# --------------------------------------------------------------------------
# watchdog: external observer -> SIGKILL
# --------------------------------------------------------------------------
class Watchdog(threading.Thread):
    """Polls progress.log; SIGKILLs the agent process the moment the target
    marker line appears. Daemon thread; never touches agent internals."""

    def __init__(self, proc, progress_path, target, poll_s):
        super().__init__(daemon=True)
        self.proc = proc
        self.progress_path = progress_path
        self.target = target.encode()
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
            if any(l.startswith(self.target) for l in lines):
                try:
                    os.kill(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.fired = True
                return
            time.sleep(self.poll_s)


# --------------------------------------------------------------------------
# zombie probes (stale-epoch calls must be fenced)
# --------------------------------------------------------------------------
def probe_http_stale(server_url, workflow_id):
    """A call from the dead generation (epoch -1) must be rejected."""
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
# one episode
# --------------------------------------------------------------------------
def run_episode(cfg, server_url, server_state_dir, cond, ep_idx):
    rng = random.Random(cfg["seed"] + ep_idx * 7919 + COND_OFFSET[cond] * 104729)
    plan_seed = rng.randrange(1 << 60)
    recover_seed = rng.randrange(1 << 60)
    plan = make_plan(random.Random(plan_seed))
    eff_uids = [s["uid"] for s in plan if is_effectful(s)]
    crash_uid = rng.choice(eff_uids)
    r = rng.random()
    if r < cfg["p_in_window"]:
        landing = "in_window"
    elif r < cfg["p_in_window"] + cfg["p_post_checkpoint"]:
        landing = "post_checkpoint"
    else:
        landing = "pre_step"
    wid = f"lg-{cond}-{ep_idx:04d}-{plan_seed & 0xffff:04x}"
    run_dir = os.path.join(PORT_DIR, "runs", cond, wid)
    os.makedirs(run_dir, exist_ok=True)
    atomic_write_json(os.path.join(run_dir, "run_meta.json"), {
        "workflow_id": wid, "condition": cond, "episode": ep_idx,
        "plan_seed": plan_seed, "recover_seed": recover_seed,
        "crash_step_uid": crash_uid, "landing": landing})

    target = {"pre_step": f"STEP {crash_uid} CLAIM",
              "in_window": f"STEP {crash_uid} TOOL_CALLED",
              "post_checkpoint": f"STEP {crash_uid} CHECKPOINT"}[landing]
    t0 = time.time()
    base_args = ["--workflow-id", wid, "--run-dir", run_dir,
                 "--condition", cond, "--server-url", server_url,
                 "--plan-seed", str(plan_seed),
                 "--recover-seed", str(recover_seed),
                 "--marker-sleep-ms", str(cfg["marker_sleep_ms"]),
                 "--p-reword", str(cfg["p_reword"]),
                 "--p-plan-shift", str(cfg["p_plan_shift"])]

    # ---- fresh generation ----
    fresh_out = open(os.path.join(run_dir, "fresh_stdout.log"), "w")
    proc = subprocess.Popen(
        [VENV_PY, os.path.join(PORT_DIR, "agent_run.py"),
         "--mode", "fresh"] + base_args,
        stdout=fresh_out, stderr=subprocess.STDOUT)
    wd = Watchdog(proc, os.path.join(run_dir, "progress.log"), target,
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
    # integrity: the planned crash marker must exist — otherwise the kill
    # did not land as scheduled (agent died early or finished early: a bug,
    # not a valid crash injection).
    try:
        with open(os.path.join(run_dir, "progress.log"), "rb") as f:
            saw_marker = any(l.startswith(target.encode())
                             for l in f.read().split(b"\n"))
    except FileNotFoundError:
        saw_marker = False
    if not saw_marker:
        crash_missed = True

    # ---- recovery generation (new process, new epoch) ----
    rec_out = open(os.path.join(run_dir, "recover_stdout.log"), "w")
    proc2 = subprocess.Popen(
        [VENV_PY, os.path.join(PORT_DIR, "agent_run.py"),
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

    # ---- ground-truth scoring from the tool-side ledgers ----
    plan_doc = read_json(os.path.join(run_dir, "plan.json"), {})
    intended = [(s["action"], s["args"].get("target"))
                for s in plan_doc.get("plan", []) if is_effectful(s)]
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
                    committed.append((rec.get("action"), rec.get("target")))
    for e in FileTool(run_dir).ledger():
        committed.append((e["action"], e["target"]))
    sc = score_episode(intended, committed)

    rec = {
        "workflow_id": wid, "condition": cond, "episode": ep_idx,
        "plan_seed": plan_seed, "recover_seed": recover_seed,
        "crash_step_uid": crash_uid, "landing": landing,
        "crashed": crashed, "crash_missed": crash_missed,
        "recover_ok": recover_ok,
        "duplicates": sc["duplicates"], "missing": sc["missing"],
        "exactly_once": sc["exactly_once"],
        "zombie_http_fenced": z_http, "zombie_file_fenced": z_file,
        "n_intended": len(intended), "n_committed": len(committed),
        "elapsed_s": round(time.time() - t0, 2),
    }
    return rec


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(PORT_DIR, "config.json"))
    ap.add_argument("--conditions", default=None,
                    help="comma-separated override, e.g. wal,baseline")
    ap.add_argument("--episodes", type=int, default=None,
                    help="episodes-per-condition override")
    ap.add_argument("--out", default=None)
    ap.add_argument("--jsonl-out", default=None,
                    help="append each episode record here as it completes, "
                         "so a driver death never loses finished episodes")
    ap.add_argument("--overwrite", action="store_true",
                    help="delete runs/<condition> dirs for the run's "
                         "conditions before starting (fresh run dirs; avoids "
                         "append-only ledgers/logs from a previous launch "
                         "contaminating the new run)")
    args = ap.parse_args()
    cfg = json.load(open(args.config))
    if args.conditions:
        cfg["conditions"] = [c.strip() for c in args.conditions.split(",")]
    if args.episodes:
        cfg["episodes_per_condition"] = args.episodes
    if args.overwrite:
        import shutil
        for cond in cfg["conditions"]:
            cdir = os.path.join(PORT_DIR, "runs", cond)
            if os.path.isdir(cdir):
                shutil.rmtree(cdir)
                log(f"--overwrite: removed stale run dir {cdir}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    server_state_dir = os.path.join(PORT_DIR, "runs", "_server", ts)
    server_proc, server_url = start_server(
        server_state_dir, cfg["server_host"], cfg["server_port"])
    out_path = args.out or os.path.join(PORT_DIR, "results_langgraph.json")
    jsonl_path = (args.jsonl_out
                  or os.path.join(PORT_DIR, "results_langgraph.jsonl"))
    episodes = []
    try:
        for cond in cfg["conditions"]:
            n = cfg["episodes_per_condition"]
            log(f"condition={cond} episodes={n}")
            for i in range(n):
                rec = run_episode(cfg, server_url, server_state_dir, cond, i)
                episodes.append(rec)
                # incremental persistence: a driver death must not lose
                # finished episodes (cf. the 2026-10-07 silent-death lesson)
                with open(jsonl_path, "a") as jf:
                    jf.write(json.dumps(rec) + "\n")
                if (i + 1) % 10 == 0 or not rec["exactly_once"]:
                    log(f"  [{cond}] {i + 1}/{n} dup={rec['duplicates']} "
                        f"miss={rec['missing']} eo={rec['exactly_once']} "
                        f"landing={rec['landing']}")
    finally:
        server_proc.terminate()
        server_proc.wait(timeout=10)

    summary = {"config": cfg,
               "server_state_dir": server_state_dir,
               "conditions": {}}
    for cond in cfg["conditions"]:
        ce = [e for e in episodes if e["condition"] == cond]
        n = len(ce)
        dup_eps = sum(1 for e in ce if e["duplicates"] > 0)
        eo = sum(1 for e in ce if e["exactly_once"])
        landings = {}
        for e in ce:
            landings[e["landing"]] = landings.get(e["landing"], 0) + 1
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
            "crash_landings": landings,
        }
        c = summary["conditions"][cond]
        log(f"[{cond}] dup_rate={c['duplicate_effect_rate']} "
            f"exactly_once={c['exactly_once_rate']} "
            f"fenced_http={c['zombie_http_fenced']}/{n} "
            f"fenced_file={c['zombie_file_fenced']}/{n}")
    summary["episodes"] = episodes
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    log(f"wrote {out_path}")


if __name__ == "__main__":
    sys.exit(main())
