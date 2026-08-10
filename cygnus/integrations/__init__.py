"""External and session-facing integration adapters for Cygnus.

Ownership:
- Nanobot/MCP-facing tool adapters and outward integration surfaces live here
- MCP auth/scope adapters live here
- OAuth session adapters live here
- external notification fan-out adapters live here
- this package is an adapter boundary, not the core governance domain itself
"""

from cygnus.integrations.governed_publish_tools import (
    GovernedPublishTools,
    publish_tool_bindings,
    publish_tool_definitions,
)
from cygnus.integrations.governed_draft_review_tools import (
    GovernedDraftReviewTools,
    draft_review_tool_bindings,
    draft_review_tool_definitions,
)
from cygnus.integrations.governed_session_tools import (
    governed_session_tool_definition,
    governed_session_tool_definitions,
)
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
    "GovernedDraftReviewTools",
    "GovernedPublishTools",
    "GovernedQueryRequest",
    "GovernedSessionBridge",
    "MCPAuthService",
    "OAuthService",
    "PriorGovernanceContext",
    "ResolvedIdentity",
    "apply_scope_filter",
    "build_governed_tool_registry",
    "draft_review_tool_bindings",
    "draft_review_tool_definitions",
    "governed_session_tool_definition",
    "governed_session_tool_definitions",
    "publish_tool_bindings",
    "publish_tool_definitions",
    "dispatch_external",
    "hash_token",
    "session_bridge_capabilities",
]
