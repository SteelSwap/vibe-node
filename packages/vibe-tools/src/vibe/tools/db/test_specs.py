"""CRUD operations for test_specifications table."""

import uuid


async def add_test_spec(
    conn,
    subsystem: str,
    test_type: str,
    test_name: str,
    description: str,
    priority: str,
    phase: str,
    spec_section_id: uuid.UUID | None = None,
    hypothesis_strategy: str | None = None,
    metadata: dict | None = None,
) -> uuid.UUID:
    """Insert a test specification and return its ID."""
    row_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO test_specifications (id, spec_section_id, subsystem, test_type,
            test_name, description, hypothesis_strategy, priority, phase, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
        ON CONFLICT (spec_section_id, test_name) DO UPDATE SET
            description = EXCLUDED.description,
            hypothesis_strategy = EXCLUDED.hypothesis_strategy,
            priority = EXCLUDED.priority
        """,
        row_id,
        spec_section_id,
        subsystem,
        test_type,
        test_name,
        description,
        hypothesis_strategy,
        priority,
        phase,
        metadata,
    )
    return row_id


async def list_test_specs(
    conn,
    subsystem: str | None = None,
    phase: str | None = None,
    test_type: str | None = None,
    priority: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """List test specifications with optional filters. Returns (results, total_count)."""
    conditions = []
    params = []
    idx = 1

    for col, val in [
        ("subsystem", subsystem),
        ("phase", phase),
        ("test_type", test_type),
        ("priority", priority),
    ]:
        if val:
            conditions.append(f"{col} = ${idx}")
            params.append(val)
            idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count = await conn.fetchval(f"SELECT COUNT(*) FROM test_specifications {where}", *params)

    params.extend([limit, offset])
    rows = await conn.fetch(
        f"""SELECT id, test_name, subsystem, test_type, priority, phase
        FROM test_specifications {where}
        ORDER BY
            CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                          WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END,
            subsystem, test_name
        LIMIT ${idx} OFFSET ${idx + 1}""",
        *params,
    )
    return [dict(r) for r in rows], count
