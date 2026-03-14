"""CLI entry point for vibe-node."""

import subprocess
import sys

import typer

from vibe_node import __version__

app = typer.Typer(help="vibe-node — a vibe-coded Cardano node.")
db_app = typer.Typer(help="Database management commands.")
app.add_typer(db_app, name="db")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"vibe-node v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-v", callback=version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    pass


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
) -> None:
    """Drop all tables and recreate the database schema.

    THIS IS DESTRUCTIVE. All data in ParadeDB will be lost.
    Requires double confirmation unless --yes is passed.
    """
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
