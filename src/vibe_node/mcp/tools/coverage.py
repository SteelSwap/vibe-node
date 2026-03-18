"""coverage tool — spec coverage dashboard."""
from __future__ import annotations

from vibe_node.mcp.app import mcp
from vibe_node.mcp.db import get_pool


@mcp.tool()
async def coverage(
    subsystem: str | None = None,
    era: str | None = None,
    show_uncovered: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Spec coverage dashboard. Returns empty if spec_sections doesn't exist yet."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE tablename IN ('spec_sections', 'cross_references', 'test_specifications')"
        )
        existing = {row["tablename"] for row in tables}

        if "spec_sections" not in existing:
            return {
                "summary": {"total_sections": 0},
                "note": "spec_sections table not yet created (Phase 1).",
            }

        conditions: list[str] = []
        qparams: list = []
        idx = 1

        if subsystem:
            conditions.append(f"ss.subsystem = ${idx}")
            qparams.append(subsystem)
            idx += 1
        if era:
            conditions.append(f"ss.era = ${idx}")
            qparams.append(era)
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        has_xref = "cross_references" in existing
        has_tests = "test_specifications" in existing

        impl_check = (
            "EXISTS (SELECT 1 FROM cross_references cr"
            " WHERE cr.source_type = 'spec_section'"
            " AND cr.source_id = ss.id"
            " AND cr.relationship = 'implements')"
            if has_xref
            else "FALSE"
        )
        test_check = (
            "EXISTS (SELECT 1 FROM test_specifications ts"
            " WHERE ts.spec_section_id = ss.id)"
            if has_tests
            else "FALSE"
        )

        summary = await conn.fetchrow(
            f"""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE {impl_check}) AS with_implementation,
                COUNT(*) FILTER (WHERE {test_check}) AS with_tests,
                COUNT(*) FILTER (WHERE NOT {impl_check} AND NOT {test_check}) AS uncovered
            FROM spec_sections ss {where}
            """,
            *qparams,
        )

        output: dict = {"summary": dict(summary)}

        if show_uncovered:
            uncovered_where = f"{where} AND" if conditions else "WHERE"
            uncovered = await conn.fetch(
                f"""
                SELECT ss.section_id, ss.title, ss.subsystem, ss.era, ss.section_type
                FROM spec_sections ss
                {uncovered_where} NOT {impl_check} AND NOT {test_check}
                ORDER BY ss.subsystem, ss.section_id
                LIMIT ${idx} OFFSET ${idx + 1}
                """,
                *qparams,
                limit,
                offset,
            )
            output["uncovered"] = [dict(r) for r in uncovered]
            output["total_uncovered"] = summary["uncovered"]

        output["offset"] = offset
        output["limit"] = limit

    return output
