"""Deterministic logical identity extraction and A4 authorization guardrails.

Formalizes the three-stage mapping from raw LLM tool-call JSON payloads to
ClaimFence's canonical `(action, target, occurrence)` logical identity:
  1. Schema action validation (separating read-only diagnostics from mutations)
  2. Entity-ID canonicalization (normalizing case, delimiters, and annotations)
  3. Declarative task-ordinal `occurrence` binding (never attempt-counting)
     with optional per-(action, target) authorization bounds (`max_occurrences`).
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any, Callable, Dict, Mapping, Optional, Set, Tuple


class AuthorizationViolationError(ValueError):
    """Raised when a planner emits an unauthorized action, malformed target,
    or an occurrence index exceeding the workflow's authorized policy bound."""


_ENTITY_ID_RE = re.compile(r"\b([a-zA-Z]+[-_]\d+(?:[-_][a-zA-Z0-9]+)*)\b")


def default_canonicalize_target(raw_target: str) -> str:
    """Normalize surface formatting drift while preserving distinct entity IDs.

    Examples:
      '  CUST_1042 '              -> 'cust-1042'
      'customer cust-1042 (VIP)'  -> 'cust-1042'
      'finding_r0_b1_rpl'         -> 'finding-r0-b1'
    """
    s = str(raw_target or "").strip()
    if not s:
        return ""
    # Strip synthetic replay suffix if present (E2b benchmark compatibility)
    if s.lower().endswith("_rpl") or s.lower().endswith("-rpl"):
        s = s[:-4]
    m = _ENTITY_ID_RE.search(s)
    token = m.group(1) if m else s
    token = re.sub(r"[\s_]+", "-", token.strip().lower())
    # Re-strip trailing -rpl if matched inside compound token
    if token.endswith("-rpl"):
        token = token[:-4]
    return token


@dataclasses.dataclass(frozen=True)
class ExtractedIdentity:
    action: str
    target: str
    occurrence: int
    is_diagnostic: bool = False

    @property
    def triple(self) -> Tuple[str, str, int]:
        return (self.action, self.target, self.occurrence)


class CanonicalIdentityExtractor:
    """Deterministic harness-side extractor mapping LLM JSON tool calls to
    `(action, target, occurrence)` triples without stateful attempt counters."""

    def __init__(
        self,
        effectful_actions: Set[str],
        diagnostic_actions: Optional[Set[str]] = None,
        target_normalizer: Callable[[str], str] = default_canonicalize_target,
        authorized_max_occurrence: Optional[Mapping[Tuple[str, str], int]] = None,
        default_max_occurrence: Optional[int] = None,
    ) -> None:
        self.effectful_actions = set(effectful_actions)
        self.diagnostic_actions = set(diagnostic_actions or set())
        self.target_normalizer = target_normalizer
        self.authorized_max_occurrence = (
            dict(authorized_max_occurrence) if authorized_max_occurrence is not None else None
        )
        self.default_max_occurrence = default_max_occurrence

    def extract(self, tool_call: Mapping[str, Any]) -> ExtractedIdentity:
        raw_action = str(tool_call.get("action", "")).strip()
        raw_target = str(tool_call.get("target", "")).strip()
        norm_target = self.target_normalizer(raw_target)

        if raw_action in self.diagnostic_actions:
            return ExtractedIdentity(
                action=raw_action,
                target=norm_target,
                occurrence=0,
                is_diagnostic=True,
            )

        if raw_action not in self.effectful_actions:
            raise AuthorizationViolationError(f"Unregistered effectful action: {raw_action!r}")

        if not norm_target:
            raise AuthorizationViolationError(f"Empty canonical target from {raw_target!r}")

        raw_occ = tool_call.get("occurrence", 0)
        if raw_occ is None or raw_occ == "":
            occ = 0
        else:
            try:
                occ = int(raw_occ)
            except (TypeError, ValueError) as exc:
                raise AuthorizationViolationError(
                    f"Invalid non-integer occurrence: {raw_occ!r}"
                ) from exc
        if occ < 0:
            raise AuthorizationViolationError(f"Negative occurrence index: {occ}")

        # Optional fail-closed policy guardrail against A4 occurrence hallucinations
        max_allowed: Optional[int] = None
        if self.authorized_max_occurrence is not None:
            max_allowed = self.authorized_max_occurrence.get(
                (raw_action, norm_target), self.default_max_occurrence
            )
        elif self.default_max_occurrence is not None:
            max_allowed = self.default_max_occurrence

        if max_allowed is not None and occ > max_allowed:
            raise AuthorizationViolationError(
                f"Unauthorized occurrence={occ} for ({raw_action}, {norm_target}); "
                f"max authorized ordinal is {max_allowed}"
            )

        return ExtractedIdentity(
            action=raw_action,
            target=norm_target,
            occurrence=occ,
            is_diagnostic=False,
        )
