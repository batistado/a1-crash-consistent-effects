#!/usr/bin/env python3
"""Real OS SIGKILL Multi-Model Benchmark across Qwen2.5-3B, 7B, and 14B-Coder on Apple MPS.

Key Apple Metal (MPS) engineering discipline:
- Each model runs in a dedicated fresh OS process (`--single-model`) so Metal unified
  memory starts completely clean.
- A single dedicated thread both initializes the PyTorch MPS model and serves
  `HTTPServer` (`/generate`), keeping 100% of Metal command buffers on one OS thread
  and avoiding `ThreadingHTTPServer` per-thread Metal TLS stalls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claimfence import (
    AtomicIdempotentReceiver,
    IndexedJSONLClaimStore,
    atomic_write_json,
    start_tool_server_in_thread,
)

VALID_EFFECT_ACTIONS = ["issue_refund", "record_ledger", "send_notice"]
DIAGNOSTIC_ACTION = "check_account_status"


def http_post_json(
    url: str, payload: Dict[str, Any], timeout: float = 300.0
) -> Tuple[int, Dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, {"status": "http_error", "raw": body}


def content_hash_key(wid: str, action: str, args: Dict[str, Any]) -> str:
    s = json.dumps(args, sort_keys=True)
    h = hashlib.sha256(f"{wid}|{action}|{s}".encode("utf-8")).hexdigest()[:24]
    return f"ch:{h}"


def positional_key(wid: str, call_pos: int, action: str) -> str:
    return f"pos:{wid}:{call_pos}:{action}"


def canonical_key(wid: str, action: str, target: str, occ: int) -> str:
    return f"can:{wid}:{action}:{target}:occ{occ}"


def build_episode_spec(ep_seed: int) -> Dict[str, Any]:
    rng = random.Random(ep_seed)
    cust = f"cust-{rng.randint(1000, 9999)}"
    amt = f"{rng.randint(25, 450)}.{rng.randint(10, 99):02d}"
    case_id = f"CASE-{rng.randint(10000, 99999)}"
    two_refunds = rng.random() < 0.25
    steps = [
        {
            "step_id": 0,
            "action": "issue_refund",
            "target": cust,
            "occurrence": 0,
            "depends_on": None,
            "desc": f"Issue primary refund of ${amt} to {cust} for {case_id}",
        },
        {
            "step_id": 1,
            "action": "record_ledger",
            "target": cust,
            "occurrence": 0,
            "depends_on": 0,
            "desc": f"Record audit ledger entry for {cust} citing Step 0's receipt_token",
        },
    ]
    if two_refunds:
        fee = f"{rng.randint(5, 20)}.00"
        steps.append(
            {
                "step_id": 2,
                "action": "issue_refund",
                "target": cust,
                "occurrence": 1,
                "depends_on": None,
                "desc": f"Issue separately authorized fee-waiver refund of ${fee} to {cust} (occurrence 1)",
            }
        )
    else:
        steps.append(
            {
                "step_id": 2,
                "action": "send_notice",
                "target": cust,
                "occurrence": 0,
                "depends_on": 0,
                "desc": f"Send resolution confirmation notice to {cust} citing Step 0's receipt_token",
            }
        )
    crash_step_id = 0 if rng.random() < 0.80 else 1
    return {
        "ep_seed": ep_seed,
        "customer": cust,
        "case_id": case_id,
        "amount": amt,
        "two_refunds": two_refunds,
        "crash_step_id": crash_step_id,
        "steps": steps,
    }


def parse_llm_json(raw_text: str) -> Optional[Dict[str, Any]]:
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    obj = None
    try:
        obj = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*?\}", text, re.S)
        if m:
            try:
                obj = json.loads(m.group(0))
            except ValueError:
                obj = None
    if not isinstance(obj, dict):
        return None
    act = str(obj.get("action", "")).strip()
    if act == DIAGNOSTIC_ACTION:
        return {"action": DIAGNOSTIC_ACTION, "target": str(obj.get("target", "")).strip()}
    if act not in VALID_EFFECT_ACTIONS:
        return None
    tgt = str(obj.get("target", "")).strip()
    if not tgt:
        return None
    try:
        occ = int(obj.get("occurrence", 0))
    except (TypeError, ValueError):
        occ = 0
    utok = obj.get("upstream_token")
    if isinstance(utok, str):
        utok = utok.strip()
        if utok.lower() in ("", "none", "null", "unknown", "n/a", "unknown_lost_in_crash"):
            utok = None
    else:
        utok = None
    memo = str(obj.get("memo", "")).strip()[:160]
    return {
        "action": act,
        "target": tgt,
        "occurrence": occ,
        "upstream_token": utok,
        "memo": memo or f"{act} on {tgt}",
    }


def run_worker_subprocess(args: argparse.Namespace) -> int:
    run_dir = args.run_dir
    wid = args.workflow_id
    arch = args.arch
    mode = args.mode
    spec = json.loads(Path(os.path.join(run_dir, "spec.json")).read_text(encoding="utf-8"))
    steps = spec["steps"]

    ckpt_path = os.path.join(run_dir, "ckpt.json")
    ledger_ckpt_path = os.path.join(run_dir, "ckpt_ledger.json")
    store_path = os.path.join(run_dir, "claimfence.jsonl")
    progress_path = os.path.join(run_dir, "progress.log")
    metrics_path = os.path.join(run_dir, f"worker_metrics_{mode}.json")

    def mark(line: str, sleep_ms: int = 0) -> None:
        with open(progress_path, "ab", buffering=0) as f:
            f.write((line + "\n").encode("utf-8"))
            os.fsync(f.fileno())
        if sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)

    def read_ckpt() -> Dict[str, Any]:
        if not os.path.exists(ckpt_path):
            return {"checkpoint": -1, "tokens": {}}
        try:
            return json.loads(Path(ckpt_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"checkpoint": -1, "tokens": {}}

    holder_id = f"{mode}-{os.getpid()}"
    epoch = 0
    cf_store = IndexedJSONLClaimStore(store_path) if arch == "claimfence" else None

    reconciled_summary = []
    if mode == "recover":
        mark("RECOVER_START")
        if arch == "claimfence":
            assert cf_store is not None
            _, finfo = http_post_json(
                args.tool_url + "/fence",
                {"workflow_id": wid, "holder_id": holder_id},
            )
            epoch = int(finfo["epoch"])
            for c in cf_store.uncommitted():
                code, resp = http_post_json(
                    args.tool_url + "/tool",
                    {
                        "workflow_id": wid,
                        "step_uid": c.uid,
                        "action": c.action,
                        "target": c.target,
                        "args": c.args,
                        "key": c.key,
                        "epoch": epoch,
                        "holder_id": holder_id,
                    },
                )
                if code == 409:
                    return 2
                cf_store.append_commit(c.key, result=resp.get("result"))

            ck_data = read_ckpt()
            tok_map = dict(ck_data.get("tokens") or {})
            max_idx = int(ck_data.get("checkpoint", -1))
            for c in cf_store.claims():
                if c.committed:
                    idx_i = int(c.uid)
                    max_idx = max(max_idx, idx_i)
                    if c.result and c.result.get("receipt_token"):
                        tok_map[str(idx_i)] = c.result["receipt_token"]
                    reconciled_summary.append(
                        f"step {c.uid} ({c.action} {c.target} occ={c.occurrence}): "
                        f"COMMITTED, receipt_token={c.result.get('receipt_token') if c.result else 'none'}"
                    )
            atomic_write_json(ckpt_path, {"checkpoint": max_idx, "tokens": tok_map})
            mark(f"RECOVER_RECONCILED epoch={epoch} ckpt={max_idx}")

    ck_state = read_ckpt()
    checkpoint = int(ck_state.get("checkpoint", -1))
    known_tokens: Dict[str, str] = dict(ck_state.get("tokens") or {})

    ckpt_ledger: Dict[str, Any] = {}
    if arch == "ckpt_ledger" and os.path.exists(ledger_ckpt_path):
        try:
            ckpt_ledger = json.loads(Path(ledger_ckpt_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            ckpt_ledger = {}

    call_pos = 0
    diag_inserted = False
    reword_observed = False
    llm_calls = 0

    goal_lines = "\n".join(
        f"  Step {s['step_id']}: action=\"{s['action']}\", target=\"{s['target']}\", "
        f"occurrence={s['occurrence']} -- {s['desc']}"
        for s in steps
    )

    if mode == "recover" and checkpoint < len(steps) - 1:
        settled_str = (
            "; ".join(reconciled_summary)
            if reconciled_summary
            else (
                f"Steps <= {checkpoint} checkpointed; tokens={json.dumps(known_tokens)}"
                if checkpoint >= 0
                else "NONE (checkpoint=-1; crash occurred mid-execution, external state uncertain!)"
            )
        )
        triage_prompt = (
            "You are an autonomous cloud operations agent recovering after an unexpected OS SIGKILL crash.\n"
            f"Workflow goal:\n{goal_lines}\n\n"
            f"Durable recovery state:\n  {settled_str}\n\n"
            "Before issuing external side-effecting calls, you may EITHER emit a read-only diagnostic check "
            f'{{"action": "{DIAGNOSTIC_ACTION}", "target": "{spec["customer"]}"}} if external commit state is uncertain, '
            "OR directly emit the JSON call for the first unfinished effectful step:\n"
            '{"action": "<issue_refund|record_ledger|send_notice>", "target": "<id>", '
            '"occurrence": <int>, "upstream_token": "<receipt_token_or_null>", "memo": "<6-8 word recovery note>"}\n'
            "Reply with ONLY a single-line JSON object."
        )
        _, gen_resp = http_post_json(
            args.llm_url + "/generate",
            {"ep_seed": spec["ep_seed"], "role": f"rec_triage_{checkpoint}", "prompt": triage_prompt},
        )
        llm_calls += 1
        parsed_first = parse_llm_json(gen_resp.get("text", ""))
        if parsed_first and parsed_first["action"] == DIAGNOSTIC_ACTION:
            diag_inserted = True
            call_pos += 1
            mark(f"DIAGNOSTIC_STEP pos={call_pos}")

    for s in steps:
        sid = s["step_id"]
        if sid <= checkpoint:
            continue

        ident_str = f"{s['action']}|{s['target']}|{s['occurrence']}"
        if arch == "ckpt_ledger" and ident_str in ckpt_ledger:
            if ckpt_ledger[ident_str].get("receipt_token"):
                known_tokens[str(sid)] = ckpt_ledger[ident_str]["receipt_token"]
            continue

        dep_hint = "null"
        if s["depends_on"] is not None:
            dep_hint = known_tokens.get(str(s["depends_on"]), "null")

        ctx_label = (
            "POST-CRASH RECOVERY EXECUTION (write a recovery-specific audit memo)"
            if mode == "recover"
            else "NORMAL EXECUTION"
        )
        step_prompt = (
            f"Mode: {ctx_label}.\n"
            f"Workflow:\n{goal_lines}\n"
            f"Known upstream receipt tokens: {json.dumps(known_tokens)}\n"
            f"Now emit the JSON tool call for Step {sid} "
            f"(action=\"{s['action']}\", target=\"{s['target']}\", occurrence={s['occurrence']}, "
            f"expected upstream_token=\"{dep_hint}\").\n"
            "Keep `memo` concise (under 10 words) and output single-line valid JSON:\n"
            '{"action": "...", "target": "...", "occurrence": 0, "upstream_token": "...", "memo": "..."}'
        )
        _, gen_resp = http_post_json(
            args.llm_url + "/generate",
            {"ep_seed": spec["ep_seed"], "role": f"{mode}_s{sid}", "prompt": step_prompt},
        )
        llm_calls += 1
        call_obj = parse_llm_json(gen_resp.get("text", ""))
        if call_obj is None or call_obj["action"] != s["action"]:
            _, gen_resp = http_post_json(
                args.llm_url + "/generate",
                {
                    "ep_seed": spec["ep_seed"] + 99,
                    "role": f"{mode}_s{sid}_retry",
                    "prompt": step_prompt + f'\nMUST set "action": "{s["action"]}", "target": "{s["target"]}".',
                },
            )
            llm_calls += 1
            call_obj = parse_llm_json(gen_resp.get("text", ""))

        if call_obj is None:
            continue

        utok = call_obj.get("upstream_token")
        if s["depends_on"] is not None and not utok:
            utok = known_tokens.get(str(s["depends_on"]))

        tool_args = {
            "memo": call_obj["memo"],
            "upstream_token": utok,
        }

        memo_track_path = os.path.join(run_dir, f"pre_memo_s{sid}.txt")
        if mode == "fresh":
            Path(memo_track_path).write_text(call_obj["memo"], encoding="utf-8")
        elif os.path.exists(memo_track_path):
            old_m = Path(memo_track_path).read_text(encoding="utf-8")
            if old_m != call_obj["memo"]:
                reword_observed = True

        if arch == "claimfence":
            assert cf_store is not None
            rec, reused = cf_store.create_or_reuse(
                wid=wid,
                uid=str(sid),
                action=call_obj["action"],
                target=call_obj["target"],
                args=tool_args,
                epoch=epoch,
                occurrence=call_obj["occurrence"],
            )
            if reused and rec.committed:
                if rec.result and rec.result.get("receipt_token"):
                    known_tokens[str(sid)] = rec.result["receipt_token"]
                call_pos += 1
                continue
            key: Optional[str] = rec.key
        elif arch == "baseline":
            key = None
        elif arch == "content_hash":
            key = content_hash_key(wid, call_obj["action"], tool_args)
        elif arch in ("deterministic_pos", "ckpt_ledger"):
            key = positional_key(wid, call_pos, call_obj["action"])
        elif arch == "det_canonical":
            key = canonical_key(
                wid, call_obj["action"], call_obj["target"], call_obj["occurrence"]
            )
        else:
            raise ValueError(arch)

        code, resp = http_post_json(
            args.tool_url + "/tool",
            {
                "workflow_id": wid,
                "step_uid": str(sid),
                "action": call_obj["action"],
                "target": call_obj["target"],
                "args": tool_args,
                "key": key,
                "epoch": epoch,
                "holder_id": holder_id,
            },
        )
        if code == 409:
            return 2

        res_payload = resp.get("result") or {}
        rtok = res_payload.get("receipt_token")
        if rtok:
            known_tokens[str(sid)] = rtok

        mark(f"STEP_COMMITTED sid={sid}", sleep_ms=(90 if mode == "fresh" else 0))

        if arch == "claimfence":
            assert cf_store is not None and key is not None
            cf_store.append_commit(key, result=res_payload)
        elif arch == "ckpt_ledger":
            ckpt_ledger[ident_str] = {"key": key, "receipt_token": rtok}
            atomic_write_json(ledger_ckpt_path, ckpt_ledger)

        checkpoint = sid
        atomic_write_json(ckpt_path, {"checkpoint": checkpoint, "tokens": known_tokens})
        mark(f"STEP_CHECKPOINTED sid={sid}")
        call_pos += 1

    atomic_write_json(
        metrics_path,
        {
            "mode": mode,
            "diag_inserted": diag_inserted,
            "reword_observed": reword_observed,
            "llm_calls": llm_calls,
        },
    )
    return 0


class DedicatedThreadMPSServer:
    """Loads AND serves the PyTorch MPS model on ONE dedicated thread so Metal
    command encoders never cross OS thread boundaries."""

    def __init__(self, model_id: str, temperature: float = 0.7) -> None:
        self.model_id = model_id
        self.temperature = temperature
        self.device = "cpu"
        self.load_s = 0.0
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.live_gpu_calls = 0
        self.cached_paired_hits = 0
        self.total_gen_tokens = 0
        self.gen_latencies_ms: List[float] = []
        self.url = ""
        self._ready = threading.Event()
        self._srv: Optional[HTTPServer] = None
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=600) or not self.url:
            raise RuntimeError(f"Timed out waiting for MPS server for {self.model_id}")

    def _run_loop(self) -> None:
        import torch
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            StoppingCriteria,
            StoppingCriteriaList,
        )

        self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        print(f"[MPS Dedicated Thread] Loading {self.model_id} onto {self.device}...", flush=True)
        t0 = time.perf_counter()
        tokenizer = AutoTokenizer.from_pretrained(self.model_id, local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            dtype=torch.float16 if self.device == "mps" else torch.float32,
            low_cpu_mem_usage=True,
            local_files_only=True,
        ).to(self.device)
        model.eval()
        self.load_s = round(time.perf_counter() - t0, 2)
        print(f"[MPS Dedicated Thread] Loaded {self.model_id} in {self.load_s}s", flush=True)

        # Fast O(|V|) dict scan (<0.03s) for token IDs containing '}'
        brace_tok_ids = {
            tid for tok_str, tid in tokenizer.get_vocab().items() if "}" in tok_str
        }

        parent_ref = self

        class _FastJSONStop(StoppingCriteria):
            def __init__(self, prompt_len: int) -> None:
                self.prompt_len = prompt_len

            def __call__(self, input_ids: Any, scores: Any, **kwargs: Any) -> bool:
                last_id = int(input_ids[0, -1])
                if last_id not in brace_tok_ids:
                    return False
                decoded = tokenizer.decode(
                    input_ids[0, self.prompt_len :], skip_special_tokens=True
                )
                start = decoded.find("{")
                if start == -1:
                    return False
                depth = 0
                in_str = False
                esc = False
                for ch in decoded[start:]:
                    if esc:
                        esc = False
                        continue
                    if ch == "\\":
                        esc = True
                        continue
                    if ch == '"':
                        in_str = not in_str
                        continue
                    if not in_str:
                        if ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                            if depth == 0:
                                return True
                return False

        def generate_on_owner_thread(ep_seed: int, prompt: str) -> Dict[str, Any]:
            prompt_hash = hashlib.sha256(
                f"{ep_seed}|{prompt}".encode("utf-8")
            ).hexdigest()[:24]
            if prompt_hash in parent_ref._cache:
                parent_ref.cached_paired_hits += 1
                return dict(parent_ref._cache[prompt_hash], cached=True)

            t_g0 = time.perf_counter()
            messages = [
                {
                    "role": "system",
                    "content": "You are a precise cloud workflow agent. Output only a single-line JSON object.",
                },
                {"role": "user", "content": prompt},
            ]
            chat_str = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = tokenizer(chat_str, return_tensors="pt").to(parent_ref.device)
            in_len = int(inputs["input_ids"].shape[1])

            seed_int = int(prompt_hash[:12], 16) % (2**31 - 1)
            torch.manual_seed(seed_int)
            if parent_ref.device == "mps":
                torch.mps.manual_seed(seed_int)

            with torch.no_grad():
                out_ids = model.generate(
                    **inputs,
                    max_new_tokens=96,
                    do_sample=True,
                    temperature=parent_ref.temperature,
                    top_p=0.90,
                    pad_token_id=tokenizer.eos_token_id,
                    stopping_criteria=StoppingCriteriaList([_FastJSONStop(in_len)]),
                )
            if parent_ref.device == "mps":
                torch.mps.synchronize()

            gen_ids = out_ids[0][in_len:]
            text = tokenizer.decode(gen_ids, skip_special_tokens=True).strip()
            dt_ms = (time.perf_counter() - t_g0) * 1000.0

            parent_ref.live_gpu_calls += 1
            parent_ref.total_gen_tokens += int(gen_ids.shape[0])
            parent_ref.gen_latencies_ms.append(dt_ms)

            rec = {
                "text": text,
                "latency_ms": round(dt_ms, 2),
                "tokens": int(gen_ids.shape[0]),
            }
            parent_ref._cache[prompt_hash] = rec
            return dict(rec, cached=False)

        class _SingleThreadHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length))
                res = generate_on_owner_thread(int(body["ep_seed"]), str(body["prompt"]))
                raw = json.dumps(res).encode("utf-8")
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except BrokenPipeError:
                    pass

            def log_message(self, fmt: str, *args: Any) -> None:
                return

        self._srv = HTTPServer(("127.0.0.1", 0), _SingleThreadHandler)
        self.url = f"http://127.0.0.1:{self._srv.server_address[1]}"
        self._ready.set()
        self._srv.serve_forever()

    def shutdown(self) -> None:
        if self._srv:
            self._srv.shutdown()


class SigkillWatchdog(threading.Thread):
    def __init__(
        self, proc: subprocess.Popen, progress_path: str, target_marker: bytes
    ) -> None:
        super().__init__(daemon=True)
        self.proc = proc
        self.progress_path = progress_path
        self.target_marker = target_marker
        self.fired = False
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                with open(self.progress_path, "rb") as f:
                    data = f.read()
                if self.target_marker in data:
                    os.kill(self.proc.pid, signal.SIGKILL)
                    self.fired = True
                    return
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass
            time.sleep(0.002)


def evaluate_single_model(
    model_id: str, n_episodes: int, base_seed: int, work_root: str
) -> Dict[str, Any]:
    engine = DedicatedThreadMPSServer(model_id=model_id, temperature=0.7)
    architectures = [
        "baseline",
        "content_hash",
        "deterministic_pos",
        "ckpt_ledger",
        "det_canonical",
        "claimfence",
    ]
    per_arch_results: Dict[str, List[Dict[str, Any]]] = {a: [] for a in architectures}
    try:
        for arch in architectures:
            srv_dir = os.path.join(work_root, model_id.replace("/", "_"), arch, "_srv")
            recv = AtomicIdempotentReceiver(
                state_dir=srv_dir,
                fencing_enabled=(arch == "claimfence"),
                status_only_mode=(arch != "claimfence"),
                durable_disk=True,
            )
            tool_srv, tool_url = start_tool_server_in_thread(recv)
            try:
                for ep_idx in range(n_episodes):
                    ep_seed = base_seed + ep_idx * 4099
                    spec = build_episode_spec(ep_seed)
                    wid = f"mm-{arch}-{ep_idx:03d}"
                    run_dir = os.path.join(
                        work_root, model_id.replace("/", "_"), arch, wid
                    )
                    os.makedirs(run_dir, exist_ok=True)
                    atomic_write_json(os.path.join(run_dir, "spec.json"), spec)

                    cmd_base = [
                        sys.executable,
                        os.path.abspath(__file__),
                        "--worker-subprocess",
                        "--run-dir",
                        run_dir,
                        "--workflow-id",
                        wid,
                        "--arch",
                        arch,
                        "--tool-url",
                        tool_url,
                        "--llm-url",
                        engine.url,
                    ]

                    proc1 = subprocess.Popen(
                        cmd_base + ["--mode", "fresh"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    target_marker = f"STEP_COMMITTED sid={spec['crash_step_id']}".encode("utf-8")
                    wd = SigkillWatchdog(
                        proc1, os.path.join(run_dir, "progress.log"), target_marker
                    )
                    wd.start()
                    proc1.wait(timeout=360)
                    wd.stop()
                    wd.join(timeout=1)
                    sigkilled = (proc1.returncode == -signal.SIGKILL) and wd.fired

                    proc2 = subprocess.Popen(
                        cmd_base + ["--mode", "recover"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    proc2.wait(timeout=360)
                    rec_ok = proc2.returncode == 0

                    commits = recv.workflow_commits(wid)
                    steps = spec["steps"]
                    step_by_id = {str(s["step_id"]): s for s in steps}
                    committed_counts: Dict[Tuple[str, str, int], int] = {}
                    auth_tokens: Dict[int, str] = {}

                    for c in commits:
                        s_orig = step_by_id.get(c["step_uid"])
                        occ = s_orig["occurrence"] if s_orig else 0
                        ident = (c["action"], c["target"], occ)
                        committed_counts[ident] = committed_counts.get(ident, 0) + 1
                        if s_orig and committed_counts[ident] == 1:
                            auth_tokens[s_orig["step_id"]] = c["result"]["receipt_token"]

                    intended_idents = [
                        (s["action"], s["target"], s["occurrence"]) for s in steps
                    ]
                    dups = sum(max(0, v - 1) for v in committed_counts.values())
                    miss = sum(
                        1 for idt in intended_idents if committed_counts.get(idt, 0) == 0
                    )

                    dep_total = sum(1 for s in steps if s["depends_on"] is not None)
                    dep_valid = 0
                    checked_sids = set()
                    for c in commits:
                        s_orig = step_by_id.get(c["step_uid"])
                        if s_orig and s_orig["depends_on"] is not None:
                            sid_i = s_orig["step_id"]
                            if sid_i not in checked_sids:
                                checked_sids.add(sid_i)
                                exp_t = auth_tokens.get(s_orig["depends_on"])
                                if exp_t and c["args"].get("upstream_token") == exp_t:
                                    dep_valid += 1

                    w_metrics_path = os.path.join(run_dir, "worker_metrics_recover.json")
                    w_metrics = (
                        json.loads(Path(w_metrics_path).read_text(encoding="utf-8"))
                        if os.path.exists(w_metrics_path)
                        else {}
                    )

                    per_arch_results[arch].append(
                        {
                            "ep_idx": ep_idx,
                            "sigkilled": sigkilled,
                            "recover_ok": rec_ok,
                            "duplicates": dups,
                            "missing": miss,
                            "exactly_once": (dups == 0 and miss == 0),
                            "payload_intact": (dep_valid == dep_total),
                            "strict_e2e": (dups == 0 and miss == 0 and dep_valid == dep_total),
                            "diag_shift": bool(w_metrics.get("diag_inserted")),
                            "memo_reworded": bool(w_metrics.get("reword_observed")),
                        }
                    )
            finally:
                tool_srv.shutdown()

        summary_by_arch = {}
        for arch in architectures:
            eps = per_arch_results[arch]
            n = len(eps)
            summary_by_arch[arch] = {
                "episodes": n,
                "sigkill_rate": round(sum(1 for e in eps if e["sigkilled"]) / n, 4),
                "duplicate_ep_rate": round(sum(1 for e in eps if e["duplicates"] > 0) / n, 4),
                "missing_ep_rate": round(sum(1 for e in eps if e["missing"] > 0) / n, 4),
                "exactly_once_rate": round(sum(1 for e in eps if e["exactly_once"]) / n, 4),
                "payload_continuity_rate": round(
                    sum(1 for e in eps if e["payload_intact"]) / n, 4
                ),
                "strict_e2e_rate": round(sum(1 for e in eps if e["strict_e2e"]) / n, 4),
                "organic_plan_shift_rate": round(
                    sum(1 for e in eps if e["diag_shift"]) / n, 4
                ),
                "organic_reword_rate": round(
                    sum(1 for e in eps if e["memo_reworded"]) / n, 4
                ),
            }
            s = summary_by_arch[arch]
            print(
                f"  [{model_id.split('/')[-1]:22s} | {arch:17s}] "
                f"SIGKILL={s['sigkill_rate']:.2f} dup={s['duplicate_ep_rate']:.3f} "
                f"eo={s['exactly_once_rate']:.3f} payload={s['payload_continuity_rate']:.3f} "
                f"strict={s['strict_e2e_rate']:.3f} "
                f"(reword={s['organic_reword_rate']:.2f}, shift={s['organic_plan_shift_rate']:.2f})",
                flush=True,
            )

        lats = sorted(engine.gen_latencies_ms)
        return {
            "model_id": model_id,
            "device": engine.device,
            "load_s": engine.load_s,
            "live_gpu_calls": engine.live_gpu_calls,
            "paired_cache_hits": engine.cached_paired_hits,
            "total_generated_tokens": engine.total_gen_tokens,
            "gen_latency_p50_ms": round(lats[len(lats) // 2], 1) if lats else 0.0,
            "gen_latency_p95_ms": round(lats[int(0.95 * len(lats))], 1) if lats else 0.0,
            "architectures": summary_by_arch,
        }
    finally:
        engine.shutdown()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker-subprocess", action="store_true")
    ap.add_argument("--single-model", default="")
    ap.add_argument("--base-seed", type=int, default=20261120)
    ap.add_argument("--model-out", default="")
    ap.add_argument("--run-dir", default="")
    ap.add_argument("--workflow-id", default="")
    ap.add_argument("--arch", default="")
    ap.add_argument("--mode", choices=["fresh", "recover"], default="fresh")
    ap.add_argument("--tool-url", default="")
    ap.add_argument("--llm-url", default="")
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument(
        "--models",
        default="Qwen/Qwen2.5-3B-Instruct,Qwen/Qwen2.5-7B-Instruct,Qwen/Qwen2.5-Coder-14B-Instruct",
    )
    args = ap.parse_args()

    if args.worker_subprocess:
        return run_worker_subprocess(args)

    out_dir = ROOT / "results"
    os.makedirs(out_dir, exist_ok=True)

    if args.single_model:
        work_root = tempfile.mkdtemp(dir=str(out_dir), prefix="_mm_one_")
        try:
            mres = evaluate_single_model(
                args.single_model, args.episodes, args.base_seed, work_root
            )
            Path(args.model_out).write_text(json.dumps(mres, indent=2), encoding="utf-8")
        finally:
            shutil.rmtree(work_root, ignore_errors=True)
        return 0

    # Parent multi-model driver: spawns one clean OS process per model!
    t0 = time.perf_counter()
    model_list = [m.strip() for m in args.models.split(",") if m.strip()]
    all_models = []
    for idx, mid in enumerate(model_list):
        slug = mid.replace("/", "_")
        part_path = out_dir / f"_part_{slug}.json"
        cmd = [
            sys.executable,
            os.path.abspath(__file__),
            "--single-model",
            mid,
            "--episodes",
            str(args.episodes),
            "--base-seed",
            str(20261120 + idx * 100_000),
            "--model-out",
            str(part_path),
        ]
        subprocess.run(cmd, check=True)
        all_models.append(json.loads(part_path.read_text(encoding="utf-8")))
        part_path.unlink(missing_ok=True)

    out_path = out_dir / "multimodel_sigkill_results.json"
    doc = {
        "episodes_per_model_per_arch": args.episodes,
        "total_sigkill_episodes": args.episodes * 6 * len(all_models),
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "models": all_models,
    }
    out_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"\nWrote {out_path} in {doc['elapsed_s']}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
