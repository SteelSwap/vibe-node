"""Tests for search templates and configuration."""


def test_search_config_has_all_entity_types():
    from vibe.tools.db.search_config import SEARCH_CONFIG

    required = {"spec_doc", "code", "issue", "issue_comment", "pr", "pr_comment"}
    assert required.issubset(set(SEARCH_CONFIG.keys()))


def test_search_config_entries_have_required_fields():
    from vibe.tools.db.search_config import SEARCH_CONFIG

    for name, cfg in SEARCH_CONFIG.items():
        assert "table" in cfg, f"{name} missing 'table'"
        assert "text_column" in cfg, f"{name} missing 'text_column'"
        assert "preview_column" in cfg, f"{name} missing 'preview_column'"
        assert "filter_columns" in cfg, f"{name} missing 'filter_columns'"


def test_search_config_table_exists_check():
    from vibe.tools.db.search_config import get_available_configs

    assert callable(get_available_configs)


def test_build_bm25_query():
    from vibe.tools.db.search import build_bm25_query

    sql, params = build_bm25_query(
        table="spec_documents",
        text_column="content_plain",
        query="UTxO validation",
        filters={"era": "shelley"},
        filter_columns={"era": "era"},
        limit=10,
        offset=0,
    )
    assert "content_plain" in sql
    assert "pdb.score" in sql
    assert any("UTxO" in str(v) for v in params)
    assert "shelley" in params


def test_build_vector_query():
    from vibe.tools.db.search import build_vector_query

    fake_embedding = [0.1] * 1536
    sql, params = build_vector_query(
        table="spec_documents",
        embedding=fake_embedding,
        filters={"era": "shelley"},
        filter_columns={"era": "era"},
        limit=10,
        offset=0,
    )
    assert "embedding" in sql
    assert "<=>" in sql


def test_build_rrf_query():
    from vibe.tools.db.search import build_rrf_query

    fake_embedding = [0.1] * 1536
    sql, params = build_rrf_query(
        table="spec_documents",
        text_column="content_plain",
        query="UTxO validation",
        embedding=fake_embedding,
        filters={"era": "shelley"},
        filter_columns={"era": "era"},
        limit=10,
        offset=0,
    )
    assert "bm25" in sql.lower()
    assert "vector" in sql.lower()
    assert "rrf" in sql.lower()
    assert "UNION ALL" in sql
