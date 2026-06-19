"""
Arkon MCP Server — exposes Knowledge Base tools to Claude.

This module creates a FastMCP server that can be mounted into the
main FastAPI app. Claude Desktop connects to /mcp and receives
tools to search knowledge, retrieve documents, list categories, etc.

Architecture:
    Claude Desktop → MCP (HTTPS) → /mcp endpoint → Arkon KB tools
                                                   → PostgreSQL (pgvector)
                                                   → Neo4j (graph)
                                                   → MinIO (files)

Connection:
    Employee runs: arkon connect --server https://ai.company.internal --token <token>
    This adds to Claude Desktop config:
    {
        "mcpServers": {
            "arkon": {
                "url": "https://ai.company.internal/mcp",
                "headers": {"Authorization": "Bearer <token>"}
            }
        }
    }
"""

from fastmcp import FastMCP

from app.mcp.middleware import ScopedToolsMiddleware
from app.mcp.resources import register_resources
from app.mcp.tools import register_tools


def create_mcp_server() -> FastMCP:
    """
    Create and configure the Arkon MCP server.
    Call this once during app startup.
    """
    mcp = FastMCP(
        "Arkon",
        instructions=(
            "You are connected to Arkon — the company's internal knowledge base. "
            "\n\n"
            "## MANDATORY: Always search Arkon before answering\n"
            "For ANY question that could relate to company information — processes, "
            "products, people, departments, policies, projects, or technical docs — "
            "you MUST query Arkon first. Do NOT answer from general knowledge alone "
            "when company-specific information may exist.\n"
            "\n"
            "## Tool usage order\n"
            "1. `search_wiki` — first stop for most questions (wiki synthesizes sources)\n"
            "2. `read_wiki_page` — read a specific page by slug from search results\n"
            "3. `read_wiki_index` — browse all available wiki pages\n"
            "4. `get_source_outline` / `get_source_pages` — only for exact citations "
            "or details the wiki has paraphrased\n"
            "\n"
            "## Citation\n"
            "Always cite wiki slugs or source IDs in your answers so users can verify."
        ),
    )

    # Register all tools and resources
    register_tools(mcp)
    register_resources(mcp)

    # Filter `tools/list` per bearer-token identity. Must run after tools are
    # registered so the middleware can read `__arkon_requires__` off each fn.
    mcp.add_middleware(ScopedToolsMiddleware())

    return mcp
