"""Transactional Outbox & Epoch-Fencing Proxy for Unmodified Third-Party APIs.

Commercial SaaS APIs (e.g., Stripe, Adyen, AWS) support `Idempotency-Key` headers
but do not expose ClaimFence's `/fence` `CAS_inc` endpoint; legacy internal REST
services often lack idempotency keys altogether. `TransactionalOutboxProxy` bridges
Assumption A1 without modifying the upstream backend `U`:
  1. Enforces atomic per-workflow `CAS_inc` epoch-lease fencing (`/fence`, `/tool`).
  2. Persists a durable `PENDING` outbox record in SQLite-WAL (`synchronous=FULL`)
     prior to forwarding the HTTP call to `U` with header `Idempotency-Key: <key>`.
  3. Persists `COMPLETED` + the upstream return JSON payload (`receipt_token`)
     for RIFL-complete payload replay across worker and proxy restarts.

Boundary characterization:
  - When upstream `U` honors `Idempotency-Key` (Stripe/AWS model), BOTH worker crashes
    in `W(s)` AND proxy crashes in `W_proxy = (t_U_commit, t_outbox_complete)` achieve
    exact-once execution and 100% payload preservation.
  - When upstream `U` is completely non-idempotent (legacy REST), 100% of agent-worker
    crashes, stale zombies, and dual recoveries are eliminated; residual duplication
    occurs iff the proxy host itself crashes inside `W_proxy`.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, Optional, Tuple


class TransactionalOutboxProxy:
    """Durable fencing + outbox sidecar fronting an unmodified upstream HTTP API."""

    def __init__(
        self,
        db_path: str,
        upstream_url: str,
        timeout: float = 15.0,
    ) -> None:
        self.db_path = os.path.abspath(db_path)
        self.upstream_url = upstream_url.rstrip("/")
        self.timeout = timeout
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._meta_lock = threading.Lock()
        self._wf_locks: Dict[str, threading.Lock] = {}
        self.fenced_rejections: int = 0
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=FULL;")
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fences (
                    wid TEXT PRIMARY KEY,
                    max_epoch INTEGER NOT NULL,
                    holder_id TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outbox (
                    wid TEXT NOT NULL,
                    key TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    PRIMARY KEY (wid, key)
                );
                """
            )
        finally:
            conn.close()

    def _lock_for(self, wid: str) -> threading.Lock:
        with self._meta_lock:
            lk = self._wf_locks.get(wid)
            if lk is None:
                lk = threading.Lock()
                self._wf_locks[wid] = lk
            return lk

    def acquire_fence_atomic(self, workflow_id: str, holder_id: str) -> Dict[str, Any]:
        lk = self._lock_for(workflow_id)
        with lk:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                row = conn.execute(
                    "SELECT max_epoch FROM fences WHERE wid = ?;", (workflow_id,)
                ).fetchone()
                new_epoch = (int(row[0]) + 1) if row else 1
                conn.execute(
                    """
                    INSERT INTO fences (wid, max_epoch, holder_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(wid) DO UPDATE SET
                        max_epoch = excluded.max_epoch,
                        holder_id = excluded.holder_id;
                    """,
                    (workflow_id, new_epoch, holder_id),
                )
                conn.execute("COMMIT;")
                return {
                    "workflow_id": workflow_id,
                    "epoch": new_epoch,
                    "holder_id": holder_id,
                }
            except BaseException:
                conn.execute("ROLLBACK;")
                raise
            finally:
                conn.close()

    def call(
        self,
        workflow_id: str,
        step_uid: str,
        action: str,
        target: str,
        args: Dict[str, Any],
        key: str,
        epoch: int = 0,
        holder_id: Optional[str] = None,
        proxy_crash_hook: Optional[Callable[[str], None]] = None,
    ) -> Tuple[int, Dict[str, Any]]:
        lk = self._lock_for(workflow_id)
        with lk:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE;")
                frow = conn.execute(
                    "SELECT max_epoch, holder_id FROM fences WHERE wid = ?;",
                    (workflow_id,),
                ).fetchone()
                cur_epoch = int(frow[0]) if frow else 0
                cur_holder = str(frow[1]) if frow else None

                if epoch < cur_epoch or (
                    cur_epoch > 0
                    and epoch == cur_epoch
                    and cur_holder is not None
                    and holder_id is not None
                    and holder_id != cur_holder
                ):
                    conn.execute("COMMIT;")
                    self.fenced_rejections += 1
                    return 409, {
                        "status": "fenced",
                        "epoch": epoch,
                        "max_epoch": cur_epoch,
                        "holder": cur_holder,
                    }

                if epoch > cur_epoch:
                    conn.execute(
                        """
                        INSERT INTO fences (wid, max_epoch, holder_id)
                        VALUES (?, ?, ?)
                        ON CONFLICT(wid) DO UPDATE SET
                            max_epoch = excluded.max_epoch,
                            holder_id = excluded.holder_id;
                        """,
                        (workflow_id, epoch, holder_id or ""),
                    )

                orow = conn.execute(
                    "SELECT status, result_json FROM outbox WHERE wid = ? AND key = ?;",
                    (workflow_id, key),
                ).fetchone()
                if orow and orow[0] == "COMPLETED":
                    conn.execute("COMMIT;")
                    saved = json.loads(orow[1]) if orow[1] else None
                    return 200, {
                        "status": "duplicate_suppressed",
                        "key": key,
                        "result": saved,
                    }

                if not orow:
                    conn.execute(
                        """
                        INSERT INTO outbox (wid, key, action, target, status, result_json)
                        VALUES (?, ?, ?, ?, 'PENDING', NULL);
                        """,
                        (workflow_id, key, action, target),
                    )
                conn.execute("COMMIT;")
            except BaseException:
                conn.execute("ROLLBACK;")
                raise
            finally:
                conn.close()

            if proxy_crash_hook:
                proxy_crash_hook("after_outbox_pending_before_upstream")

            # Forward to unmodified upstream API with standard Idempotency-Key header
            up_body = json.dumps(
                {
                    "workflow_id": workflow_id,
                    "step_uid": step_uid,
                    "action": action,
                    "target": target,
                    "args": args,
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                self.upstream_url + "/upstream_mutate",
                data=up_body,
                headers={
                    "Content-Type": "application/json",
                    "Idempotency-Key": key,
                },
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                up_resp = json.loads(resp.read().decode("utf-8"))

            if proxy_crash_hook:
                # Residual proxy crash window W_proxy = (t_U_commit, t_outbox_complete)
                proxy_crash_hook("after_upstream_before_outbox_complete")

            result_payload = up_resp.get("result", up_resp)
            conn2 = self._connect()
            try:
                conn2.execute("BEGIN IMMEDIATE;")
                conn2.execute(
                    """
                    UPDATE outbox
                    SET status = 'COMPLETED', result_json = ?
                    WHERE wid = ? AND key = ?;
                    """,
                    (json.dumps(result_payload), workflow_id, key),
                )
                conn2.execute("COMMIT;")
            except BaseException:
                conn2.execute("ROLLBACK;")
                raise
            finally:
                conn2.close()

            return 200, {
                "status": "committed",
                "key": key,
                "result": result_payload,
            }


def start_outbox_proxy_in_thread(
    proxy: TransactionalOutboxProxy, host: str = "127.0.0.1", port: int = 0
) -> Tuple[ThreadingHTTPServer, str]:
    """Expose `TransactionalOutboxProxy` over HTTP (`/fence` and `/tool`)."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _send(self, code: int, obj: Dict[str, Any]) -> None:
            raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if self.path == "/fence":
                res = proxy.acquire_fence_atomic(
                    str(body["workflow_id"]), str(body["holder_id"])
                )
                self._send(200, res)
            elif self.path == "/tool":
                code, res = proxy.call(
                    workflow_id=str(body["workflow_id"]),
                    step_uid=str(body.get("step_uid", "0")),
                    action=str(body["action"]),
                    target=str(body["target"]),
                    args=dict(body.get("args") or {}),
                    key=str(body["key"]),
                    epoch=int(body.get("epoch", 0)),
                    holder_id=body.get("holder_id"),
                )
                self._send(code, res)
            else:
                self._send(404, {"error": "not_found"})

    httpd = ThreadingHTTPServer((host, port), Handler)
    actual_port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, f"http://{host}:{actual_port}"
