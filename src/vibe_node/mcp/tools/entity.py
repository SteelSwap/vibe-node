"""get_entity tool — fetch full entity details."""
from vibe_node.mcp.search_server import mcp


@mcp.tool()
async def get_entity(entity_type: str, entity_id: str | None = None, section_id: str | None = None, function_name: str | None = None, repo: str | None = None, include_relationships: bool = True, rel_limit: int = 20, rel_offset: int = 0) -> dict:
    """Fetch full details of a specific entity."""
    return {"status": "not_implemented"}
