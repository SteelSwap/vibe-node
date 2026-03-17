"""find_similar tool — pure vector similarity search."""
from __future__ import annotations
import uuid as _uuid

from vibe_node.mcp.search_server import mcp
from vibe_node.mcp.db import get_pool
from vibe_node.mcp.embed import embed_query
from vibe_node.db.search import build_vector_query
from vibe_node.db.search_config import get_available_configs


@mcp.tool()
async def find_similar(
    text: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    target_type: str | None = None,
    era: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> dict:
    """Find semantically similar entities. Provide text OR entity_type+entity_id."""
    filters: dict[str, str] = {}
    if era:
        filters["era"] = era

    pool = await get_pool()
    async with pool.acquire() as conn:
        if text:
            embedding = await embed_query(text)
        elif entity_id and entity_type:
            entity_uuid = _uuid.UUID(entity_id)
            available = await get_available_configs(conn)
            cfg = available.get(entity_type)
            if not cfg:
                return {"error": f"Unknown entity type: {entity_type}"}
            row = await conn.fetchrow(
                f"SELECT embedding FROM {cfg['table']} WHERE id = $1", entity_uuid
            )
            if not row or not row["embedding"]:
                return {"error": "Entity not found or has no embedding"}
            embedding = list(row["embedding"])
        else:
            return {"error": "Provide either 'text' or 'entity_type' + 'entity_id'"}

        available = await get_available_configs(conn)
        if target_type and target_type in available:
            configs = {target_type: available[target_type]}
        else:
            configs = available

        all_results = []
        for etype, cfg in configs.items():
            sql, params = build_vector_query(
                table=cfg["table"],
                embedding=embedding,
                filters=filters if filters else {},
                filter_columns=cfg.get("filter_columns") or {},
                limit=limit,
                offset=0,
            )
            try:
                rows = await conn.fetch(sql, *params)
                for row in rows:
                    r = dict(row)
                    r["entity_type"] = etype
                    title_col = cfg.get("title_column")
                    r["_title"] = r.get(title_col, "") if title_col else ""
                    preview_col = cfg["preview_column"]
                    preview = r.get(preview_col, "")
                    r["_preview"] = preview[:500] if preview else ""
                    # build_vector_query returns 'vector_distance' (cosine distance);
                    # similarity = 1 - distance for cosine.
                    dist = r.get("vector_distance")
                    r["similarity"] = (1.0 - float(dist)) if dist is not None else 0.0
                    all_results.append(r)
            except Exception:
                continue

    all_results.sort(key=lambda r: r.get("similarity", 0), reverse=True)
    total = len(all_results)
    paginated = all_results[offset : offset + limit]

    return {
        "results": [
            {
                "entity_type": r["entity_type"],
                "id": str(r.get("id", "")),
                "title": r.get("_title", ""),
                "similarity": round(float(r.get("similarity", 0)), 4),
                "content_preview": r.get("_preview", ""),
            }
            for r in paginated
        ],
        "total_count": total,
        "offset": offset,
        "limit": limit,
    }
