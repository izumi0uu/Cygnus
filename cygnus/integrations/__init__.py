"""External and session-facing integration adapters for Cygnus.

Ownership:
- Nanobot/MCP-facing tool adapters and outward integration surfaces live here
- MCP auth/scope adapters live here
- OAuth session adapters live here
- external notification fan-out adapters live here
- this package is an adapter boundary, not the core governance domain itself
"""

from cygnus.integrations.mcp_auth import (
    MCPAuthService,
    ResolvedIdentity,
    apply_scope_filter,
    hash_token,
)
from cygnus.integrations.nanobot_tools import (
    GovernedKnowledgeTools,
    build_governed_tool_registry,
)
from cygnus.integrations.notification_dispatch import dispatch_external
from cygnus.integrations.oauth_service import OAuthService
from cygnus.integrations.session_bridge import (
    ContinuityDisposition,
    GovernanceDisposition,
    GovernedQueryRequest,
    GovernedSessionBridge,
    PriorGovernanceContext,
    session_bridge_capabilities,
)

__all__ = [
    "ContinuityDisposition",
    "GovernanceDisposition",
    "GovernedKnowledgeTools",
    "GovernedQueryRequest",
    "GovernedSessionBridge",
    "MCPAuthService",
    "OAuthService",
    "PriorGovernanceContext",
    "ResolvedIdentity",
    "apply_scope_filter",
    "build_governed_tool_registry",
    "dispatch_external",
    "hash_token",
    "session_bridge_capabilities",
]
