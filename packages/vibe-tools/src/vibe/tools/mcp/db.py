"""asyncpg connection pool for the MCP server.

Re-exports the shared pool from vibe_node.db.pool so MCP tool modules
can import from vibe_node.mcp.db without knowing the shared location.
"""
from vibe_node.db.pool import get_pool, close_pool  # noqa: F401
