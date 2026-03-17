"""coverage tool — spec coverage dashboard."""
from vibe_node.mcp.search_server import mcp


@mcp.tool()
async def coverage(subsystem: str | None = None, era: str | None = None, show_uncovered: bool = True, limit: int = 50, offset: int = 0) -> dict:
    """Spec coverage dashboard showing which rules have implementations and tests."""
    return {"status": "not_implemented"}
