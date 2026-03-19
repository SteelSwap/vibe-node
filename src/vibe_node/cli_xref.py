"""CLI commands for cross-referencing, coverage, and test specifications."""
import asyncio
import uuid as _uuid

import typer
from rich.console import Console
from rich.table import Table

console = Console()

xref_app = typer.Typer(help="Cross-reference management")
test_spec_app = typer.Typer(help="Test specification management")


@xref_app.command("add")
def xref_add(
    source_type: str = typer.Argument(help="Source entity type"),
    source_id: str = typer.Argument(help="Source entity UUID"),
    target_type: str = typer.Argument(help="Target entity type"),
    target_id: str = typer.Argument(help="Target entity UUID"),
    relationship: str = typer.Argument(help="Relationship type"),
    confidence: float = typer.Option(1.0, "--confidence", "-c"),
    notes: str | None = typer.Option(None, "--notes"),
    created_by: str = typer.Option("manual", "--by"),
):
    """Add a cross-reference between two entities."""
    async def _run():
        from vibe_node.db.pool import get_pool, close_pool
        from vibe_node.db.xref import add_xref

        pool = await get_pool()
        async with pool.acquire() as conn:
            row_id = await add_xref(
                conn, source_type, _uuid.UUID(source_id),
                target_type, _uuid.UUID(target_id),
                relationship, confidence, notes, created_by,
            )
        await close_pool()
        console.print(f"[green]Cross-reference added:[/green] {row_id}")

    asyncio.run(_run())


@xref_app.command("query")
def xref_query(
    entity_type: str = typer.Argument(help="Entity type"),
    entity_id: str = typer.Argument(help="Entity UUID"),
    relationship: str | None = typer.Option(None, "--rel", "-r"),
    target_type: str | None = typer.Option(None, "--target", "-t"),
):
    """Query cross-references for an entity."""
    async def _run():
        from vibe_node.db.pool import get_pool, close_pool
        from vibe_node.db.xref import query_xrefs

        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await query_xrefs(
                conn, entity_type, _uuid.UUID(entity_id),
                relationship, target_type,
            )
        await close_pool()

        table = Table(title="Cross References")
        table.add_column("Direction")
        table.add_column("Relationship")
        table.add_column("Entity Type")
        table.add_column("ID")
        table.add_column("Confidence")
        table.add_column("By")
        for r in rows:
            table.add_row(
                r["direction"], r["relationship"], r["entity_type"],
                r["id"][:12] + "...", f"{r['confidence']:.1f}", r["created_by"],
            )
        console.print(table)

    asyncio.run(_run())


@xref_app.command("coverage")
def coverage(
    subsystem: str | None = typer.Option(None, "--subsystem", "-s"),
    era: str | None = typer.Option(None, "--era", "-e"),
):
    """Show spec coverage report — which rules have tests and implementations."""
    async def _run():
        from vibe_node.db.pool import get_pool, close_pool
        from vibe_node.db.xref import coverage_report, uncovered_sections

        pool = await get_pool()
        async with pool.acquire() as conn:
            report = await coverage_report(conn, subsystem, era)
            uncovered = await uncovered_sections(
                conn, subsystem, era, no_tests=True, no_implementation=True, limit=20,
            )
        await close_pool()

        console.print("\n[bold]Spec Coverage Report[/bold]\n")
        console.print(f"  Total spec sections:    {report['total']}")
        console.print(f"  With implementation:    {report['with_implementation']}")
        console.print(f"  With planned tests:     {report['with_tests']}")
        console.print(f"  With gaps documented:   {report['with_gaps']}")
        console.print(f"  [red]Uncovered (neither):[/red]  {report['uncovered']}")

        if uncovered:
            console.print(f"\n[bold]Uncovered Sections[/bold] (no tests, no implementation):\n")
            table = Table()
            table.add_column("Section ID")
            table.add_column("Title")
            table.add_column("Subsystem")
            table.add_column("Era")
            for s in uncovered:
                table.add_row(s["section_id"], s["title"][:40], s["subsystem"], s["era"])
            console.print(table)

    asyncio.run(_run())


@test_spec_app.command("list")
def test_specs_list(
    subsystem: str | None = typer.Option(None, "--subsystem", "-s"),
    phase: str | None = typer.Option(None, "--phase", "-p"),
    test_type: str | None = typer.Option(None, "--type", "-t"),
    priority: str | None = typer.Option(None, "--priority"),
    limit: int = typer.Option(50, "--limit", "-n"),
):
    """List planned test specifications."""
    async def _run():
        from vibe_node.db.pool import get_pool, close_pool
        from vibe_node.db.test_specs import list_test_specs

        pool = await get_pool()
        async with pool.acquire() as conn:
            rows, total = await list_test_specs(
                conn, subsystem, phase, test_type, priority, limit,
            )
        await close_pool()

        table = Table(title=f"Test Specifications ({total} total)")
        table.add_column("Name")
        table.add_column("Subsystem")
        table.add_column("Type")
        table.add_column("Priority")
        table.add_column("Phase")
        for r in rows:
            table.add_row(
                r["test_name"][:40], r["subsystem"], r["test_type"],
                r["priority"], r["phase"],
            )
        console.print(table)

    asyncio.run(_run())
