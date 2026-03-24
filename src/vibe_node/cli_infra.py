"""Infrastructure and database management CLI commands."""

import subprocess
from pathlib import Path

import typer

infra_app = typer.Typer(help="Docker infrastructure management.", invoke_without_command=True)


@infra_app.callback(invoke_without_command=True)
def infra_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


def _compose(*args: str, stream: bool = False) -> subprocess.CompletedProcess | None:
    """Run a docker compose command."""
    cmd = ["docker", "compose", *args]
    if stream:
        subprocess.run(cmd)
        return None
    return subprocess.run(cmd, capture_output=True, text=True)


@infra_app.command()
def up(
    detach: bool = typer.Option(True, "--detach/--no-detach", "-d", help="Run in background."),
) -> None:
    """Start the full Docker Compose stack."""
    args = ["up"]
    if detach:
        args.append("-d")
    typer.echo("Starting vibe-node infrastructure...")
    _compose(*args, stream=True)


@infra_app.command()
def down(
    volumes: bool = typer.Option(False, "--volumes", "-v", help="Also remove volumes."),
) -> None:
    """Stop the Docker Compose stack."""
    args = ["down"]
    if volumes:
        args.append("-v")
    typer.echo("Stopping vibe-node infrastructure...")
    _compose(*args, stream=True)


@infra_app.command(name="status")
def infra_status() -> None:
    """Show status of all Docker services."""
    _compose("ps", stream=True)


@infra_app.command()
def logs(
    service: str = typer.Argument(
        None, help="Service name (e.g. paradedb, ollama). Omit for all."
    ),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output."),
    tail: int = typer.Option(50, "--tail", "-n", help="Number of lines to show."),
) -> None:
    """View logs from Docker services."""
    args = ["logs", f"--tail={tail}"]
    if follow:
        args.append("--follow")
    if service:
        args.append(service)
    _compose(*args, stream=True)


# ── Database snapshot/restore/search ────────────────────────────────


def register_db_extras(db_app: typer.Typer) -> None:
    """Register snapshot, restore, and search commands on the db app."""

    @db_app.command()
    def snapshot() -> None:
        """Create a pg_dump snapshot of the ParadeDB database."""
        from datetime import datetime as dt

        snapshots_dir = Path("snapshots")
        snapshots_dir.mkdir(exist_ok=True)

        timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
        filename = snapshots_dir / f"vibenode_{timestamp}.dump"

        typer.echo(f"Creating snapshot: {filename}")

        result = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "paradedb",
                "pg_dump",
                "-U",
                "vibenode",
                "-d",
                "vibenode",
                "--format=custom",
                "--compress=zstd",
            ],
            capture_output=True,
        )

        if result.returncode != 0:
            typer.echo(f"Error: {result.stderr.decode()}", err=True)
            raise typer.Exit(1)

        filename.write_bytes(result.stdout)
        size_mb = len(result.stdout) / (1024 * 1024)
        typer.echo(f"Snapshot saved: {filename} ({size_mb:.1f} MB)")

    @db_app.command()
    def restore(
        snapshot_file: Path = typer.Argument(..., help="Path to .dump file."),
        force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation."),
    ) -> None:
        """Restore the database from a pg_dump snapshot."""
        if not snapshot_file.exists():
            typer.echo(f"File not found: {snapshot_file}", err=True)
            raise typer.Exit(1)

        if not force:
            typer.echo(f"This will REPLACE all data in ParadeDB with {snapshot_file.name}")
            if not typer.confirm("Continue?"):
                typer.echo("Aborted.")
                raise typer.Exit()

        typer.echo(f"Restoring from {snapshot_file}...")

        # Terminate active connections and drop schema
        subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "paradedb",
                "psql",
                "-U",
                "vibenode",
                "-d",
                "vibenode",
                "-c",
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = 'vibenode' AND pid <> pg_backend_pid();",
            ],
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "paradedb",
                "psql",
                "-U",
                "vibenode",
                "-d",
                "vibenode",
                "-c",
                "DROP SCHEMA public CASCADE; CREATE SCHEMA public;",
            ],
            capture_output=True,
            text=True,
        )

        # Restore from dump via stdin
        data = snapshot_file.read_bytes()
        result = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "paradedb",
                "pg_restore",
                "-U",
                "vibenode",
                "-d",
                "vibenode",
                "--no-owner",
                "--no-privileges",
            ],
            input=data,
            capture_output=True,
        )

        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")
            if "ERROR" in stderr:
                typer.echo(f"Restore errors:\n{stderr}", err=True)
                raise typer.Exit(1)

        typer.echo("Restore complete.")

    @db_app.command(name="search")
    def search(
        query: str = typer.Argument(help="Search query text"),
        table: str = typer.Option(
            "all", "--table", "-t", help="Entity type: spec_doc, code, issue, pr, all"
        ),
        limit: int = typer.Option(10, "--limit", "-n", help="Max results"),
    ) -> None:
        """Search the knowledge base using BM25 + vector fusion (RRF)."""
        import asyncio

        async def _run():
            from vibe.tools.db.pool import close_pool, get_pool
            from vibe.tools.db.search import search_all
            from vibe.tools.embed.client import EmbeddingClient

            embed_client = EmbeddingClient()
            embedding = await embed_client.embed(query)
            await embed_client.close()

            entity_type = None if table == "all" else table

            pool = await get_pool()
            async with pool.acquire() as conn:
                results, total = await search_all(
                    conn,
                    query,
                    embedding,
                    entity_type=entity_type,
                    limit=limit,
                )
            await close_pool()

            if not results:
                typer.echo("No results found.")
                return

            from rich.console import Console
            from rich.table import Table as RichTable

            console = Console()
            t = RichTable(title=f"Search: '{query}' ({total} results)")
            t.add_column("Type", width=10)
            t.add_column("Title", width=40)
            t.add_column("Score", width=8)
            t.add_column("Preview", width=60)

            for r in results:
                t.add_row(
                    r.get("entity_type", "?"),
                    (r.get("_title", "") or "")[:40],
                    f"{r.get('rrf_score', 0) or r.get('rrf_total', 0):.4f}",
                    (r.get("_preview", "") or "")[:60].replace("\n", " "),
                )
            console.print(t)

        asyncio.run(_run())
