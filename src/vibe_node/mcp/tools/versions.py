"""compare_versions tool — diff entities across versions."""
from vibe_node.mcp.search_server import mcp


@mcp.tool()
async def compare_versions(entity_type: str, version_a: str, version_b: str, function_name: str | None = None, repo: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    """Compare a function between release tags or see what changed between versions."""
    return {"status": "not_implemented"}
