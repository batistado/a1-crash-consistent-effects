"""ClaimFence: Crash-consistent write-ahead effect-claim logging, atomic lease fencing,
and payload-preserving reconciliation for stateful and multi-node agentic workflows.
"""

from .claim_store import (
    ClaimRecord,
    IndexedJSONLClaimStore,
    SQLiteWALClaimStore,
    atomic_write_json,
)
from .extractor import (
    AuthorizationViolationError,
    CanonicalIdentityExtractor,
    ExtractedIdentity,
    default_canonicalize_target,
)
from .network_store import (
    HTTPClaimStore,
    RemoteClaimStoreState,
    start_remote_claim_store_in_thread,
)
from .outbox_proxy import TransactionalOutboxProxy, start_outbox_proxy_in_thread
from .receiver import AtomicIdempotentReceiver, FencedError, start_tool_server_in_thread
from .reconciler import ClaimFenceRuntime

__all__ = [
    "ClaimRecord",
    "IndexedJSONLClaimStore",
    "SQLiteWALClaimStore",
    "atomic_write_json",
    "AuthorizationViolationError",
    "CanonicalIdentityExtractor",
    "ExtractedIdentity",
    "default_canonicalize_target",
    "HTTPClaimStore",
    "RemoteClaimStoreState",
    "start_remote_claim_store_in_thread",
    "TransactionalOutboxProxy",
    "start_outbox_proxy_in_thread",
    "AtomicIdempotentReceiver",
    "FencedError",
    "start_tool_server_in_thread",
    "ClaimFenceRuntime",
]
__version__ = "2.1.0"
