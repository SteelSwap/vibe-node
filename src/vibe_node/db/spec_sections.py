"""CRUD operations for spec_sections table."""
import uuid
from typing import Optional


async def add_spec_section(
    conn,
    section_id: str,
    title: str,
    section_type: str,
    era: str,
    subsystem: str,
    verbatim: str,
    extracted_rule: str,
    spec_chunk_id: Optional[uuid.UUID] = None,
    embedding: Optional[list[float]] = None,
    metadata: Optional[dict] = None,
) -> uuid.UUID:
    """Insert a spec section and return its ID."""
    row_id = uuid.uuid4()
    embedding_str = (
        "[" + ",".join(str(x) for x in embedding) + "]" if embedding else None
    )
    result = await conn.fetchrow(
        """
        INSERT INTO spec_sections (id, spec_chunk_id, section_id, title, section_type,
            era, subsystem, verbatim, extracted_rule, embedding, metadata)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::vector, $11::jsonb)
        ON CONFLICT (section_id) DO UPDATE SET
            title = EXCLUDED.title,
            extracted_rule = EXCLUDED.extracted_rule,
            embedding = EXCLUDED.embedding,
            metadata = EXCLUDED.metadata
        RETURNING id
        """,
        row_id, spec_chunk_id, section_id, title, section_type,
        era, subsystem, verbatim, extracted_rule, embedding_str,
        metadata,
    )
    return result["id"]


async def list_spec_sections(
    conn,
    subsystem: Optional[str] = None,
    era: Optional[str] = None,
    section_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """List spec sections with optional filters. Returns (results, total_count)."""
    conditions = []
    params = []
    idx = 1
    if subsystem:
        conditions.append(f"subsystem = ${idx}")
        params.append(subsystem)
        idx += 1
    if era:
        conditions.append(f"era = ${idx}")
        params.append(era)
        idx += 1
    if section_type:
        conditions.append(f"section_type = ${idx}")
        params.append(section_type)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count = await conn.fetchval(
        f"SELECT COUNT(*) FROM spec_sections {where}", *params
    )

    params.extend([limit, offset])
    rows = await conn.fetch(
        f"""SELECT id, section_id, title, section_type, era, subsystem
        FROM spec_sections {where}
        ORDER BY subsystem, section_id
        LIMIT ${idx} OFFSET ${idx + 1}""",
        *params,
    )
    return [dict(r) for r in rows], count
