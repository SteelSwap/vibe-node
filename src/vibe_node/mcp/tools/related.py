"""get_related tool — navigate cross-references."""
from vibe_node.mcp.search_server import mcp


@mcp.tool()
async def get_related(entity_type: str, entity_id: str, relationship: str | None = None, target_type: str | None = None, limit: int = 20, offset: int = 0) -> dict:
    """Navigate cross-references to find linked entities."""
    return {"status": "not_implemented"}
