"""Runtime audit-log writer for Cygnus shell mutations.

Ownership:
- audit-log persistence for runtime-side mutations and policy decisions lives here
- this module records runtime actions; it does not own higher-level governance workflow semantics
- correlation/trace context is attached from the bounded observability surface
  (``cygnus.observability``) so audit rows join end-to-end request traces
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database.models import AuditLog, Employee


async def log_audit(
    db: AsyncSession,
    user: Employee,
    action: str,
    resource_type: str,
    resource_id: str,
    decision: str = "ALLOW",
    reason: Optional[str] = None,
    correlation_id: Optional[str] = None,
):
    """
    Log an action to the audit log.
    This should be called during sensitive mutations (Create/Update/Delete).
    Does NOT commit the session — the caller must commit.

    ``correlation_id`` is optional: when omitted, the active observability
    correlation context is used (request → MCP → job propagation). The value
    is sanitized by the observability layer before it reaches the column.
    """
    import uuid as _uuid

    from cygnus.observability import current_request_id, current_traceparent

    effective_correlation = correlation_id or current_request_id()
    correlation_uuid = None
    if effective_correlation:
        try:
            correlation_uuid = _uuid.UUID(effective_correlation)
        except (ValueError, TypeError, AttributeError):
            correlation_uuid = None

    entry = AuditLog(
        principal_id=user.id,
        principal_type="human",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        decision=decision,
        reason=reason,
        correlation_id=correlation_uuid,
        traceparent=current_traceparent() if correlation_uuid else None,
    )
    db.add(entry)
