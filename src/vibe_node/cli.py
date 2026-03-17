"""CLI entry point for vibe-node."""

import subprocess
import sys
from pathlib import Path

import typer

# Load .env file if present (so GITHUB_TOKEN etc. are available)
_env_file = Path.cwd() / ".env"
if _env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_file)

from vibe_node import __version__

app = typer.Typer(help="vibe-node — a vibe-coded Cardano node.", invoke_without_command=True)
db_app = typer.Typer(help="Database management commands.", invoke_without_command=True)
ingest_app = typer.Typer(help="Data ingestion commands.", invoke_without_command=True)

# Import infra commands and extra db commands from cli_infra
from vibe_node.cli_infra import infra_app, register_db_extras

app.add_typer(db_app, name="db")
app.add_typer(ingest_app, name="ingest")
app.add_typer(infra_app, name="infra")

# Register snapshot, restore, search on the db app
register_db_extras(db_app)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"vibe-node v{__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-v", callback=version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@db_app.callback(invoke_without_command=True)
def db_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@ingest_app.callback(invoke_without_command=True)
def ingest_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host to bind to."),
    port: int = typer.Option(3001, help="Port to listen on."),
) -> None:
    """Start the Cardano node."""
    typer.echo(f"vibe-node v{__version__}")
    typer.echo(f"Starting node on {host}:{port} ...")
    typer.echo("Not yet implemented — but the vibes are immaculate.")


@db_app.command()
def reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip first confirmation."),
    force: bool = typer.Option(False, "--force", "-f", help="Skip ALL confirmations (use in scripts)."),
) -> None:
    """Drop all tables and recreate the database schema.

    THIS IS DESTRUCTIVE. All data in ParadeDB will be lost.
    Use --force to skip all confirmations.
    """
    if not force:
        typer.echo("WARNING: This will DROP ALL TABLES in the ParadeDB database.")
        typer.echo("All spec documents, code chunks, issues, and embeddings will be lost.")
        typer.echo("")

        if not yes:
            confirm1 = typer.confirm("Are you sure you want to reset the database?")
            if not confirm1:
                typer.echo("Aborted.")
                raise typer.Exit()

        confirm2 = typer.confirm(
            "FINAL CONFIRMATION: Type 'y' to permanently delete all data"
        )
        if not confirm2:
            typer.echo("Aborted.")
            raise typer.Exit()

    typer.echo("")
    typer.echo("Resetting database...")

    # Terminate active connections first
    subprocess.run(
        [
            "docker", "compose", "exec", "-T", "paradedb",
            "psql", "-U", "vibenode", "-d", "vibenode", "-c",
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = 'vibenode' AND pid <> pg_backend_pid();",
        ],
        capture_output=True,
        text=True,
    )

    # Drop and recreate via docker compose
    result = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "paradedb",
            "psql", "-U", "vibenode", "-d", "vibenode", "-c",
            "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        typer.echo(f"Error dropping schema: {result.stderr}", err=True)
        raise typer.Exit(1)

    typer.echo("Schema dropped. Re-running init script...")

    # Re-run the init.sql
    result = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "paradedb",
            "psql", "-U", "vibenode", "-d", "vibenode",
            "-f", "/docker-entrypoint-initdb.d/init.sql",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        typer.echo(f"Error running init script: {result.stderr}", err=True)
        raise typer.Exit(1)

    typer.echo("Database reset complete. All tables recreated.")


@db_app.command()
def status() -> None:
    """Show database table row counts and connection status."""
    result = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "paradedb",
            "psql", "-U", "vibenode", "-d", "vibenode", "-c",
            """
            SELECT 'spec_documents' as table_name, count(*) FROM spec_documents
            UNION ALL
            SELECT 'code_chunks', count(*) FROM code_chunks
            UNION ALL
            SELECT 'github_issues', count(*) FROM github_issues
            UNION ALL
            SELECT 'github_issue_comments', count(*) FROM github_issue_comments
            UNION ALL
            SELECT 'github_pull_requests', count(*) FROM github_pull_requests
            UNION ALL
            SELECT 'github_pr_comments', count(*) FROM github_pr_comments
            ORDER BY table_name;
            """,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        typer.echo(f"Error connecting to database: {result.stderr}", err=True)
        typer.echo("Is ParadeDB running? Try: docker compose up paradedb -d")
        raise typer.Exit(1)

    typer.echo(result.stdout)


@ingest_app.command()
def issues(
    repo: str = typer.Option(
        None, "--repo", "-r",
        help="Single repo to ingest (e.g. IntersectMBO/cardano-node). Omit for all.",
    ),
    limit: int = typer.Option(
        None, "--limit", "-n",
        help="Max issues/PRs per repo (for testing). Omit for all.",
    ),
    rescan: bool = typer.Option(
        False, "--rescan",
        help="Re-fetch all issues/PRs to check for new comments and updates.",
    ),
) -> None:
    """Ingest GitHub issues and PRs with full discussion threads.

    Requires GITHUB_TOKEN env var for authentication (GraphQL API).
    Use --rescan to update existing items with new comments.
    """
    import asyncio
    import logging
    import os

    if not os.getenv("GITHUB_TOKEN"):
        typer.echo("ERROR: GITHUB_TOKEN is required (GraphQL API needs authentication).")
        typer.echo("Set it: export GITHUB_TOKEN=ghp_your_token_here")
        typer.echo("Get one: https://github.com/settings/tokens (no special scopes needed)")
        raise typer.Exit(1)

    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn, TimeRemainingColumn

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    async def run():
        from vibe_node.db.session import get_session
        from vibe_node.embed.client import EmbeddingClient
        from vibe_node.ingest.config import GITHUB_REPOS
        from vibe_node.ingest.github import GitHubIngestor

        repos = [repo] if repo else GITHUB_REPOS
        suffix = f" (limit {limit} per repo)" if limit else ""
        if rescan:
            suffix += " [RESCAN]"
        typer.echo(f"Ingesting issues and PRs from {len(repos)} repo(s){suffix}...")

        embed_client = EmbeddingClient()
        ingestor = GitHubIngestor()

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
            ) as progress:
                async with get_session() as session:
                    results = await ingestor.ingest_all(
                        session, embed_client, repos,
                        limit=limit, progress=progress,
                        rescan=rescan,
                    )

            typer.echo("")
            typer.echo("=== Ingestion Complete ===")
            total_issues = 0
            total_prs = 0
            for r, counts in results.items():
                typer.echo(f"  {r}: {counts['issues']} issues, {counts['prs']} PRs")
                total_issues += counts["issues"]
                total_prs += counts["prs"]
            typer.echo(f"  Total: {total_issues} issues, {total_prs} PRs")
        finally:
            await embed_client.close()
            await ingestor.close()

    asyncio.run(run())


@ingest_app.command()
def specs(
    format: str = typer.Option(
        None, "--format", "-f",
        help="Only ingest this format: markdown, cddl, latex, agda, pdf",
    ),
    source: str = typer.Option(
        None, "--source", "-s",
        help="Only ingest sources matching this substring (e.g. 'consensus').",
    ),
    limit: int = typer.Option(
        None, "--limit", "-n",
        help="Max files per source (for testing).",
    ),
    history: bool = typer.Option(
        False, "--history",
        help="Walk git commit history for versioned spec tracking (slow).",
    ),
) -> None:
    """Ingest spec documents from vendor submodules."""
    import asyncio
    import logging

    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    async def run():
        from vibe_node.db.session import get_session
        from vibe_node.embed.client import EmbeddingClient
        from vibe_node.ingest.specs.pipeline import SpecIngestor

        suffix = ""
        if format:
            suffix += f" format={format}"
        if source:
            suffix += f" source={source}"
        if limit:
            suffix += f" limit={limit}"
        if history:
            suffix += " [HISTORY MODE]"
        typer.echo(f"Ingesting spec documents...{suffix}")

        embed_client = EmbeddingClient()
        ingestor = SpecIngestor()

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
            ) as progress:
                async with get_session() as session:
                    if history:
                        results = await ingestor.ingest_history(
                            session, embed_client,
                            format_filter=format,
                            source_filter=source,
                            limit=limit,
                            progress=progress,
                        )
                    else:
                        results = await ingestor.ingest_all(
                            session, embed_client,
                            format_filter=format,
                            source_filter=source,
                            limit=limit,
                            progress=progress,
                        )

            typer.echo("")
            typer.echo("=== Spec Ingestion Complete ===")
            total = 0
            for key, count in results.items():
                typer.echo(f"  {key}: {count} chunks")
                total += count
            typer.echo(f"  Total: {total} chunks")
        finally:
            await embed_client.close()

    asyncio.run(run())


@ingest_app.command()
def code(
    repo: str = typer.Option(
        None, "--repo", "-r",
        help="Single repo to ingest (e.g. cardano-node). Omit for all.",
    ),
    limit: int = typer.Option(
        None, "--limit", "-n",
        help="Max tags per repo (for testing).",
    ),
) -> None:
    """Index Haskell source code from vendor submodules by release tag."""
    import asyncio
    import logging

    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    async def run():
        from vibe_node.db.session import get_session
        from vibe_node.embed.client import EmbeddingClient
        from vibe_node.ingest.code import CodeIngestor
        from vibe_node.ingest.config import CODE_REPOS

        repos = {repo: CODE_REPOS[repo]} if repo and repo in CODE_REPOS else CODE_REPOS
        suffix = f" (limit {limit} tags per repo)" if limit else ""
        typer.echo(f"Indexing code from {len(repos)} repo(s){suffix}...")

        embed_client = EmbeddingClient()
        ingestor = CodeIngestor()

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
            ) as progress:
                async with get_session() as session:
                    results = await ingestor.ingest_all(
                        session, embed_client, repos,
                        limit=limit, progress=progress,
                    )

            typer.echo("")
            typer.echo("=== Code Indexing Complete ===")
            total = 0
            for name, count in results.items():
                typer.echo(f"  {name}: {count} chunks")
                total += count
            typer.echo(f"  Total: {total} chunks")
        finally:
            await embed_client.close()

    asyncio.run(run())


@db_app.command(name="rebuild-manifest")
def rebuild_manifest() -> None:
    """Rebuild the code_tag_manifest table from existing code_chunks data."""
    import asyncio

    async def _run():
        from vibe_node.db.session import get_session
        from vibe_node.ingest.code import CodeIngestor

        typer.echo("Rebuilding code_tag_manifest from code_chunks...")
        async with get_session() as session:
            count = await CodeIngestor.rebuild_manifest(session)
        typer.echo(f"Done. Manifest has {count} entries.")

    asyncio.run(_run())


@db_app.command(name="backfill-completion")
def backfill_completion() -> None:
    """Backfill code_tag_completion markers from existing data.

    Run this once after upgrading to populate completion markers for
    tags that were fully ingested before the marker was added.
    """
    import asyncio

    async def _run():
        from vibe_node.db.session import get_session
        from vibe_node.ingest.code import CodeIngestor

        typer.echo("Backfilling code_tag_completion from existing data...")
        async with get_session() as session:
            count = await CodeIngestor.backfill_completion(session)
        typer.echo(f"Done. {count} tags marked as complete.")

    asyncio.run(_run())


@db_app.command(name="export-specs")
def export_specs_cmd() -> None:
    """Export pre-converted spec markdown to docs/specs/ organized by era.

    Reads era metadata from the database, then copies pre-converted markdown
    from data/specs/ to docs/specs/{era}/ with clean filenames and index pages.
    """
    from vibe_node.export_specs import export_specs

    typer.echo("Exporting spec documents to docs/specs/...")
    stats = export_specs()
    if not stats:
        typer.echo("No documents exported.", err=True)
        raise typer.Exit(1)
    total = sum(stats.values())
    typer.echo(f"\nDone: {total} documents across {len(stats)} categories.")


@db_app.command(name="create-indexes")
def create_indexes() -> None:
    """Create BM25 and HNSW indexes on all tables."""
    sql_path = Path(__file__).resolve().parents[2] / "infra" / "db" / "create_indexes.sql"
    if not sql_path.exists():
        typer.echo(f"Index SQL not found: {sql_path}", err=True)
        raise typer.Exit(1)

    typer.echo("Creating BM25 and HNSW indexes (this may take a few minutes)...")
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "paradedb",
         "psql", "-U", "vibenode", "-d", "vibenode", "-f", "/dev/stdin"],
        input=sql_path.read_text(),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        typer.echo(f"Error creating indexes:\n{result.stderr}", err=True)
        raise typer.Exit(1)
    typer.echo("Indexes created successfully.")
    typer.echo(result.stdout)
