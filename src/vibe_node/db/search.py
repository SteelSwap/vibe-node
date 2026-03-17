"""Composable search query builders.

Each function returns a (sql, params) tuple suitable for asyncpg execution.
None of these functions execute queries — they only construct them.

Query patterns:
- BM25: pg_search `|||` operator with `pdb.score()` for ranking
- Vector: pgvector `<=>` cosine distance on `embedding` column
- RRF: Reciprocal Rank Fusion combining BM25 and vector CTEs
"""

from __future__ import annotations


def _build_filter_clause(
    filters: dict[str, str],
    filter_columns: dict[str, str],
    params: list,
    table_alias: str = "",
) -> str:
    """Build a parameterized WHERE clause fragment for the given filters.

    Args:
        filters: Mapping of filter key -> value supplied by the caller.
        filter_columns: Mapping of filter key -> actual column name in table.
        params: Mutable list of bound parameter values; appended in place.
        table_alias: Optional table alias prefix (e.g. "t" → "t.era = $N").

    Returns:
        A SQL fragment starting with "AND ..." (empty string if no filters).
    """
    clauses: list[str] = []
    prefix = f"{table_alias}." if table_alias else ""
    for key, value in filters.items():
        col = filter_columns.get(key)
        if col is None:
            continue
        params.append(value)
        clauses.append(f"{prefix}{col} = ${len(params)}")
    if not clauses:
        return ""
    return " AND " + " AND ".join(clauses)


def build_bm25_query(
    table: str,
    text_column: str,
    query: str,
    filters: dict[str, str],
    filter_columns: dict[str, str],
    limit: int,
    offset: int,
) -> tuple[str, list]:
    """Build a BM25 keyword search query using the pg_search `|||` operator.

    Uses `pdb.score()` for ranking and includes `COUNT(*) OVER ()` for
    pagination metadata.

    Args:
        table: Table name to search.
        text_column: Column to match against using `|||`.
        query: Full-text search query string.
        filters: Runtime filter values (e.g. {"era": "shelley"}).
        filter_columns: Map from filter key to actual column name.
        limit: Maximum rows to return.
        offset: Row offset for pagination.

    Returns:
        (sql, params) tuple ready for asyncpg.
    """
    params: list = [query]
    filter_sql = _build_filter_clause(filters, filter_columns, params)

    params.append(limit)
    limit_param = len(params)
    params.append(offset)
    offset_param = len(params)

    sql = f"""
SELECT
    id,
    {text_column},
    pdb.score(id) AS bm25_score,
    COUNT(*) OVER () AS total_count
FROM {table}
WHERE {text_column} ||| $1
{filter_sql}
ORDER BY bm25_score DESC
LIMIT ${limit_param}
OFFSET ${offset_param}
""".strip()

    return sql, params


def build_vector_query(
    table: str,
    embedding: list[float],
    filters: dict[str, str],
    filter_columns: dict[str, str],
    limit: int,
    offset: int,
) -> tuple[str, list]:
    """Build a vector similarity search query using pgvector cosine distance.

    The embedding is formatted as a bracket-delimited string without spaces
    (e.g. '[0.1,0.2,...]') which pgvector requires.

    Args:
        table: Table name to search.
        embedding: Query embedding vector.
        filters: Runtime filter values.
        filter_columns: Map from filter key to actual column name.
        limit: Maximum rows to return.
        offset: Row offset for pagination.

    Returns:
        (sql, params) tuple ready for asyncpg.
    """
    # pgvector requires no spaces inside the vector literal
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    params: list = [vec_str]
    filter_sql = _build_filter_clause(filters, filter_columns, params)

    params.append(limit)
    limit_param = len(params)
    params.append(offset)
    offset_param = len(params)

    sql = f"""
SELECT
    id,
    embedding,
    embedding <=> $1::vector AS vector_distance,
    COUNT(*) OVER () AS total_count
FROM {table}
WHERE embedding IS NOT NULL
{filter_sql}
ORDER BY vector_distance ASC
LIMIT ${limit_param}
OFFSET ${offset_param}
""".strip()

    return sql, params


def build_rrf_query(
    table: str,
    text_column: str,
    query: str,
    embedding: list[float],
    filters: dict[str, str],
    filter_columns: dict[str, str],
    limit: int,
    offset: int,
    k: int = 60,
    bm25_weight: float = 0.5,
    vector_weight: float = 0.5,
    fetch_limit: int = 100,
) -> tuple[str, list]:
    """Build a Reciprocal Rank Fusion (RRF) query combining BM25 and vector.

    Architecture:
    - `bm25_ranked` CTE: BM25 matches ranked by pdb.score()
    - `vector_ranked` CTE: Vector matches ranked by cosine distance
    - `rrf_scores` CTE: UNION ALL of both rank lists with weighted RRF scores
    - Final SELECT: GROUP BY id to merge duplicate rows, sum RRF scores,
      ORDER BY fused score DESC

    RRF formula: weight / (k + rank)

    Args:
        table: Table name to search.
        text_column: Column for BM25 matching.
        query: Full-text search query string.
        embedding: Query embedding vector.
        filters: Runtime filter values.
        filter_columns: Map from filter key to actual column name.
        limit: Maximum rows to return in final result.
        offset: Row offset for pagination.
        k: RRF smoothing constant (default 60).
        bm25_weight: Weight applied to BM25 rank contribution (default 0.5).
        vector_weight: Weight applied to vector rank contribution (default 0.5).
        fetch_limit: Rows fetched from each CTE before fusion (default 100).

    Returns:
        (sql, params) tuple ready for asyncpg.
    """
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"

    # Params shared between both CTEs: query and vector
    params: list = [query, vec_str]

    # Build filter clause for BM25 CTE (no alias needed — single table query)
    bm25_filter_params: list = []
    bm25_filter_sql = _build_filter_clause(
        filters, filter_columns, bm25_filter_params
    )
    # Append bm25 filter values into main params, shifting $N accordingly
    bm25_param_offset = len(params)
    params.extend(bm25_filter_params)

    # Rebuild filter clause with correct param indices for BM25 CTE
    bm25_filter_clauses: list[str] = []
    idx = bm25_param_offset + 1
    for key, value in filters.items():
        col = filter_columns.get(key)
        if col is None:
            continue
        bm25_filter_clauses.append(f"{col} = ${idx}")
        idx += 1
    bm25_filter_fragment = (
        " AND " + " AND ".join(bm25_filter_clauses) if bm25_filter_clauses else ""
    )

    # Build filter clause for vector CTE
    vector_filter_params: list = []
    vector_filter_sql = _build_filter_clause(
        filters, filter_columns, vector_filter_params
    )
    vector_param_offset = len(params)
    params.extend(vector_filter_params)

    vector_filter_clauses: list[str] = []
    idx = vector_param_offset + 1
    for key, value in filters.items():
        col = filter_columns.get(key)
        if col is None:
            continue
        vector_filter_clauses.append(f"{col} = ${idx}")
        idx += 1
    vector_filter_fragment = (
        " AND " + " AND ".join(vector_filter_clauses) if vector_filter_clauses else ""
    )

    # Append scalar params: k, bm25_weight, vector_weight, fetch_limit x2, limit, offset
    params.append(k)
    k_param = len(params)
    params.append(bm25_weight)
    bm25_weight_param = len(params)
    params.append(vector_weight)
    vector_weight_param = len(params)
    params.append(fetch_limit)
    fetch_limit_bm25_param = len(params)
    params.append(fetch_limit)
    fetch_limit_vector_param = len(params)
    params.append(limit)
    limit_param = len(params)
    params.append(offset)
    offset_param = len(params)

    sql = f"""
WITH bm25_ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (ORDER BY pdb.score(id) DESC) AS rank
    FROM {table}
    WHERE {text_column} ||| $1
    {bm25_filter_fragment}
    LIMIT ${fetch_limit_bm25_param}
),
vector_ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (ORDER BY embedding <=> $2::vector ASC) AS rank
    FROM {table}
    WHERE embedding IS NOT NULL
    {vector_filter_fragment}
    LIMIT ${fetch_limit_vector_param}
),
rrf_scores AS (
    SELECT id, ${bm25_weight_param}::float / (${k_param}::float + rank) AS rrf_score
    FROM bm25_ranked
    UNION ALL
    SELECT id, ${vector_weight_param}::float / (${k_param}::float + rank) AS rrf_score
    FROM vector_ranked
)
SELECT
    id,
    SUM(rrf_score) AS rrf_total,
    COUNT(*) OVER () AS total_count
FROM rrf_scores
GROUP BY id
ORDER BY rrf_total DESC
LIMIT ${limit_param}
OFFSET ${offset_param}
""".strip()

    return sql, params


async def search_all(
    conn,
    query: str,
    embedding: list[float],
    entity_type: str | None = None,
    filters: dict | None = None,
    limit: int = 10,
    offset: int = 0,
    k: int = 60,
    bm25_weight: float = 0.5,
    vector_weight: float = 0.5,
) -> tuple[list[dict], int]:
    """Search across all tables (or a single entity type) using RRF.

    Returns (results, total_count). Each result includes 'entity_type' field.
    Skips tables that don't exist (Phase 1 tables).
    """
    from vibe_node.db.search_config import get_available_configs

    available = await get_available_configs(conn)

    if entity_type:
        if entity_type not in available:
            return [], 0
        configs = {entity_type: available[entity_type]}
    else:
        configs = available

    all_results = []

    for etype, cfg in configs.items():
        sql, params = build_rrf_query(
            table=cfg["table"],
            text_column=cfg["text_column"],
            query=query,
            embedding=embedding,
            filters=filters or {},
            filter_columns=cfg.get("filter_columns") or {},
            limit=limit,
            offset=0,  # fetch top N from each table, re-rank later
            k=k,
            bm25_weight=bm25_weight,
            vector_weight=vector_weight,
        )
        try:
            ranked_rows = await conn.fetch(sql, *params)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Search failed on %s: %s", cfg["table"], e)
            continue

        if not ranked_rows:
            continue

        # RRF query returns (id, rrf_total, total_count) only.
        # Fetch full rows for the ranked IDs to get title/preview columns.
        ranked_ids = [row["id"] for row in ranked_rows]
        score_map = {row["id"]: float(row["rrf_total"]) for row in ranked_rows}

        full_rows = await conn.fetch(
            f"SELECT * FROM {cfg['table']} WHERE id = ANY($1::uuid[])",
            ranked_ids,
        )

        for row in full_rows:
            r = dict(row)
            r["entity_type"] = etype
            r["rrf_total"] = score_map.get(row["id"], 0)
            title_col = cfg.get("title_column")
            r["_title"] = r.get(title_col, "") if title_col else ""
            preview_col = cfg["preview_column"]
            preview = r.get(preview_col, "")
            r["_preview"] = preview[:500] if preview else ""
            all_results.append(r)

    # Re-rank by RRF score across all tables
    all_results.sort(key=lambda r: r.get("rrf_score", 0) or r.get("rrf_total", 0), reverse=True)
    total = len(all_results)

    # Apply pagination
    paginated = all_results[offset:offset + limit]
    return paginated, total
