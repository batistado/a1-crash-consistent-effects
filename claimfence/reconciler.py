"""ClaimFence execution and reconciliation runtime.

Implements:
- Pre-invocation durable claim discipline (`create_or_reuse`)
- Log-fenced checkpoint advancement (`checkpoint <= max_committed_step`)
- Reconciliation-first recovery under server-allocated atomic monotonic epoch fences
- Payload-preserving semantic skip (`(action, target, occurrence)` -> cached result)
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Callable, Dict, Optional, Tuple, Union

from .claim_store import (
    ClaimRecord,
    IndexedJSONLClaimStore,
    SQLiteWALClaimStore,
    atomic_write_json,
)
from .receiver import AtomicIdempotentReceiver, FencedError

ClaimStoreType = Union[IndexedJSONLClaimStore, SQLiteWALClaimStore]


class ClaimFenceRuntime:
    """Client/worker harness runtime enforcing the ClaimFence crash-consistency protocol."""

    def __init__(
        self,
        workflow_id: str,
        store: ClaimStoreType,
        checkpoint_path: str,
        receiver: AtomicIdempotentReceiver,
        holder_id: Optional[str] = None,
    ) -> None:
        self.workflow_id = workflow_id
        self.store = store
        self.checkpoint_path = os.path.abspath(checkpoint_path)
        self.receiver = receiver
        self.holder_id = holder_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.epoch: int = 0

    def read_checkpoint(self) -> Dict[str, Any]:
        if not os.path.exists(self.checkpoint_path):
            return {"checkpoint": -1, "epoch": 0}
        import json

        try:
            with open(self.checkpoint_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"checkpoint": -1, "epoch": 0}

    def advance_checkpoint(self, step_index: int, claim_key: str) -> None:
        """Log-fenced checkpoint write: refuses to advance unless COMMIT(key) is durable."""
        if not self.store.is_committed(claim_key):
            raise RuntimeError(
                f"Log-fenced checkpoint violation: key {claim_key} is not committed in ClaimStore"
            )
        cur = self.read_checkpoint().get("checkpoint", -1)
        if step_index >= cur:
            atomic_write_json(
                self.checkpoint_path,
                {"checkpoint": step_index, "epoch": self.epoch},
            )

    def execute_step(
        self,
        step_index: int,
        action: str,
        target: str,
        args: Dict[str, Any],
        occurrence: int = 0,
        crash_hook: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """Execute one effectful step under full ClaimFence discipline.

        Returns the committed (or replayed) tool result payload.
        `crash_hook(stage)` may inject faults at stages:
          - "after_claim_before_call"
          - "after_call_before_commit_log"   (the critical W(s) window!)
          - "after_commit_log_before_ckpt"   (sub-window [t_mark, t_ckpt))
          - "after_ckpt"
        """
        claim, reused = self.store.create_or_reuse(
            wid=self.workflow_id,
            uid=str(step_index),
            action=action,
            target=target,
            args=args,
            epoch=self.epoch,
            occurrence=occurrence,
        )
        if reused and claim.committed:
            # Semantic skip: return cached result payload directly without re-calling T
            return {
                "status": "skipped_via_log",
                "key": claim.key,
                "result": claim.result,
            }

        if crash_hook:
            crash_hook("after_claim_before_call")

        code, resp = self.receiver.call(
            workflow_id=self.workflow_id,
            step_uid=str(step_index),
            action=action,
            target=target,
            args=args,
            key=claim.key,
            epoch=self.epoch,
            holder_id=self.holder_id,
        )
        if code == 409 or resp.get("status") == "fenced":
            raise FencedError(f"Writer {self.holder_id} fenced at epoch {self.epoch}")

        if crash_hook:
            crash_hook("after_call_before_commit_log")

        result_payload = resp.get("result")
        updated = self.store.append_commit(claim.key, result=result_payload)

        if crash_hook:
            crash_hook("after_commit_log_before_ckpt")

        self.advance_checkpoint(step_index, updated.key)

        if crash_hook:
            crash_hook("after_ckpt")

        return {
            "status": resp["status"],
            "key": updated.key,
            "result": updated.result,
        }

    def recover(self) -> Dict[str, Any]:
        """Reconciliation-first recovery with server-allocated atomic monotonic fence."""
        fence_info = self.receiver.acquire_fence_atomic(
            self.workflow_id, holder_id=self.holder_id
        )
        self.epoch = int(fence_info["epoch"])
        replayed = 0
        for claim in self.store.uncommitted():
            code, resp = self.receiver.call(
                workflow_id=self.workflow_id,
                step_uid=claim.uid,
                action=claim.action,
                target=claim.target,
                args=claim.args,
                key=claim.key,
                epoch=self.epoch,
                holder_id=self.holder_id,
            )
            if code == 409 or resp.get("status") == "fenced":
                raise FencedError(
                    f"Recovery writer {self.holder_id} superseded during reconciliation"
                )
            self.store.append_commit(claim.key, result=resp.get("result"))
            replayed += 1

        # Advance log-fenced checkpoint past all settled integer-indexed claims
        settled_indices = []
        settled_keys = {}
        for c in self.store.claims():
            if c.committed:
                try:
                    idx = int(c.uid)
                    settled_indices.append(idx)
                    settled_keys[idx] = c.key
                except ValueError:
                    pass
        if settled_indices:
            max_idx = max(settled_indices)
            self.advance_checkpoint(max_idx, settled_keys[max_idx])

        return {
            "epoch": self.epoch,
            "replayed_claims": replayed,
            "checkpoint": self.read_checkpoint().get("checkpoint", -1),
        }

    def get_committed_result(
        self, action: str, target: str, occurrence: int = 0
    ) -> Optional[Dict[str, Any]]:
        rec = self.store.find_by_identity(action, target, occurrence)
        if rec and rec.committed:
            return rec.result
        return None
