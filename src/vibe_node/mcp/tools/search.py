"""search tool — RRF fusion across all knowledge base tables."""
from vibe_node.mcp.search_server import mcp


@mcp.tool()
async def search(query: str, entity_type: str | None = None, era: str | None = None, repo: str | None = None, limit: int = 10, offset: int = 0) -> dict:
    """Search the Cardano knowledge base using BM25 + vector fusion (RRF)."""
    return {"status": "not_implemented"}
