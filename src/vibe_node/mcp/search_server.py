"""vibe-node Search MCP server.

Read-only access to the knowledge base via 6 tools:
search, find_similar, get_related, coverage, get_entity, compare_versions.

Run: uv run python -m vibe_node.mcp.search_server
"""
import logging

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("vibe-search")


def register_tools():
    """Import all tool modules so their @mcp.tool() decorators fire."""
    from vibe_node.mcp.tools import search, similar, related, coverage, entity, versions  # noqa: F401


register_tools()

if __name__ == "__main__":
    mcp.run()
