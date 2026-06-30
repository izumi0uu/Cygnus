"""
Policy Engine — dormant legacy compatibility wrapper.

The old PolicyEngine (based on ScopeMembership/ScopeRole/Action enums) has been
replaced by the new dual-realm permission engine in permission_engine.py.

Current boundary:
- this module is preserved only for source-parity baseline and dormant legacy references
- it is not part of the current mounted Cygnus API assembly
- new code should use cygnus.runtime.services.permission_engine directly
- any attempt to revive workspace/scope compatibility here should happen in a dedicated repair-or-removal lane
"""

import uuid
from dataclasses import dataclass

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from cygnus.runtime.database.models import AuditLog, Employee


@dataclass
class PolicyDecision:
    """Result of a policy evaluation."""
    allowed: bool
    reason: str


class PolicyEngine:
    """
    Legacy wrapper — delegates to permission_engine for actual checks.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def check_document_access(
        self,
        user: Employee,
        source,
        action: str = "read",
    ) -> PolicyDecision:
        """Check document access using the new permission engine."""
        from cygnus.runtime.services.permission_engine import can_access_document
        allowed = await can_access_document(self.db, user, source, action)
        return PolicyDecision(
            allowed=allowed,
            reason="Allowed" if allowed else "Access denied",
        )

    async def check_workspace_access(
        self,
        user: Employee,
        workspace_id: uuid.UUID,
    ) -> PolicyDecision:
        """Check workspace access using the new permission engine."""
        from cygnus.runtime.services.permission_engine import can_access_workspace
        allowed = await can_access_workspace(self.db, user, workspace_id)
        return PolicyDecision(
            allowed=allowed,
            reason="Allowed" if allowed else "Not a workspace member",
        )

    async def _audit(
        self,
        principal_id: uuid.UUID,
        action: str,
        resource_type: str,
        resource_id: str,
        decision: PolicyDecision,
    ) -> None:
        """Write an audit log entry (append-only)."""
        if not resource_type:
            return

        try:
            entry = AuditLog(
                principal_id=principal_id,
                principal_type="human",
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                decision="allow" if decision.allowed else "deny",
                reason=decision.reason,
            )
            self.db.add(entry)
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")
