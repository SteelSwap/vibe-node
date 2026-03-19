"""get_related tool — navigate cross-references."""
from __future__ import annotations

from vibe.tools.mcp.app import mcp
from vibe.tools.mcp.db import get_pool

# Forward relationship → human-readable inverse label
INVERSE_MAP = {
    "implements": "implementedBy",
    "tests": "testedBy",
    "discusses": "discussedIn",
    "references": "referencedBy",
    "contradicts": "contradictedBy",
    "extends": "extendedBy",
    "derivedFrom": "derivationOf",
    "supersedes": "supersededBy",
    "requires": "requiredBy",
    "trackedBy": "tracks",
}
# Inverse label → canonical forward relationship (for filter normalisation)
INVERSE_REVERSE = {v: k for k, v in INVERSE_MAP.items()}


@mcp.tool()
async def get_related(
    entity_type: str,
    entity_id: str,
    relationship: str | None = None,
    target_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Navigate cross-references. Returns empty if cross_references doesn't exist yet."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'cross_references')"
        )
        if not exists:
            return {
                "source": {"entity_type": entity_type, "id": entity_id},
                "results": [],
                "total_count": 0,
                "offset": offset,
                "limit": limit,
                "note": "cross_references table not yet created (Phase 1)",
            }

        results = []

        # Outgoing edges: this entity is the source
        out_rows = await conn.fetch(
            "SELECT * FROM cross_references WHERE source_type = $1 AND source_id = $2 ORDER BY relationship",
            entity_type,
            entity_id,
        )
        for row in out_rows:
            results.append(
                {
                    "direction": "outgoing",
                    "relationship": row["relationship"],
                    "entity_type": row["target_type"],
                    "id": str(row["target_id"]),
                    "confidence": row["confidence"],
                    "notes": row["notes"],
                }
            )

        # Incoming edges: this entity is the target
        in_rows = await conn.fetch(
            "SELECT * FROM cross_references WHERE target_type = $1 AND target_id = $2 ORDER BY relationship",
            entity_type,
            entity_id,
        )
        for row in in_rows:
            inverse = INVERSE_MAP.get(row["relationship"], f"inv_{row['relationship']}")
            results.append(
                {
                    "direction": "incoming",
                    "relationship": inverse,
                    "entity_type": row["source_type"],
                    "id": str(row["source_id"]),
                    "confidence": row["confidence"],
                    "notes": row["notes"],
                }
            )

        # Optional filters
        if relationship:
            # Accept both the forward name and its inverse label
            canonical = INVERSE_REVERSE.get(relationship, relationship)
            results = [
                r for r in results if r["relationship"] in (relationship, canonical)
            ]
        if target_type:
            results = [r for r in results if r["entity_type"] == target_type]

        total = len(results)
        paginated = results[offset : offset + limit]

    return {
        "source": {"entity_type": entity_type, "id": entity_id},
        "results": paginated,
        "total_count": total,
        "offset": offset,
        "limit": limit,
    }
