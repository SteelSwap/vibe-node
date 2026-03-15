"""GitHub issues and pull requests ingestion pipeline.

Uses GitHub's GraphQL API to fetch issues, PRs, and all discussion threads
in bulk (100 items + comments per request instead of 1 per request with REST).
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from vibe_node.embed.client import EmbeddingClient
from vibe_node.ingest.config import GITHUB_REPOS, GITHUB_TOKEN

logger = logging.getLogger(__name__)

GITHUB_GRAPHQL = "https://api.github.com/graphql"

# ── GraphQL Queries ─────────────────────────────────────────────────

ISSUES_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        title
        body
        state
        createdAt
        closedAt
        updatedAt
        author { login }
        labels(first: 20) { nodes { name } }
        comments(first: 100) {
          nodes {
            databaseId
            author { login }
            body
            createdAt
            updatedAt
          }
        }
      }
    }
  }
}
"""

PRS_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        title
        body
        state
        merged
        createdAt
        closedAt
        mergedAt
        updatedAt
        author { login }
        mergeCommit { oid }
        baseRefName
        headRefName
        labels(first: 20) { nodes { name } }
        comments(first: 50) {
          nodes {
            databaseId
            author { login }
            body
            createdAt
            updatedAt
          }
        }
        reviews(first: 50) {
          nodes {
            databaseId
            author { login }
            body
            state
            submittedAt
          }
        }
        reviewThreads(first: 50) {
          nodes {
            comments(first: 20) {
              nodes {
                databaseId
                author { login }
                body
                path
                diffHunk
                createdAt
                updatedAt
              }
            }
          }
        }
      }
    }
  }
}
"""


class GitHubIngestor:
    """Fetches and stores GitHub issues and PRs via GraphQL."""

    def __init__(self, token: str = GITHUB_TOKEN):
        if not token:
            raise RuntimeError(
                "GITHUB_TOKEN is required for GitHub ingestion. "
                "GraphQL API does not support unauthenticated access. "
                "Set GITHUB_TOKEN in your environment or .env file. "
                "Get one: https://github.com/settings/tokens"
            )
        self._client = httpx.AsyncClient(
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

    async def _graphql(self, query: str, variables: dict) -> dict:
        """Execute a GraphQL query with rate limit handling."""
        response = await self._client.post(
            GITHUB_GRAPHQL,
            json={"query": query, "variables": variables},
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            errors = data["errors"]
            # Check for rate limiting
            for err in errors:
                if "rate limit" in err.get("message", "").lower():
                    logger.warning("Rate limited. Sleeping 60s...")
                    await asyncio.sleep(60)
                    return await self._graphql(query, variables)
            raise RuntimeError(f"GraphQL errors: {errors}")

        return data["data"]

    @staticmethod
    def _parse_dt(s: str | None) -> datetime | None:
        if not s:
            return None
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    @staticmethod
    def _author(node: dict) -> str:
        author = node.get("author")
        if author and author.get("login"):
            return author["login"]
        return "ghost"

    @staticmethod
    def _build_content_combined(
        title: str, body: str | None, comments: list[dict],
    ) -> str:
        parts = [f"# {title}"]
        if body:
            parts.append(body)
        for c in comments:
            author = c.get("_author", "unknown")
            date = c.get("_date", "")
            parts.append(f"\n--- {author} ({date}) ---\n{c.get('body', '')}")
        return "\n\n".join(parts)

    @staticmethod
    def _extract_linked(body: str | None, repo: str) -> list[str]:
        if not body:
            return []
        import re
        refs = re.findall(r'#(\d+)', body)
        urls = re.findall(
            r'https://github\.com/[\w-]+/[\w-]+/(?:issues|pull)/(\d+)', body,
        )
        return list(set(f"{repo}#{r}" for r in refs + urls))

    # ── Issues ──────────────────────────────────────────────────────

    async def ingest_issues(
        self,
        repo: str,
        session: AsyncSession,
        embed_client: EmbeddingClient,
        limit: int | None = None,
        progress=None,
    ) -> int:
        owner, name = repo.split("/")
        cursor = None
        count = 0
        total = None
        task = None

        while True:
            data = await self._graphql(ISSUES_QUERY, {
                "owner": owner, "name": name, "cursor": cursor,
            })
            issues_data = data["repository"]["issues"]

            if total is None:
                total = issues_data["totalCount"]
                effective_total = min(total, limit) if limit else total
                if progress:
                    task = progress.add_task(
                        f"[blue]{repo} issues", total=effective_total,
                    )
                logger.info("Fetching %d issues from %s", effective_total, repo)

            for node in issues_data["nodes"]:
                if limit and count >= limit:
                    break

                number = node["number"]

                # Check if already ingested
                existing = await session.execute(
                    text("SELECT id FROM github_issues WHERE repo = :repo AND issue_number = :num"),
                    {"repo": repo, "num": number},
                )
                if existing.first():
                    if progress and task is not None:
                        progress.update(task, advance=1)
                    count += 1
                    continue

                # Flatten comments
                comments = [
                    {
                        "body": c.get("body", ""),
                        "_author": self._author(c),
                        "_date": c.get("createdAt", ""),
                        **c,
                    }
                    for c in node.get("comments", {}).get("nodes", [])
                ]

                content_combined = self._build_content_combined(
                    node["title"], node.get("body"), comments,
                )

                embedding = await embed_client.embed(content_combined[:8000])
                issue_id = uuid.uuid4()
                labels = [l["name"] for l in node.get("labels", {}).get("nodes", [])]

                await session.execute(
                    text("""
                        INSERT INTO github_issues (
                            id, repo, issue_number, title, body, state, labels,
                            created_at, closed_at, updated_at, author, comment_count,
                            content_combined, embedding, linked_prs, metadata
                        ) VALUES (
                            :id, :repo, :num, :title, :body, :state, :labels,
                            :created_at, :closed_at, :updated_at, :author, :comment_count,
                            :content_combined, :embedding, :linked_prs, NULL
                        )
                    """),
                    {
                        "id": str(issue_id),
                        "repo": repo,
                        "num": number,
                        "title": node["title"],
                        "body": node.get("body"),
                        "state": node["state"].lower(),
                        "labels": labels,
                        "created_at": self._parse_dt(node["createdAt"]),
                        "closed_at": self._parse_dt(node.get("closedAt")),
                        "updated_at": self._parse_dt(node.get("updatedAt")),
                        "author": self._author(node),
                        "comment_count": len(comments),
                        "content_combined": content_combined,
                        "embedding": str(embedding),
                        "linked_prs": self._extract_linked(node.get("body"), repo),
                    },
                )

                # Store individual comments
                for c in node.get("comments", {}).get("nodes", []):
                    db_id = c.get("databaseId")
                    if not db_id:
                        continue
                    await session.execute(
                        text("""
                            INSERT INTO github_issue_comments (
                                id, issue_id, repo, issue_number, comment_id,
                                author, body, created_at, updated_at
                            ) VALUES (
                                :id, :issue_id, :repo, :num, :comment_id,
                                :author, :body, :created_at, :updated_at
                            )
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "issue_id": str(issue_id),
                            "repo": repo,
                            "num": number,
                            "comment_id": db_id,
                            "author": self._author(c),
                            "body": c.get("body") or "",
                            "created_at": self._parse_dt(c.get("createdAt")),
                            "updated_at": self._parse_dt(c.get("updatedAt")),
                        },
                    )

                count += 1
                if progress and task is not None:
                    progress.update(task, advance=1)
                if count % 50 == 0:
                    await session.commit()

            await session.commit()

            if limit and count >= limit:
                break
            if not issues_data["pageInfo"]["hasNextPage"]:
                break
            cursor = issues_data["pageInfo"]["endCursor"]

        if progress and task is not None:
            progress.update(task, completed=progress.tasks[task].total)
        logger.info("Completed %s: %d issues ingested", repo, count)
        return count

    # ── Pull Requests ───────────────────────────────────────────────

    async def ingest_prs(
        self,
        repo: str,
        session: AsyncSession,
        embed_client: EmbeddingClient,
        limit: int | None = None,
        progress=None,
    ) -> int:
        owner, name = repo.split("/")
        cursor = None
        count = 0
        total = None
        task = None

        while True:
            data = await self._graphql(PRS_QUERY, {
                "owner": owner, "name": name, "cursor": cursor,
            })
            prs_data = data["repository"]["pullRequests"]

            if total is None:
                total = prs_data["totalCount"]
                effective_total = min(total, limit) if limit else total
                if progress:
                    task = progress.add_task(
                        f"[purple]{repo} PRs", total=effective_total,
                    )
                logger.info("Fetching %d PRs from %s", effective_total, repo)

            for node in prs_data["nodes"]:
                if limit and count >= limit:
                    break

                number = node["number"]

                existing = await session.execute(
                    text("SELECT id FROM github_pull_requests WHERE repo = :repo AND pr_number = :num"),
                    {"repo": repo, "num": number},
                )
                if existing.first():
                    if progress and task is not None:
                        progress.update(task, advance=1)
                    count += 1
                    continue

                # Collect all comment types
                general_comments = node.get("comments", {}).get("nodes", [])
                reviews = [
                    r for r in node.get("reviews", {}).get("nodes", [])
                    if r.get("body")
                ]
                review_comments = []
                for thread in node.get("reviewThreads", {}).get("nodes", []):
                    review_comments.extend(
                        thread.get("comments", {}).get("nodes", [])
                    )

                # Build combined content
                all_for_combined = [
                    {"body": c.get("body", ""), "_author": self._author(c), "_date": c.get("createdAt", "")}
                    for c in general_comments
                ] + [
                    {"body": r.get("body", ""), "_author": self._author(r), "_date": r.get("submittedAt", "")}
                    for r in reviews
                ] + [
                    {"body": rc.get("body", ""), "_author": self._author(rc), "_date": rc.get("createdAt", "")}
                    for rc in review_comments
                ]

                content_combined = self._build_content_combined(
                    node["title"], node.get("body"), all_for_combined,
                )

                embedding = await embed_client.embed(content_combined[:8000])
                pr_id = uuid.uuid4()
                labels = [l["name"] for l in node.get("labels", {}).get("nodes", [])]
                merge_commit = node.get("mergeCommit")

                await session.execute(
                    text("""
                        INSERT INTO github_pull_requests (
                            id, repo, pr_number, title, body, state, merged, labels,
                            created_at, closed_at, merged_at, updated_at, author,
                            merge_commit_sha, base_branch, head_branch,
                            comment_count, review_comment_count,
                            content_combined, embedding, linked_issues, metadata
                        ) VALUES (
                            :id, :repo, :num, :title, :body, :state, :merged, :labels,
                            :created_at, :closed_at, :merged_at, :updated_at, :author,
                            :merge_commit_sha, :base_branch, :head_branch,
                            :comment_count, :review_comment_count,
                            :content_combined, :embedding, :linked_issues, NULL
                        )
                    """),
                    {
                        "id": str(pr_id),
                        "repo": repo,
                        "num": number,
                        "title": node["title"],
                        "body": node.get("body"),
                        "state": node["state"].lower(),
                        "merged": node.get("merged", False),
                        "labels": labels,
                        "created_at": self._parse_dt(node["createdAt"]),
                        "closed_at": self._parse_dt(node.get("closedAt")),
                        "merged_at": self._parse_dt(node.get("mergedAt")),
                        "updated_at": self._parse_dt(node.get("updatedAt")),
                        "author": self._author(node),
                        "merge_commit_sha": merge_commit["oid"] if merge_commit else None,
                        "base_branch": node.get("baseRefName", ""),
                        "head_branch": node.get("headRefName", ""),
                        "comment_count": len(general_comments),
                        "review_comment_count": len(review_comments),
                        "content_combined": content_combined,
                        "embedding": str(embedding),
                        "linked_issues": self._extract_linked(node.get("body"), repo),
                    },
                )

                # Store general comments
                for c in general_comments:
                    db_id = c.get("databaseId")
                    if not db_id:
                        continue
                    await session.execute(
                        text("""
                            INSERT INTO github_pr_comments (
                                id, pr_id, repo, pr_number, comment_id, comment_type,
                                author, body, created_at, updated_at
                            ) VALUES (
                                :id, :pr_id, :repo, :num, :comment_id, :type,
                                :author, :body, :created_at, :updated_at
                            )
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "pr_id": str(pr_id),
                            "repo": repo,
                            "num": number,
                            "comment_id": db_id,
                            "type": "comment",
                            "author": self._author(c),
                            "body": c.get("body") or "",
                            "created_at": self._parse_dt(c.get("createdAt")),
                            "updated_at": self._parse_dt(c.get("updatedAt")),
                        },
                    )

                # Store review summaries
                for r in reviews:
                    db_id = r.get("databaseId")
                    if not db_id:
                        continue
                    await session.execute(
                        text("""
                            INSERT INTO github_pr_comments (
                                id, pr_id, repo, pr_number, comment_id, comment_type,
                                author, body, created_at
                            ) VALUES (
                                :id, :pr_id, :repo, :num, :comment_id, :type,
                                :author, :body, :created_at
                            )
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "pr_id": str(pr_id),
                            "repo": repo,
                            "num": number,
                            "comment_id": db_id,
                            "type": "review",
                            "author": self._author(r),
                            "body": r["body"],
                            "created_at": self._parse_dt(r.get("submittedAt")),
                        },
                    )

                # Store line-level review comments
                for rc in review_comments:
                    db_id = rc.get("databaseId")
                    if not db_id:
                        continue
                    await session.execute(
                        text("""
                            INSERT INTO github_pr_comments (
                                id, pr_id, repo, pr_number, comment_id, comment_type,
                                author, body, file_path, diff_hunk, created_at, updated_at
                            ) VALUES (
                                :id, :pr_id, :repo, :num, :comment_id, :type,
                                :author, :body, :file_path, :diff_hunk, :created_at, :updated_at
                            )
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "pr_id": str(pr_id),
                            "repo": repo,
                            "num": number,
                            "comment_id": db_id,
                            "type": "review_comment",
                            "author": self._author(rc),
                            "body": rc.get("body") or "",
                            "file_path": rc.get("path"),
                            "diff_hunk": rc.get("diffHunk"),
                            "created_at": self._parse_dt(rc.get("createdAt")),
                            "updated_at": self._parse_dt(rc.get("updatedAt")),
                        },
                    )

                count += 1
                if progress and task is not None:
                    progress.update(task, advance=1)
                if count % 50 == 0:
                    await session.commit()

            await session.commit()

            if limit and count >= limit:
                break
            if not prs_data["pageInfo"]["hasNextPage"]:
                break
            cursor = prs_data["pageInfo"]["endCursor"]

        if progress and task is not None:
            progress.update(task, completed=progress.tasks[task].total)
        logger.info("Completed %s: %d PRs ingested", repo, count)
        return count

    # ── Orchestration ───────────────────────────────────────────────

    async def ingest_repo(
        self,
        repo: str,
        session: AsyncSession,
        embed_client: EmbeddingClient,
        limit: int | None = None,
        progress=None,
    ) -> dict[str, int]:
        issues_count = await self.ingest_issues(
            repo, session, embed_client, limit=limit, progress=progress,
        )
        prs_count = await self.ingest_prs(
            repo, session, embed_client, limit=limit, progress=progress,
        )
        return {"issues": issues_count, "prs": prs_count}

    async def ingest_all(
        self,
        session: AsyncSession,
        embed_client: EmbeddingClient,
        repos: list[str] | None = None,
        limit: int | None = None,
        progress=None,
    ) -> dict[str, dict[str, int]]:
        repos = repos or GITHUB_REPOS
        results = {}
        for repo in repos:
            results[repo] = await self.ingest_repo(
                repo, session, embed_client, limit=limit, progress=progress,
            )
        return results

    async def close(self):
        await self._client.aclose()
