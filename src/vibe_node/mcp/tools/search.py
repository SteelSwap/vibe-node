"""search tool — RRF fusion across all knowledge base tables."""
from __future__ import annotations

from vibe_node.mcp.app import mcp
from vibe_node.mcp.db import get_pool
from vibe_node.mcp.embed import embed_query
from vibe_node.db.search import search_all


@mcp.tool()
async def search(
    query: str,
    entity_type: str | None = None,
    era: str | None = None,
    repo: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict:
    """Search the Cardano knowledge base using BM25 + vector fusion (RRF).
    Returns ranked results from specs, code, issues, and PRs."""
    filters: dict[str, str] = {}
    if era:
        filters["era"] = era
    if repo:
        filters["repo"] = repo

    embedding = await embed_query(query)

    pool = await get_pool()
    async with pool.acquire() as conn:
        results, total = await search_all(
            conn,
            query,
            embedding,
            entity_type=entity_type,
            filters=filters if filters else None,
            limit=limit,
            offset=offset,
        )

    # build_rrf_query uses 'rrf_total' as the fused score column name;
    # search_all's sort key also checks 'rrf_score' as a fallback.
    return {
        "results": [
            {
                "entity_type": r.get("entity_type", "unknown"),
                "id": str(r.get("id", "")),
                "title": r.get("_title", ""),
                "score": round(float(r.get("rrf_total") or r.get("rrf_score") or 0), 4),
                "content_preview": r.get("_preview", ""),
            }
            for r in results
        ],
        "total_count": total,
        "offset": offset,
        "limit": limit,
    }
