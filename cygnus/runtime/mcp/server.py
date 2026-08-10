"""
Cygnus MCP Server — exposes support knowledge tools to Claude.

This module creates a FastMCP server that can be mounted into the
main FastAPI app. Claude Desktop connects to /mcp and receives
tools to search knowledge, retrieve documents, list categories, etc.

Architecture:
    Claude Desktop → MCP (HTTPS) → /mcp endpoint → Cygnus support tools
                                                   → PostgreSQL (pgvector)
                                                   → Neo4j (graph)
                                                   → MinIO (files)

Connection:
    Employee runs: cygnus connect --server https://ai.company.internal --token <token>
    This adds to Claude Desktop config:
    {
        "mcpServers": {
            "cygnus": {
                "url": "https://ai.company.internal/mcp",
                "headers": {"Authorization": "Bearer <token>"}
            }
        }
    }
"""

from fastmcp import FastMCP

from cygnus.runtime.mcp.middleware import ScopedToolsMiddleware
from cygnus.runtime.mcp.resources import register_resources
from cygnus.runtime.mcp.tools import register_tools


def create_mcp_server() -> FastMCP:
    """
    Create and configure the Cygnus MCP server.
    Call this once during app startup.
    """
    mcp = FastMCP(
        "Cygnus",
        instructions=(
            "You are connected to Cygnus, the governed support knowledge control plane. "
            "Nanobot or another client may own the session, but Cygnus owns knowledge, "
            "audience, traceability, approval, and publication truth.\n\n"
            "## Support query boundary\n"
            "For every support question, call `search_knowledge_objects` with the current "
            "audience context before composing an answer. Never treat chat history or model "
            "memory as support knowledge truth.\n\n"
            "## Governed tool order\n"
            "1. `search_knowledge_objects` — audience-filtered object retrieval.\n"
            "2. `read_knowledge_object` — read the selected typed object.\n"
            "3. `get_source_trace` — inspect freshness and blind spots before direct use.\n"
            "4. `search_support_evidence` — investigate evidence gaps without promoting raw "
            "evidence to answer truth.\n"
            "5. `list_drift_alerts` — read current release and incident drift with explicit coverage.\n"
            "6. `propose_knowledge_object` — create a durable staged draft; it is not "
            "reviewed or published truth.\n"
            "7. `update_draft_object` — make a version-checked draft revision.\n"
            "8. `request_review` — submit the current draft version through Cygnus review.\n"
            "9. `read_review_feedback` — read scoped review and approval feedback.\n"
            "10. `record_feedback_signal` — durably record consumption feedback; it does not "
            "queue review or refresh work.\n"
            "11. `validate_publish_policy` — re-check approval, source readiness, audience bindings, "
            "and object version before a durable command.\n"
            "12. `publish_knowledge_object` — administrator-only durable publication; a successful "
            "command stages propagation as `pending`, never as downstream `synced`.\n"
            "Generic wiki and source tools remain available for substrate exploration, but "
            "must not bypass the governed object path for support answers. If governed "
            "retrieval finds no usable object or reports a restriction, say so and fall back "
            "or escalate instead of fabricating an answer."
        ),
    )

    # Register all tools and resources
    register_tools(mcp)
    register_resources(mcp)

    # Filter `tools/list` per bearer-token identity. Must run after tools are
    # registered so the middleware can read `__cygnus_requires__` off each fn.
    mcp.add_middleware(ScopedToolsMiddleware())

    return mcp
