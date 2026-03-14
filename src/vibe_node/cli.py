"""CLI entry point for vibe-node."""

import typer

from vibe_node import __version__

app = typer.Typer(help="vibe-node — a vibe-coded Cardano node.")


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
