"""CRUD operations for cross_references table."""
import uuid
from typing import Optional

# Maps canonical relationship names to their inverses (computed at query time)
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
INVERSE_REVERSE = {v: k for k, v in INVERSE_MAP.items()}

# Maps source_type values to table names
TYPE_TABLE_MAP = {
    "spec_section": "spec_sections",
    "code_chunk": "code_chunks",
    "github_issue": "github_issues",
    "github_pr": "github_pull_requests",
    "gap_analysis": "gap_analysis",
    "test_specification": "test_specifications",
}


async def add_xref(
    conn,
    source_type: str,
    source_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    relationship: str,
    confidence: float = 1.0,
    notes: Optional[str] = None,
    created_by: str = "manual",
) -> uuid.UUID:
    """Insert a cross-reference and return its ID."""
    row_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO cross_references (id, source_type, source_id, target_type, target_id,
            relationship, confidence, notes, created_by)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT (source_type, source_id, target_type, target_id, relationship)
        DO UPDATE SET confidence = EXCLUDED.confidence, notes = EXCLUDED.notes
        """,
        row_id, source_type, source_id, target_type, target_id,
        relationship, confidence, notes, created_by,
    )
    return row_id


async def query_xrefs(
    conn,
    entity_type: str,
    entity_id: uuid.UUID,
    relationship: Optional[str] = None,
    target_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Find all cross-references involving an entity (as source or target).

    Returns results with direction and appropriate relationship name
    (canonical for outgoing, inverse for incoming).
    """
    results = []

    # Outgoing (this entity is source)
    out_rows = await conn.fetch(
        "SELECT * FROM cross_references WHERE source_type = $1 AND source_id = $2 ORDER BY relationship",
        entity_type, entity_id,
    )
    for row in out_rows:
        results.append({
            "direction": "outgoing",
            "relationship": row["relationship"],
            "entity_type": row["target_type"],
            "id": str(row["target_id"]),
            "confidence": row["confidence"],
            "notes": row["notes"],
            "created_by": row["created_by"],
        })

    # Incoming (this entity is target) — show inverse relationship name
    in_rows = await conn.fetch(
        "SELECT * FROM cross_references WHERE target_type = $1 AND target_id = $2 ORDER BY relationship",
        entity_type, entity_id,
    )
    for row in in_rows:
        inverse = INVERSE_MAP.get(row["relationship"], f"inv_{row['relationship']}")
        results.append({
            "direction": "incoming",
            "relationship": inverse,
            "entity_type": row["source_type"],
            "id": str(row["source_id"]),
            "confidence": row["confidence"],
            "notes": row["notes"],
            "created_by": row["created_by"],
        })

    # Apply filters
    if relationship:
        canonical = INVERSE_REVERSE.get(relationship, relationship)
        results = [r for r in results if r["relationship"] in (relationship, canonical)]
    if target_type:
        results = [r for r in results if r["entity_type"] == target_type]

    total = len(results)
    return results[offset:offset + limit]


async def coverage_report(conn, subsystem: Optional[str] = None, era: Optional[str] = None) -> dict:
    """Generate spec coverage report.

    Returns counts of spec sections with/without implementations, tests, and gaps.
    """
    conditions = []
    params = []
    idx = 1
    if subsystem:
        conditions.append(f"ss.subsystem = ${idx}")
        params.append(subsystem)
        idx += 1
    if era:
        conditions.append(f"ss.era = ${idx}")
        params.append(era)
        idx += 1
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    result = await conn.fetchrow(f"""
        WITH section_coverage AS (
            SELECT
                ss.id,
                EXISTS (
                    SELECT 1 FROM cross_references cr
                    WHERE cr.source_type = 'spec_section' AND cr.source_id = ss.id
                    AND cr.relationship = 'implements'
                ) AS has_implementation,
                EXISTS (
                    SELECT 1 FROM cross_references cr
                    WHERE cr.source_type = 'spec_section' AND cr.source_id = ss.id
                    AND cr.relationship = 'tests'
                ) AS has_test,
                EXISTS (
                    SELECT 1 FROM gap_analysis ga
                    WHERE ga.spec_section_id = ss.id
                ) AS has_gap
            FROM spec_sections ss {where}
        )
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE has_implementation) AS with_implementation,
            COUNT(*) FILTER (WHERE has_test) AS with_tests,
            COUNT(*) FILTER (WHERE has_gap) AS with_gaps,
            COUNT(*) FILTER (WHERE NOT has_implementation AND NOT has_test) AS uncovered
        FROM section_coverage
    """, *params)
    return dict(result)


async def uncovered_sections(
    conn,
    subsystem: Optional[str] = None,
    era: Optional[str] = None,
    no_tests: bool = False,
    no_implementation: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List spec sections missing tests, implementations, or both."""
    conditions = []
    params = []
    idx = 1

    if subsystem:
        conditions.append(f"ss.subsystem = ${idx}")
        params.append(subsystem)
        idx += 1
    if era:
        conditions.append(f"ss.era = ${idx}")
        params.append(era)
        idx += 1
    if no_tests:
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM cross_references cr "
            "WHERE cr.source_type = 'spec_section' AND cr.source_id = ss.id "
            "AND cr.relationship = 'tests')"
        )
    if no_implementation:
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM cross_references cr "
            "WHERE cr.source_type = 'spec_section' AND cr.source_id = ss.id "
            "AND cr.relationship = 'implements')"
        )

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.extend([limit, offset])

    rows = await conn.fetch(
        f"""SELECT ss.section_id, ss.title, ss.subsystem, ss.era, ss.section_type
        FROM spec_sections ss {where}
        ORDER BY ss.subsystem, ss.section_id
        LIMIT ${idx} OFFSET ${idx + 1}""",
        *params,
    )
    return [dict(r) for r in rows]
