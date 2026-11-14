"""Atomic idempotent external tool receiver with server-enforced monotonic CAS fencing
and RIFL-complete durable completion-payload replay.

Upgrades over v1.0:
1. True atomic server-side epoch allocation (`acquire_fence_atomic`): atomically
   increments `max_epoch[wid] <- cur + 1` and binds `holder_id` under lock + durable
   persist, guaranteeing strictly disjoint epochs even when multiple recovery
   processes race concurrently (eliminating Assumption A7).
2. RIFL-complete result payload persistence: stores the deterministic/domain tool
   return payload alongside `key` in the durable ledger and replays it on
   `duplicate_suppressed` (unless `status_only_mode=True` is set for ablation).
3. Per-workflow fine-grained locking so independent concurrent workflows do not
   serialize on a single global Python mutex unless writing to the shared ledger.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

from .claim_store import atomic_write_json


class FencedError(Exception):
    """Raised when a writer presents a stale epoch or superseded holder lease."""


def synthesize_tool_result(
    workflow_id: str, action: str, target: str, args: Dict[str, Any], seq: int
) -> Dict[str, Any]:
    """Deterministic domain return payload (e.g. refund receipt token, version etag)
    that downstream workflow steps depend on."""
    digest = hashlib.sha256(
        f"{workflow_id}|{action}|{target}|{seq}".encode("utf-8")
    ).hexdigest()[:12]
    return {
        "receipt_token": f"rcpt_{action[:3]}_{digest}",
        "ledger_seq": seq,
        "target": target,
        "action": action,
    }


class AtomicIdempotentReceiver:
    """Crash-safe external service receiver supporting atomic CAS fencing and payload replay."""

    def __init__(
        self,
        state_dir: Optional[str] = None,
        fencing_enabled: bool = True,
        status_only_mode: bool = False,
        durable_disk: bool = True,
    ) -> None:
        self.state_dir = os.path.abspath(state_dir) if state_dir else None
        self.fencing_enabled = fencing_enabled
        self.status_only_mode = status_only_mode
        self.durable_disk = durable_disk and (self.state_dir is not None)
        if self.state_dir:
            os.makedirs(self.state_dir, exist_ok=True)
            self.ledger_path = os.path.join(self.state_dir, "ledger.jsonl")
            self.fences_path = os.path.join(self.state_dir, "fences.json")
        else:
            self.ledger_path = None
            self.fences_path = None

        self._global_lock = threading.Lock()
        self._wf_locks: Dict[str, threading.Lock] = {}
        self.ledger: List[Dict[str, Any]] = []
        # workflow_id -> {key -> result_payload}
        self.seen_results: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # workflow_id -> {"epoch": int, "holder": Optional[str]}
        self.fences: Dict[str, Dict[str, Any]] = {}
        self.fenced_rejections: int = 0
        self._rebuild()

    def _wf_lock(self, wid: str) -> threading.Lock:
        with self._global_lock:
            lk = self._wf_locks.get(wid)
            if lk is None:
                lk = threading.Lock()
                self._wf_locks[wid] = lk
            return lk

    def _rebuild(self) -> None:
        if not self.durable_disk:
            return
        if self.fences_path and os.path.exists(self.fences_path):
            try:
                with open(self.fences_path, encoding="utf-8") as f:
                    raw = json.load(f)
                for wid, v in raw.items():
                    if isinstance(v, dict):
                        self.fences[wid] = {
                            "epoch": int(v.get("epoch", 0)),
                            "holder": v.get("holder"),
                        }
                    else:
                        self.fences[wid] = {"epoch": int(v), "holder": None}
            except (OSError, json.JSONDecodeError):
                pass
        if self.ledger_path and os.path.exists(self.ledger_path):
            with open(self.ledger_path, "rb") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self.ledger.append(rec)
                    wid = rec.get("workflow_id", "")
                    key = rec.get("key")
                    if key:
                        self.seen_results.setdefault(wid, {})[key] = (
                            rec.get("result") or {}
                        )

    def _persist_fences(self) -> None:
        if self.durable_disk and self.fences_path:
            with self._global_lock:
                snapshot = {k: dict(v) for k, v in self.fences.items()}
                atomic_write_json(self.fences_path, snapshot)

    def acquire_fence_atomic(
        self, workflow_id: str, holder_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Server-side atomic Compare-And-Increment (`epoch <- cur + 1`).

        Any concurrent recovery caller receives a strictly higher epoch and
        immediately fences all earlier epochs, including racing recovery writers.
        """
        if not self.fencing_enabled:
            return {"epoch": 0, "holder": holder_id}
        with self._wf_lock(workflow_id):
            cur_info = self.fences.get(workflow_id, {"epoch": 0, "holder": None})
            new_epoch = int(cur_info["epoch"]) + 1
            new_info = {"epoch": new_epoch, "holder": holder_id}
            self.fences[workflow_id] = new_info
            self._persist_fences()
            return dict(new_info)

    def fence_legacy_non_atomic(
        self, workflow_id: str, client_epoch: int, holder_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Legacy v1.0 client-supplied max-monotonic fence (kept strictly for
        ablation demonstrating why non-atomic client stored+1 admits dual-recovery races)."""
        if not self.fencing_enabled:
            return {"epoch": client_epoch, "holder": holder_id}
        with self._wf_lock(workflow_id):
            cur_info = self.fences.get(workflow_id, {"epoch": 0, "holder": None})
            if client_epoch >= int(cur_info["epoch"]):
                self.fences[workflow_id] = {
                    "epoch": int(client_epoch),
                    "holder": holder_id,
                }
                self._persist_fences()
            return dict(self.fences[workflow_id])

    def call(
        self,
        workflow_id: str,
        step_uid: str,
        action: str,
        target: str,
        args: Dict[str, Any],
        key: Optional[str],
        epoch: int,
        holder_id: Optional[str] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        """Atomically verify fencing epoch, check key deduplication, and commit or replay."""
        with self._wf_lock(workflow_id):
            cur_info = self.fences.get(workflow_id, {"epoch": 0, "holder": None})
            cur_epoch = int(cur_info["epoch"])
            cur_holder = cur_info.get("holder")

            if self.fencing_enabled:
                if epoch < cur_epoch or (
                    epoch == cur_epoch
                    and cur_holder is not None
                    and holder_id is not None
                    and holder_id != cur_holder
                ):
                    self.fenced_rejections += 1
                    return 409, {
                        "status": "fenced",
                        "key": key,
                        "max_epoch": cur_epoch,
                    }
                if epoch > cur_epoch:
                    self.fences[workflow_id] = {
                        "epoch": epoch,
                        "holder": holder_id,
                    }
                    self._persist_fences()

            seen_wf = self.seen_results.setdefault(workflow_id, {})
            if key is not None and key in seen_wf:
                resp: Dict[str, Any] = {
                    "status": "duplicate_suppressed",
                    "key": key,
                }
                if not self.status_only_mode:
                    resp["result"] = seen_wf[key]
                return 200, resp

            with self._global_lock:
                seq = len(self.ledger) + 1
                result_payload = synthesize_tool_result(
                    workflow_id, action, target, args, seq
                )
                rec = {
                    "seq": seq,
                    "workflow_id": workflow_id,
                    "step_uid": str(step_uid),
                    "action": action,
                    "target": target,
                    "args": args,
                    "key": key,
                    "epoch": epoch,
                    "holder": holder_id,
                    "result": result_payload,
                    "ts": time.time(),
                }
                if self.durable_disk and self.ledger_path:
                    line = (
                        json.dumps(rec, separators=(",", ":")) + "\n"
                    ).encode("utf-8")
                    with open(self.ledger_path, "ab", buffering=0) as f:
                        f.write(line)
                        os.fsync(f.fileno())
                self.ledger.append(rec)

            if key is not None:
                seen_wf[key] = result_payload

            return 200, {
                "status": "committed",
                "key": key,
                "result": result_payload,
            }

    def workflow_commits(self, workflow_id: str) -> List[Dict[str, Any]]:
        with self._global_lock:
            return [r for r in self.ledger if r["workflow_id"] == workflow_id]


def start_tool_server_in_thread(
    receiver: AtomicIdempotentReceiver, host: str = "127.0.0.1", port: int = 0
) -> Tuple[ThreadingHTTPServer, str]:
    """Start a ThreadingHTTPServer wrapping `receiver` on an ephemeral or fixed port."""

    class _Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, obj: Dict[str, Any]) -> None:
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send(200, {"status": "ok"})
            elif self.path == "/stats":
                self._send(
                    200,
                    {
                        "status": "ok",
                        "commits": len(receiver.ledger),
                        "fenced_rejections": receiver.fenced_rejections,
                    },
                )
            else:
                self._send(404, {"status": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length)) if length else {}
            if self.path == "/fence":
                info = receiver.acquire_fence_atomic(
                    body["workflow_id"], body.get("holder_id")
                )
                self._send(200, {"status": "ok", **info})
            elif self.path == "/fence_legacy":
                info = receiver.fence_legacy_non_atomic(
                    body["workflow_id"],
                    int(body.get("epoch", 0)),
                    body.get("holder_id"),
                )
                self._send(200, {"status": "ok", **info})
            elif self.path == "/tool":
                code, resp = receiver.call(
                    workflow_id=body["workflow_id"],
                    step_uid=str(body.get("step_uid", "")),
                    action=body["action"],
                    target=body["target"],
                    args=dict(body.get("args") or {}),
                    key=body.get("key"),
                    epoch=int(body.get("epoch", 0)),
                    holder_id=body.get("holder_id"),
                )
                self._send(code, resp)
            else:
                self._send(404, {"status": "not_found"})

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    srv = ThreadingHTTPServer((host, port), _Handler)
    srv.daemon_threads = True
    actual_port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, f"http://{host}:{actual_port}"
