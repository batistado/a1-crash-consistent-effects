#!/usr/bin/env python3
"""Local test tool-server: the 'external tool' with REAL side effects.

Runs as a separate OS process (stdlib http.server). Survives agent SIGKILLs.
Implements the atomic idempotent receiver contract (DESIGN.md §2,
FORMAL_MODEL.md A1 — the same idealization LIMBO uses for the tool contract):

  POST /tool  {workflow_id, step_uid, action, target, note, key, epoch}
    - rejects calls with a stale fencing epoch            -> 409 {"status":"fenced"}
    - returns duplicate_suppressed for already-seen keys  -> 200 (no re-commit)
    - else commits the effect durably and records the key -> 200 {"status":"committed"}
    Check-and-commit is atomic under a server-side lock. Every commit is
    appended to a durable JSONL ledger (fsync per record): the ledger is the
    HTTP-side ground truth for duplicate scoring.

  POST /fence {workflow_id, epoch}
    Fence acquisition: the recovery generation registers its new epoch before
    reconciling, so any in-flight call from the dead generation is stale.

  GET  /health, GET /stats

Durability: ledger.jsonl (append+fsync per commit) and epochs.json
(atomic rewrite per fence). On startup the seen-key sets are rebuilt from
the ledger, so the server is crash-safe even if it were killed too.
"""
import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from common import atomic_write_json, read_json


class ToolState:
    def __init__(self, state_dir):
        self.state_dir = state_dir
        os.makedirs(state_dir, exist_ok=True)
        self.ledger_path = os.path.join(state_dir, "ledger.jsonl")
        self.epochs_path = os.path.join(state_dir, "epochs.json")
        self.lock = threading.Lock()
        self.seen_keys = {}   # workflow_id -> set of keys
        self.max_epoch = {}   # workflow_id -> int (durable fencing epoch)
        self.fenced_rejections = 0
        self._rebuild()

    def _rebuild(self):
        saved = read_json(self.epochs_path, {})
        self.max_epoch = {k: int(v) for k, v in saved.items()}
        if os.path.exists(self.ledger_path):
            with open(self.ledger_path, "rb") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("key"):
                        self.seen_keys.setdefault(
                            rec["workflow_id"], set()).add(rec["key"])

    def _persist_epochs(self):
        atomic_write_json(self.epochs_path, self.max_epoch)

    def fence(self, workflow_id, epoch):
        with self.lock:
            cur = self.max_epoch.get(workflow_id, 0)
            if epoch > cur:
                self.max_epoch[workflow_id] = epoch
                self._persist_epochs()
            return self.max_epoch[workflow_id]

    def call(self, workflow_id, step_uid, action, target, note, key, epoch):
        with self.lock:
            cur = self.max_epoch.get(workflow_id, 0)
            if epoch is not None and epoch < cur:
                self.fenced_rejections += 1
                return 409, {"status": "fenced", "key": key,
                             "max_epoch": cur}
            if epoch is not None and epoch > cur:
                self.max_epoch[workflow_id] = epoch
                self._persist_epochs()
            seen = self.seen_keys.setdefault(workflow_id, set())
            if key is not None and key in seen:
                return 200, {"status": "duplicate_suppressed", "key": key}
            # atomic check-and-commit: the ledger append and the key
            # registration happen under the same lock; the fsync makes the
            # commit durable before we report success.
            rec = {"workflow_id": workflow_id, "step_uid": step_uid,
                   "action": action, "target": target, "note": note,
                   "key": key, "epoch": epoch, "t": time.time()}
            line = (json.dumps(rec, separators=(",", ":")) + "\n").encode()
            with open(self.ledger_path, "ab", buffering=0) as f:
                f.write(line)
                os.fsync(f.fileno())
            if key is not None:
                seen.add(key)
            return 200, {"status": "committed", "key": key}


STATE = None


class Handler(BaseHTTPRequestHandler):
    server_version = "A1ToolServer/1.0"

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"status": "ok",
                             "state_dir": STATE.state_dir,
                             "started": STATE.started})
        elif self.path == "/stats":
            self._send(200, {"status": "ok",
                             "fenced_rejections": STATE.fenced_rejections,
                             "workflows": len(STATE.seen_keys)})
        else:
            self._send(404, {"status": "not_found"})

    def do_POST(self):
        try:
            body = self._read_json()
        except (json.JSONDecodeError, ValueError):
            self._send(400, {"status": "bad_request"})
            return
        if self.path == "/tool":
            code, resp = STATE.call(
                body.get("workflow_id"), body.get("step_uid"),
                body.get("action"), body.get("target"), body.get("note"),
                body.get("key"), body.get("epoch"))
            self._send(code, resp)
        elif self.path == "/fence":
            max_epoch = STATE.fence(body.get("workflow_id"),
                                    int(body.get("epoch", 0)))
            self._send(200, {"status": "ok", "max_epoch": max_epoch})
        else:
            self._send(404, {"status": "not_found"})

    def log_message(self, fmt, *args):  # keep stderr clean
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    global STATE
    STATE = ToolState(args.state_dir)
    STATE.started = time.time()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
