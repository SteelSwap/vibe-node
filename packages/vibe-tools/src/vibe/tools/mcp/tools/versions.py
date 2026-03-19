"""compare_versions tool — diff entities across versions."""
from __future__ import annotations

from vibe.tools.mcp.app import mcp
from vibe.tools.mcp.db import get_pool


@mcp.tool()
async def compare_versions(
    entity_type: str,
    version_a: str,
    version_b: str,
    function_name: str | None = None,
    repo: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Compare a function between release tags or see what changed between versions."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if function_name:
            # Single function comparison
            cond = "function_name = $1"
            p_base: list = [function_name]
            if repo:
                cond += " AND repo = $2"
                p_base.append(repo)
            tag_idx = len(p_base) + 1

            row_a = await conn.fetchrow(
                f"SELECT content, signature, module_name, file_path, content_hash"
                f" FROM code_chunks WHERE {cond} AND release_tag = ${tag_idx}",
                *p_base,
                version_a,
            )
            row_b = await conn.fetchrow(
                f"SELECT content, signature, module_name, file_path, content_hash"
                f" FROM code_chunks WHERE {cond} AND release_tag = ${tag_idx}",
                *p_base,
                version_b,
            )

            if row_a and not row_b:
                status = "removed"
            elif not row_a and row_b:
                status = "added"
            elif row_a and row_b and row_a["content_hash"] != row_b["content_hash"]:
                status = "changed"
            elif not row_a and not row_b:
                status = "not_found"
            else:
                status = "unchanged"

            return {
                "function_name": function_name,
                "repo": repo,
                "version_a": version_a,
                "version_b": version_b,
                "status": status,
                "content_a": dict(row_a) if row_a else None,
                "content_b": dict(row_b) if row_b else None,
            }

        # Broad comparison across all functions in code_tag_manifest.
        # code_tag_manifest columns: function_name, file_path, content_hash, repo,
        # release_tag — notably no module_name column.
        repo_cond = "AND repo = $3" if repo else ""
        bp: list = [version_a, version_b]
        if repo:
            bp.append(repo)
        li = len(bp) + 1
        oi = len(bp) + 2

        removed = await conn.fetch(
            f"""
            SELECT function_name, file_path FROM code_tag_manifest
            WHERE release_tag = $1 {repo_cond}
              AND (function_name, file_path) NOT IN (
                  SELECT function_name, file_path FROM code_tag_manifest
                  WHERE release_tag = $2 {repo_cond}
              )
            LIMIT ${li} OFFSET ${oi}
            """,
            *bp,
            limit,
            offset,
        )

        added = await conn.fetch(
            f"""
            SELECT function_name, file_path FROM code_tag_manifest
            WHERE release_tag = $2 {repo_cond}
              AND (function_name, file_path) NOT IN (
                  SELECT function_name, file_path FROM code_tag_manifest
                  WHERE release_tag = $1 {repo_cond}
              )
            LIMIT ${li} OFFSET ${oi}
            """,
            *bp,
            limit,
            offset,
        )

        # For changed: join on (function_name, file_path, repo) where content_hash differs.
        # Qualify repo column with table alias to avoid ambiguity when repo_cond is active.
        repo_cond_aliased = "AND a.repo = $3" if repo else ""
        changed = await conn.fetch(
            f"""
            SELECT a.function_name, a.file_path, a.content_hash AS hash_a, b.content_hash AS hash_b
            FROM code_tag_manifest a
            JOIN code_tag_manifest b
              ON a.function_name = b.function_name
             AND a.file_path = b.file_path
             AND a.repo = b.repo
            WHERE a.release_tag = $1
              AND b.release_tag = $2
              {repo_cond_aliased}
              AND a.content_hash != b.content_hash
            LIMIT ${li} OFFSET ${oi}
            """,
            *bp,
            limit,
            offset,
        )

        return {
            "repo": repo,
            "version_a": version_a,
            "version_b": version_b,
            "added": [dict(r) for r in added],
            "removed": [dict(r) for r in removed],
            "changed": [dict(r) for r in changed],
            "total_added": len(added),
            "total_removed": len(removed),
            "total_changed": len(changed),
            "offset": offset,
            "limit": limit,
        }
