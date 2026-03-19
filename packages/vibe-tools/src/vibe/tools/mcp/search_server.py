"""vibe-node Search MCP server.

Read-only access to the knowledge base via 6 tools:
search, find_similar, get_related, coverage, get_entity, compare_versions.

Run: uv run python -m vibe_node.mcp.search_server
"""
import logging

from vibe_node.mcp.app import mcp  # noqa: F401 — re-export for convenience

logger = logging.getLogger(__name__)

# Import tool modules so their @mcp.tool() decorators register
from vibe_node.mcp.tools import search, similar, related, coverage, entity, versions  # noqa: F401, E402

if __name__ == "__main__":
    mcp.run()
