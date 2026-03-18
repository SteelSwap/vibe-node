"""get_entity tool — fetch full entity details."""
from __future__ import annotations
import uuid as _uuid

from vibe_node.mcp.app import mcp
from vibe_node.mcp.db import get_pool
from vibe_node.db.search_config import get_available_configs


@mcp.tool()
async def get_entity(
    entity_type: str,
    entity_id: str | None = None,
    section_id: str | None = None,
    function_name: str | None = None,
    repo: str | None = None,
    include_relationships: bool = True,
    rel_limit: int = 20,
    rel_offset: int = 0,
) -> dict:
    """Fetch full details of a specific entity by ID or human-readable identifier."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        available = await get_available_configs(conn)
        cfg = available.get(entity_type)
        if not cfg:
            return {"error": f"Unknown or unavailable entity type: {entity_type}"}

        table = cfg["table"]
        row = None

        if entity_id:
            try:
                entity_uuid = _uuid.UUID(entity_id)
            except ValueError:
                return {"error": f"Invalid UUID: {entity_id}"}
            row = await conn.fetchrow(
                f"SELECT * FROM {table} WHERE id = $1", entity_uuid
            )
        elif section_id and table == "spec_sections":
            row = await conn.fetchrow(
                f"SELECT * FROM {table} WHERE section_id = $1", section_id
            )
        elif function_name and table == "code_chunks":
            q = f"SELECT * FROM {table} WHERE function_name = $1"
            p: list = [function_name]
            if repo:
                q += " AND repo = $2"
                p.append(repo)
            q += " ORDER BY release_tag DESC LIMIT 1"
            row = await conn.fetchrow(q, *p)

        if not row:
            return {"error": "Entity not found"}

        # Serialise: convert UUIDs/bytes to strings, drop the raw embedding
        entity: dict = {}
        for k, v in dict(row).items():
            if k == "embedding":
                continue  # too large and not useful in this response
            if isinstance(v, _uuid.UUID):
                entity[k] = str(v)
            elif isinstance(v, (bytes, bytearray, memoryview)):
                entity[k] = v.hex() if isinstance(v, (bytes, bytearray)) else bytes(v).hex()
            else:
                entity[k] = v

        output: dict = {"entity": entity}

        if include_relationships:
            xref_exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'cross_references')"
            )
            if xref_exists:
                rels = await conn.fetch(
                    """SELECT * FROM cross_references
                       WHERE (source_type = $1 AND source_id = $2)
                          OR (target_type = $1 AND target_id = $2)
                       LIMIT $3 OFFSET $4""",
                    entity_type,
                    row["id"],
                    rel_limit,
                    rel_offset,
                )
                output["relationships"] = {
                    "results": [dict(r) for r in rels],
                    "total_count": len(rels),
                    "offset": rel_offset,
                    "limit": rel_limit,
                }

    return output
