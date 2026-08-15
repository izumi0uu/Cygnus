"""Actor-bound replay receipts for governed session draft writes (CYG-140).

``propose_knowledge_object`` and ``update_draft_object`` accept an explicit
actor-bound ``command_id``. A successful durable write persists one receipt
row keyed by ``(actor_id, tool_name, command_id)`` in the same caller-owned
transaction as the draft/ledger/audit truth; the persistence owner only
flushes and never commits.

- Exact replay (same actor, tool, command id, and normalized request
  fingerprint) returns the stored result unchanged — one durable identity,
  no second draft/event/audit.
- Reusing the command id with different normalized input or a different actor
  raises :class:`ToolCommandReceiptConflict` without writes.
- A failed or rolled-back write never persists a receipt, so response loss can
  never create a second durable identity.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.governance.ledger import lock_governance_command
from cygnus.observability import current_request_id, current_traceparent
from cygnus.runtime.database.models import GovernanceToolCommandReceipt


class ToolCommandReceiptConflict(ValueError):
    """A command id was reused for different actor-bound input."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolCommandReceiptWrite:
    """One durable receipt plus whether this call replayed it."""

    receipt: GovernanceToolCommandReceipt
    replayed: bool

    @property
    def receipt_ref(self) -> str:
        return tool_command_receipt_ref(self.receipt)

    def to_dict(self) -> dict[str, object]:
        return {
            "receipt_ref": self.receipt_ref,
            "tool_name": self.receipt.tool_name,
            "command_id": self.receipt.command_id,
            "correlation_id": (
                str(self.receipt.correlation_id)
                if self.receipt.correlation_id is not None
                else None
            ),
            "traceparent": self.receipt.traceparent,
            "replayed": self.replayed,
        }


def tool_command_receipt_ref(receipt: GovernanceToolCommandReceipt) -> str:
    """Return the durable entity reference for one tool command receipt."""
    return f"tool-command-receipt:{receipt.id}"


def tool_command_request_fingerprint(
    *,
    actor_id: uuid.UUID,
    tool_name: str,
    command_id: str,
    normalized_arguments: Mapping[str, Any],
) -> str:
    """64-character sha256 over the normalized actor-bound command input."""
    canonical = json.dumps(
        {
            "actor_id": str(actor_id),
            "tool_name": tool_name,
            "command_id": command_id,
            "arguments": dict(normalized_arguments),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


async def replay_tool_command_receipt(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    tool_name: str,
    command_id: str,
    request_fingerprint: str,
) -> ToolCommandReceiptWrite | None:
    """Return the exact durable replay, or ``None`` when no receipt exists.

    Reusing the command id with different normalized actor-bound input raises
    :class:`ToolCommandReceiptConflict`; no writes happen on this path.
    """
    await lock_governance_command(session, f"tool-receipt:{tool_name}:{command_id}")
    existing = (
        await session.execute(
            select(GovernanceToolCommandReceipt).where(
                GovernanceToolCommandReceipt.actor_id == actor_id,
                GovernanceToolCommandReceipt.tool_name == tool_name,
                GovernanceToolCommandReceipt.command_id == command_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        return None
    if existing.request_fingerprint != request_fingerprint:
        raise ToolCommandReceiptConflict(
            f"command_id={command_id} is already bound to different actor-bound input"
        )
    return ToolCommandReceiptWrite(receipt=existing, replayed=True)


async def create_tool_command_receipt(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID,
    tool_name: str,
    command_id: str,
    request_fingerprint: str,
    result_payload: Mapping[str, Any],
    correlation_id: str | None = None,
    traceparent: str | None = None,
) -> ToolCommandReceiptWrite:
    """Persist one fresh receipt with request correlation metadata."""
    effective_correlation = correlation_id or current_request_id()
    correlation_uuid = None
    if effective_correlation:
        try:
            correlation_uuid = uuid.UUID(str(effective_correlation))
        except (TypeError, ValueError):
            correlation_uuid = None
    receipt = GovernanceToolCommandReceipt(
        id=uuid.uuid4(),
        actor_id=actor_id,
        tool_name=tool_name,
        command_id=command_id,
        request_fingerprint=request_fingerprint,
        correlation_id=correlation_uuid,
        traceparent=traceparent or current_traceparent(),
        result_payload=dict(result_payload),
    )
    session.add(receipt)
    await session.flush()
    return ToolCommandReceiptWrite(receipt=receipt, replayed=False)


__all__ = [
    "ToolCommandReceiptConflict",
    "ToolCommandReceiptWrite",
    "create_tool_command_receipt",
    "replay_tool_command_receipt",
    "tool_command_receipt_ref",
    "tool_command_request_fingerprint",
]
