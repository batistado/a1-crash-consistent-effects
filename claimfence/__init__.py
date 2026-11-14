"""ClaimFence: Crash-consistent write-ahead effect-claim logging, atomic lease fencing,
and payload-preserving reconciliation for distributed agentic workflows.
"""

from .claim_store import (
    ClaimRecord,
    IndexedJSONLClaimStore,
    SQLiteWALClaimStore,
    atomic_write_json,
)
from .receiver import AtomicIdempotentReceiver, FencedError, start_tool_server_in_thread
from .reconciler import ClaimFenceRuntime

__all__ = [
    "ClaimRecord",
    "IndexedJSONLClaimStore",
    "SQLiteWALClaimStore",
    "atomic_write_json",
    "AtomicIdempotentReceiver",
    "FencedError",
    "start_tool_server_in_thread",
    "ClaimFenceRuntime",
]
__version__ = "2.0.0"
