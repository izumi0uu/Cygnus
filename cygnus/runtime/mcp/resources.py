"""
Cygnus MCP Resources — static/semi-static data exposed to Claude.

Resources provide context Claude can read at session start without calling a tool.
"""

from fastmcp import FastMCP


def register_resources(mcp: FastMCP):
    """Register static, non-data MCP resources for the governed profile."""

    @mcp.resource("cygnus://about")
    async def about_cygnus() -> str:
        """Describe the bounded Cygnus session surface without exposing data."""
        return (
            "# Cygnus Governed Support Knowledge\n\n"
            "Cygnus is the support knowledge control plane. Nanobot or another "
            "client may own a session, but Cygnus owns audience, evidence, "
            "approval, publication, and traceability truth.\n\n"
            "Only the twelve typed governed tools are available through this "
            "server. Every knowledge or evidence read requires an explicit "
            "audience context and is rechecked against current Cygnus truth. "
            "Raw sources, generic wiki browsing, direct edits, and legacy "
            "approval actions are not MCP resources or tools.\n\n"
            "When no governed result is usable, report the restriction or "
            "escalate; never use session memory as knowledge truth."
        )
