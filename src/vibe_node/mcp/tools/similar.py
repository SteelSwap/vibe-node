"""find_similar tool — pure vector similarity search."""
from vibe_node.mcp.search_server import mcp


@mcp.tool()
async def find_similar(text: str | None = None, entity_type: str | None = None, entity_id: str | None = None, target_type: str | None = None, era: str | None = None, limit: int = 10, offset: int = 0) -> dict:
    """Find semantically similar entities in the knowledge base."""
    return {"status": "not_implemented"}
