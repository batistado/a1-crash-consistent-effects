"""Networked linearizable ClaimStore and Log-Fenced Checkpoint service (`HTTPClaimStore`).

Addresses disaggregated multi-node deployments where primary and recovery workers
execute on independent container/VM hosts with NO shared POSIX filesystem.
`RemoteClaimStoreServer` exposes atomic linearizable RPCs backed by transactional
`SQLite-WAL` (`synchronous=FULL`), modeling cloud transactional state stores
(e.g., PostgreSQL `INSERT ... ON CONFLICT DO NOTHING RETURNING *`, CockroachDB,
DynamoDB conditional `PutItem`, or `etcd` compare-and-swap transactions).
"""

from __future__ import annotations

import http.client
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .claim_store import ClaimRecord, SQLiteWALClaimStore, atomic_write_json


def _record_to_wire(rec: ClaimRecord) -> Dict[str, Any]:
    return {
        "wid": rec.wid,
        "uid": rec.uid,
        "action": rec.action,
        "target": rec.target,
        "occurrence": rec.occurrence,
        "args": rec.args,
        "key": rec.key,
        "epoch": rec.epoch,
        "committed": rec.committed,
        "result": rec.result,
    }


def _wire_to_record(d: Dict[str, Any]) -> ClaimRecord:
    return ClaimRecord(
        wid=str(d["wid"]),
        uid=str(d["uid"]),
        action=str(d["action"]),
        target=str(d["target"]),
        occurrence=int(d["occurrence"]),
        args=dict(d.get("args") or {}),
        key=str(d["key"]),
        epoch=int(d["epoch"]),
        committed=bool(d.get("committed", False)),
        result=d.get("result"),
    )


class RemoteClaimStoreState:
    """Thread-safe, per-workflow state coordinator for multi-node `L` and `C`."""

    def __init__(self, root_dir: str) -> None:
        self.root_dir = os.path.abspath(root_dir)
        os.makedirs(self.root_dir, exist_ok=True)
        self._meta_lock = threading.Lock()
        self._wf_locks: Dict[str, threading.Lock] = {}
        self._stores: Dict[str, SQLiteWALClaimStore] = {}

    def _get_wf(self, wid: str) -> Tuple[threading.Lock, SQLiteWALClaimStore, str]:
        with self._meta_lock:
            lk = self._wf_locks.get(wid)
            if lk is None:
                lk = threading.Lock()
                self._wf_locks[wid] = lk
            st = self._stores.get(wid)
            if st is None:
                safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in wid)
                db_path = os.path.join(self.root_dir, f"{safe}.sqlite")
                st = SQLiteWALClaimStore(db_path)
                self._stores[wid] = st
            ckpt_path = os.path.join(self.root_dir, f"{wid}.ckpt.json")
            return lk, st, ckpt_path

    def create_or_reuse(self, body: Dict[str, Any]) -> Dict[str, Any]:
        wid = str(body["wid"])
        lk, st, _ = self._get_wf(wid)
        with lk:
            rec, reused = st.create_or_reuse(
                wid=wid,
                uid=str(body["uid"]),
                action=str(body["action"]),
                target=str(body["target"]),
                args=dict(body.get("args") or {}),
                epoch=int(body["epoch"]),
                occurrence=body.get("occurrence"),
                key_override=body.get("key_override"),
            )
            return {"record": _record_to_wire(rec), "reused": reused}

    def append_commit(self, body: Dict[str, Any]) -> Dict[str, Any]:
        wid = str(body["wid"])
        lk, st, _ = self._get_wf(wid)
        with lk:
            rec = st.append_commit(str(body["key"]), result=body.get("result"))
            return {"record": _record_to_wire(rec)}

    def find_by_identity(self, body: Dict[str, Any]) -> Dict[str, Any]:
        wid = str(body["wid"])
        lk, st, _ = self._get_wf(wid)
        with lk:
            rec = st.find_by_identity(
                str(body["action"]),
                str(body["target"]),
                int(body.get("occurrence", 0)),
            )
            return {"record": _record_to_wire(rec) if rec else None}

    def list_claims(self, wid: str, uncommitted_only: bool = False) -> Dict[str, Any]:
        lk, st, _ = self._get_wf(wid)
        with lk:
            recs = st.uncommitted() if uncommitted_only else st.claims()
            return {"records": [_record_to_wire(r) for r in recs]}

    def is_committed(self, wid: str, key: str) -> Dict[str, Any]:
        lk, st, _ = self._get_wf(wid)
        with lk:
            return {"committed": st.is_committed(key)}

    def read_checkpoint(self, wid: str) -> Dict[str, Any]:
        lk, _, ckpt_path = self._get_wf(wid)
        with lk:
            if not os.path.exists(ckpt_path):
                return {"checkpoint": -1, "epoch": 0, "tokens": {}}
            try:
                with open(ckpt_path, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                return {"checkpoint": -1, "epoch": 0, "tokens": {}}

    def advance_checkpoint(self, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        wid = str(body["wid"])
        step_index = int(body["step_index"])
        epoch = int(body.get("epoch", 0))
        claim_key = body.get("claim_key")
        tokens_update = dict(body.get("tokens") or {})

        lk, st, ckpt_path = self._get_wf(wid)
        with lk:
            if claim_key is not None and not st.is_committed(str(claim_key)):
                return 409, {
                    "status": "log_fence_violation",
                    "detail": f"Key {claim_key} not committed in remote ClaimStore",
                }
            cur_obj = {"checkpoint": -1, "epoch": 0, "tokens": {}}
            if os.path.exists(ckpt_path):
                try:
                    with open(ckpt_path, encoding="utf-8") as f:
                        cur_obj = json.load(f)
                except (OSError, ValueError):
                    pass
            merged_tokens = dict(cur_obj.get("tokens") or {})
            merged_tokens.update(tokens_update)
            new_ckpt = max(int(cur_obj.get("checkpoint", -1)), step_index)
            new_obj = {
                "checkpoint": new_ckpt,
                "epoch": max(int(cur_obj.get("epoch", 0)), epoch),
                "tokens": merged_tokens,
            }
            atomic_write_json(ckpt_path, new_obj)
            return 200, new_obj


def start_remote_claim_store_in_thread(
    state: RemoteClaimStoreState, host: str = "127.0.0.1", port: int = 0
) -> Tuple[ThreadingHTTPServer, str]:
    """Start a multi-threaded HTTP/1.1 remote state server for multi-node workers."""

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
            p = self.path
            if p == "/claim/create_or_reuse":
                self._send(200, state.create_or_reuse(body))
            elif p == "/claim/commit":
                self._send(200, state.append_commit(body))
            elif p == "/claim/find":
                self._send(200, state.find_by_identity(body))
            elif p == "/claim/list":
                self._send(
                    200,
                    state.list_claims(
                        str(body["wid"]), bool(body.get("uncommitted_only", False))
                    ),
                )
            elif p == "/claim/is_committed":
                self._send(200, state.is_committed(str(body["wid"]), str(body["key"])))
            elif p == "/ckpt/read":
                self._send(200, state.read_checkpoint(str(body["wid"])))
            elif p == "/ckpt/advance":
                code, resp = state.advance_checkpoint(body)
                self._send(code, resp)
            else:
                self._send(404, {"error": "not_found"})

    httpd = ThreadingHTTPServer((host, port), Handler)
    actual_port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, f"http://{host}:{actual_port}"


class HTTPClaimStore:
    """Multi-node networked ClaimStore & Log-Fenced Checkpoint client.

    Drop-in replacement for `IndexedJSONLClaimStore` and `SQLiteWALClaimStore`
    requiring zero shared POSIX filesystem between primary and recovery nodes.
    Uses thread-local HTTP/1.1 keep-alive sockets for low-latency RPCs.
    """

    def __init__(self, base_url: str, workflow_id: str, timeout: float = 15.0) -> None:
        parsed = urlparse(base_url)
        self.base_url = base_url.rstrip("/")
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        self.workflow_id = workflow_id
        self.timeout = timeout
        self._tls = threading.local()

    def _post(self, path: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        for attempt in range(2):
            conn: Optional[http.client.HTTPConnection] = getattr(self._tls, "conn", None)
            if conn is None:
                conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
                self._tls.conn = conn
            try:
                conn.request(
                    "POST",
                    path,
                    body=raw,
                    headers={
                        "Content-Type": "application/json",
                        "Content-Length": str(len(raw)),
                        "Connection": "keep-alive",
                    },
                )
                resp = conn.getresponse()
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data
            except (OSError, http.client.HTTPException):
                try:
                    conn.close()
                except OSError:
                    pass
                self._tls.conn = None
                if attempt == 1:
                    raise
        raise RuntimeError("Unreachable")

    def create_or_reuse(
        self,
        wid: str,
        uid: str,
        action: str,
        target: str,
        args: Dict[str, Any],
        epoch: int,
        occurrence: Optional[int] = None,
        key_override: Optional[str] = None,
    ) -> Tuple[ClaimRecord, bool]:
        _, data = self._post(
            "/claim/create_or_reuse",
            {
                "wid": wid,
                "uid": uid,
                "action": action,
                "target": target,
                "args": args,
                "epoch": epoch,
                "occurrence": occurrence,
                "key_override": key_override,
            },
        )
        return _wire_to_record(data["record"]), bool(data["reused"])

    def append_commit(
        self, key: str, result: Optional[Dict[str, Any]] = None
    ) -> ClaimRecord:
        _, data = self._post(
            "/claim/commit",
            {"wid": self.workflow_id, "key": key, "result": result},
        )
        return _wire_to_record(data["record"])

    def find_by_identity(
        self, action: str, target: str, occurrence: int = 0
    ) -> Optional[ClaimRecord]:
        _, data = self._post(
            "/claim/find",
            {
                "wid": self.workflow_id,
                "action": action,
                "target": target,
                "occurrence": occurrence,
            },
        )
        return _wire_to_record(data["record"]) if data.get("record") else None

    def uncommitted(self) -> List[ClaimRecord]:
        _, data = self._post(
            "/claim/list", {"wid": self.workflow_id, "uncommitted_only": True}
        )
        return [_wire_to_record(r) for r in data["records"]]

    def claims(self) -> List[ClaimRecord]:
        _, data = self._post(
            "/claim/list", {"wid": self.workflow_id, "uncommitted_only": False}
        )
        return [_wire_to_record(r) for r in data["records"]]

    def is_committed(self, key: str) -> bool:
        _, data = self._post(
            "/claim/is_committed", {"wid": self.workflow_id, "key": key}
        )
        return bool(data["committed"])

    def read_remote_checkpoint(self) -> Dict[str, Any]:
        _, data = self._post("/ckpt/read", {"wid": self.workflow_id})
        return data

    def advance_remote_checkpoint(
        self,
        step_index: int,
        epoch: int,
        claim_key: Optional[str] = None,
        tokens: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        code, data = self._post(
            "/ckpt/advance",
            {
                "wid": self.workflow_id,
                "step_index": step_index,
                "epoch": epoch,
                "claim_key": claim_key,
                "tokens": tokens or {},
            },
        )
        if code != 200:
            raise RuntimeError(f"Remote log-fenced checkpoint failed: {data}")
        return data
