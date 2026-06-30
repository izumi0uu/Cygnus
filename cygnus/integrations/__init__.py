"""External and session-facing integration adapters for Cygnus.

Ownership:
- Nanobot/MCP-facing tool adapters and outward integration surfaces live here
- MCP auth/scope adapters live here
- external notification fan-out adapters live here
- this package is an adapter boundary, not the core governance domain itself
"""

from cygnus.integrations.mcp_auth import MCPAuthService, ResolvedIdentity, apply_scope_filter, hash_token
from cygnus.integrations.notification_dispatch import dispatch_external
from cygnus.integrations.nanobot_tools import (
    build_default_tool_registry,
    get_downstream_reality_check,
    get_governance_overview,
    get_recovery_window,
    get_source_trace,
    list_drift_alerts,
    propose_knowledge_object,
    publish_knowledge_object,
    read_knowledge_object,
    request_review,
    search_knowledge_objects,
    search_support_evidence,
    validate_publish_policy,
)

__all__ = [
    "MCPAuthService",
    "ResolvedIdentity",
    "apply_scope_filter",
    "build_default_tool_registry",
    "dispatch_external",
    "get_downstream_reality_check",
    "get_governance_overview",
    "get_recovery_window",
    "get_source_trace",
    "list_drift_alerts",
    "propose_knowledge_object",
    "publish_knowledge_object",
    "read_knowledge_object",
    "request_review",
    "search_knowledge_objects",
    "search_support_evidence",
    "validate_publish_policy",
    "hash_token",
]
