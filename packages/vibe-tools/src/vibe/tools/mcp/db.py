"""asyncpg connection pool for the MCP server.

Re-exports the shared pool from vibe.tools.db.pool so MCP tool modules
can import from vibe.tools.mcp.db without knowing the shared location.
"""

from vibe.tools.db.pool import close_pool, get_pool  # noqa: F401
