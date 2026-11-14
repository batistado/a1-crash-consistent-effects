"""Durable, concurrency-safe, O(1)-indexed write-ahead effect-claim stores.

Provides two crash-consistent storage backends implementing the same interface:
1. IndexedJSONLClaimStore: Append-only JSONL log with per-record fsync, torn-tail
   recovery, O(1) in-memory hash index over (action, target, occurrence),
   incremental tail refresh across OS processes, and POSIX fcntl.flock exclusive
   serialization for concurrent worker create-or-reuse (lifting Assumption A6).
2. SQLiteWALClaimStore: Transactional SQLite backend running in WAL mode with
   PRAGMA synchronous=FULL and BEGIN IMMEDIATE serialization for high-throughput
   multi-worker deployments.
"""

from __future__ import annotations

import dataclasses
import fcntl
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple


def atomic_write_json(path: str, obj: Any) -> None:
    """Crash-safe atomic file replacement: write temp + fsync + rename + fsync dir."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        dirfd = os.open(d, os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@dataclasses.dataclass
class ClaimRecord:
    wid: str
    uid: str
    action: str
    target: str
    occurrence: int
    args: Dict[str, Any]
    key: str
    epoch: int
    committed: bool = False
    result: Optional[Dict[str, Any]] = None

    @property
    def identity(self) -> Tuple[str, str, int]:
        return (self.action, self.target, self.occurrence)

    def to_dict(self, kind: str) -> Dict[str, Any]:
        return {
            "kind": kind,
            "wid": self.wid,
            "uid": self.uid,
            "action": self.action,
            "target": self.target,
            "occurrence": self.occurrence,
            "args": self.args,
            "key": self.key,
            "epoch": self.epoch,
            "committed": (kind == "commit"),
            "result": self.result,
        }


class IndexedJSONLClaimStore:
    """Append-only fsync'd JSONL claim log with O(1) identity index and flock serialization."""

    def __init__(self, path: str, full_fsync: bool = False) -> None:
        self.path = os.path.abspath(path)
        self.lock_path = self.path + ".lock"
        self.full_fsync = full_fsync
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._offset: int = 0
        self._inode: Optional[int] = None
        self._by_identity: Dict[Tuple[str, str, int], ClaimRecord] = {}
        self._by_key: Dict[str, ClaimRecord] = {}
        self._order: List[str] = []  # claim keys in creation order
        self._occ_counts: Dict[Tuple[str, str], int] = {}
        self._refresh_unlocked()

    def _sync_fd(self, fd: int) -> None:
        if self.full_fsync and hasattr(fcntl, "F_FULLFSYNC"):
            fcntl.fcntl(fd, fcntl.F_FULLFSYNC)
        else:
            os.fsync(fd)

    @contextmanager
    def _exclusive_lock(self):
        with open(self.lock_path, "a+b") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def _reset_index(self) -> None:
        self._offset = 0
        self._inode = None
        self._by_identity.clear()
        self._by_key.clear()
        self._order.clear()
        self._occ_counts.clear()

    def _apply_record(self, raw_rec: Dict[str, Any]) -> None:
        kind = raw_rec.get("kind")
        key = raw_rec.get("key")
        if not key:
            return
        if kind == "claim":
            if key not in self._by_key:
                rec = ClaimRecord(
                    wid=raw_rec.get("wid", ""),
                    uid=str(raw_rec.get("uid", "")),
                    action=raw_rec["action"],
                    target=raw_rec["target"],
                    occurrence=int(raw_rec.get("occurrence", 0)),
                    args=dict(raw_rec.get("args") or {}),
                    key=key,
                    epoch=int(raw_rec.get("epoch", 0)),
                    committed=False,
                    result=None,
                )
                self._by_key[key] = rec
                self._by_identity[rec.identity] = rec
                self._order.append(key)
                pair = (rec.action, rec.target)
                self._occ_counts[pair] = max(
                    self._occ_counts.get(pair, 0), rec.occurrence + 1
                )
        elif kind == "commit":
            rec = self._by_key.get(key)
            if rec is not None:
                rec.committed = True
                if raw_rec.get("result") is not None:
                    rec.result = raw_rec["result"]

    def _refresh_unlocked(self) -> None:
        """Incrementally parse only newly appended complete lines since self._offset."""
        if not os.path.exists(self.path):
            self._reset_index()
            return
        st = os.stat(self.path)
        if self._inode != st.st_ino or st.st_size < self._offset:
            self._reset_index()
            self._inode = st.st_ino
        if st.st_size == self._offset:
            return
        with open(self.path, "rb") as f:
            f.seek(self._offset)
            chunk = f.read()
        if not chunk:
            return
        lines = chunk.split(b"\n")
        # Last element after split(b"\n") is b"" iff file ends cleanly with newline.
        complete_lines = lines[:-1]
        trailing = lines[-1]
        consumed = len(chunk) - len(trailing)
        for i, line in enumerate(complete_lines):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                # Non-trailing corrupt line is genuine mid-file corruption
                if i == len(complete_lines) - 1 and not trailing:
                    continue
                raise ValueError(f"Corrupt non-trailing log record in {self.path}") from exc
            self._apply_record(obj)
        # Note: if trailing != b"", it is a torn tail record (crash mid-write);
        # we deliberately leave _offset before `trailing` and skip it on load.
        self._offset += consumed

    def _append_raw_unlocked(self, payload: Dict[str, Any]) -> int:
        line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        with open(self.path, "r+b" if os.path.exists(self.path) else "w+b", buffering=0) as f:
            st = os.fstat(f.fileno())
            if st.st_size > self._offset:
                # Standard WAL tail truncation: discard torn trailing bytes before appending
                f.truncate(self._offset)
            f.seek(0, os.SEEK_END)
            f.write(line)
            self._sync_fd(f.fileno())
        self._refresh_unlocked()
        return len(line)

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
        """Atomically look up (action, target, occurrence) or append a fresh CLAIM.

        Serialized across threads and OS processes via POSIX flock so two concurrent
        workers never bind two keys to the same logical identity (lifts A6).
        Returns (claim_record, was_reused).
        """
        with self._exclusive_lock():
            self._refresh_unlocked()
            if occurrence is None:
                occurrence = self._occ_counts.get((action, target), 0)
            ident = (action, target, occurrence)
            existing = self._by_identity.get(ident)
            if existing is not None:
                return existing, True
            key = key_override or f"cf:{wid}:{action}:{target}:occ{occurrence}"
            rec = ClaimRecord(
                wid=wid,
                uid=uid,
                action=action,
                target=target,
                occurrence=occurrence,
                args=dict(args),
                key=key,
                epoch=epoch,
                committed=False,
                result=None,
            )
            self._append_raw_unlocked(rec.to_dict("claim"))
            return self._by_key[key], False

    def append_commit(
        self, key: str, result: Optional[Dict[str, Any]] = None
    ) -> ClaimRecord:
        with self._exclusive_lock():
            self._refresh_unlocked()
            rec = self._by_key.get(key)
            if rec is None:
                raise KeyError(f"Cannot commit unknown claim key: {key}")
            if not rec.committed or (result is not None and rec.result is None):
                rec.committed = True
                rec.result = result
                self._append_raw_unlocked(rec.to_dict("commit"))
            return rec

    def find_by_identity(
        self, action: str, target: str, occurrence: int = 0
    ) -> Optional[ClaimRecord]:
        self._refresh_unlocked()
        return self._by_identity.get((action, target, occurrence))

    def next_occurrence(self, action: str, target: str) -> int:
        self._refresh_unlocked()
        return self._occ_counts.get((action, target), 0)

    def uncommitted(self) -> List[ClaimRecord]:
        self._refresh_unlocked()
        return [self._by_key[k] for k in self._order if not self._by_key[k].committed]

    def claims(self) -> List[ClaimRecord]:
        self._refresh_unlocked()
        return [self._by_key[k] for k in self._order]

    def is_committed(self, key: str) -> bool:
        self._refresh_unlocked()
        rec = self._by_key.get(key)
        return bool(rec and rec.committed)


class SQLiteWALClaimStore:
    """Transactional SQLite-WAL claim store with O(1) B-tree indexing and FULL sync."""

    def __init__(self, db_path: str) -> None:
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn = sqlite3.connect(
            self.db_path, timeout=30.0, isolation_level=None, check_same_thread=False
        )
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=FULL;")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS claims (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                wid TEXT NOT NULL,
                uid TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                occurrence INTEGER NOT NULL,
                args_json TEXT NOT NULL,
                key TEXT NOT NULL UNIQUE,
                epoch INTEGER NOT NULL,
                committed INTEGER NOT NULL DEFAULT 0,
                result_json TEXT,
                UNIQUE(action, target, occurrence)
            );
            """
        )

    def close(self) -> None:
        self._conn.close()

    def _row_to_rec(self, row: Tuple[Any, ...]) -> ClaimRecord:
        _, wid, uid, action, target, occ, args_s, key, epoch, comm, res_s = row
        return ClaimRecord(
            wid=wid,
            uid=uid,
            action=action,
            target=target,
            occurrence=int(occ),
            args=json.loads(args_s),
            key=key,
            epoch=int(epoch),
            committed=bool(comm),
            result=json.loads(res_s) if res_s else None,
        )

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
        self._conn.execute("BEGIN IMMEDIATE;")
        try:
            if occurrence is None:
                cur = self._conn.execute(
                    "SELECT COUNT(*) FROM claims WHERE action=? AND target=?;",
                    (action, target),
                )
                occurrence = int(cur.fetchone()[0])
            cur = self._conn.execute(
                "SELECT * FROM claims WHERE action=? AND target=? AND occurrence=?;",
                (action, target, occurrence),
            )
            row = cur.fetchone()
            if row is not None:
                self._conn.execute("COMMIT;")
                return self._row_to_rec(row), True
            key = key_override or f"cf:{wid}:{action}:{target}:occ{occurrence}"
            self._conn.execute(
                """
                INSERT INTO claims
                (wid, uid, action, target, occurrence, args_json, key, epoch, committed, result_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL);
                """,
                (wid, uid, action, target, occurrence, json.dumps(args), key, epoch),
            )
            cur2 = self._conn.execute("SELECT * FROM claims WHERE key=?;", (key,))
            rec = self._row_to_rec(cur2.fetchone())
            self._conn.execute("COMMIT;")
            return rec, False
        except BaseException:
            self._conn.execute("ROLLBACK;")
            raise

    def append_commit(
        self, key: str, result: Optional[Dict[str, Any]] = None
    ) -> ClaimRecord:
        res_s = json.dumps(result) if result is not None else None
        self._conn.execute("BEGIN IMMEDIATE;")
        try:
            self._conn.execute(
                "UPDATE claims SET committed=1, result_json=COALESCE(?, result_json) WHERE key=?;",
                (res_s, key),
            )
            cur = self._conn.execute("SELECT * FROM claims WHERE key=?;", (key,))
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"Unknown claim key: {key}")
            self._conn.execute("COMMIT;")
            return self._row_to_rec(row)
        except BaseException:
            self._conn.execute("ROLLBACK;")
            raise

    def find_by_identity(
        self, action: str, target: str, occurrence: int = 0
    ) -> Optional[ClaimRecord]:
        cur = self._conn.execute(
            "SELECT * FROM claims WHERE action=? AND target=? AND occurrence=?;",
            (action, target, occurrence),
        )
        row = cur.fetchone()
        return self._row_to_rec(row) if row else None

    def next_occurrence(self, action: str, target: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM claims WHERE action=? AND target=?;",
            (action, target),
        )
        return int(cur.fetchone()[0])

    def uncommitted(self) -> List[ClaimRecord]:
        cur = self._conn.execute(
            "SELECT * FROM claims WHERE committed=0 ORDER BY seq ASC;"
        )
        return [self._row_to_rec(r) for r in cur.fetchall()]

    def claims(self) -> List[ClaimRecord]:
        cur = self._conn.execute("SELECT * FROM claims ORDER BY seq ASC;")
        return [self._row_to_rec(r) for r in cur.fetchall()]

    def is_committed(self, key: str) -> bool:
        cur = self._conn.execute(
            "SELECT committed FROM claims WHERE key=?;", (key,)
        )
        row = cur.fetchone()
        return bool(row and row[0])
