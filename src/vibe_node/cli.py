"""CLI entry point for vibe-node."""

import subprocess
import sys
from pathlib import Path
from typing import Any

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

research_app = typer.Typer(help="Research and analysis commands.", invoke_without_command=True)
eval_app = typer.Typer(help="Evaluation and benchmarking commands.", invoke_without_command=True)

app.add_typer(db_app, name="db")
app.add_typer(ingest_app, name="ingest")
app.add_typer(infra_app, name="infra")
app.add_typer(research_app, name="research")
app.add_typer(eval_app, name="eval")

# Register snapshot, restore, search on the db app
register_db_extras(db_app)

# Register cross-referencing and test-specs subcommands
from vibe_node.cli_xref import xref_app, test_spec_app

db_app.add_typer(xref_app, name="xref")
db_app.add_typer(test_spec_app, name="test-specs")


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
    host: str = typer.Option("0.0.0.0", envvar="VIBE_HOST", help="Host to bind to."),
    port: int = typer.Option(3001, envvar="VIBE_NODE_PORT", help="Port to listen on."),
    network_magic: int = typer.Option(764824073, envvar="VIBE_NETWORK_MAGIC", help="Network magic number."),
    peers: str = typer.Option("", envvar="VIBE_PEERS", help="Comma-separated peer list (host:port,...)."),
    genesis_dir: str = typer.Option(None, envvar="VIBE_GENESIS_DIR", help="Path to genesis files directory."),
    db_path: str = typer.Option("./db", envvar="VIBE_DATA_DIR", help="Data directory for chain storage."),
    socket_path: str = typer.Option(None, envvar="VIBE_SOCKET_PATH", help="Unix socket path for N2C."),
    kes_key: str = typer.Option(None, envvar="VIBE_KES_KEY", help="Path to KES signing key file."),
    vrf_key: str = typer.Option(None, envvar="VIBE_VRF_KEY", help="Path to VRF signing key file."),
    vrf_vkey: str = typer.Option(None, envvar="VIBE_VRF_VKEY", help="Path to VRF verification key file."),
    opcert: str = typer.Option(None, envvar="VIBE_OPCERT", help="Path to operational certificate file."),
    cold_vkey: str = typer.Option(None, envvar="VIBE_COLD_VKEY", help="Path to cold verification key file."),
    cold_skey: str = typer.Option(None, envvar="VIBE_COLD_SKEY", help="Path to cold signing key file."),
    permissive_validation: bool = typer.Option(False, envvar="VIBE_PERMISSIVE_VALIDATION", help="Log validation errors but still store blocks."),
    mithril_snapshot: str = typer.Option(None, envvar="VIBE_MITHRIL_SNAPSHOT", help="Path to Mithril snapshot directory for fast bootstrap."),
) -> None:
    """Start the Cardano node."""
    import asyncio
    import hashlib
    import json
    import logging
    from datetime import datetime, timezone

    from vibe.cardano.node import NodeConfig, PeerAddress, PoolKeys, run_node

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    typer.echo(f"vibe-node v{__version__}")
    typer.echo(f"Starting node on {host}:{port} (magic={network_magic})")

    # Parse genesis parameters from shelley-genesis.json if available
    system_start = datetime(2017, 9, 23, 21, 44, 51, tzinfo=timezone.utc)
    slot_length = 1.0
    epoch_length = 432000
    security_param = 2160
    active_slot_coeff = 0.05
    protocol_params = None
    slots_per_kes_period = 129600
    genesis_hash = b""
    initial_pool_stakes: dict[bytes, int] = {}

    if genesis_dir is not None:
        genesis_path = Path(genesis_dir) / "shelley-genesis.json"
        if genesis_path.exists():
            with open(genesis_path) as f:
                sg = json.load(f)
            system_start = datetime.fromisoformat(sg["systemStart"])
            if system_start.tzinfo is None:
                system_start = system_start.replace(tzinfo=timezone.utc)
            slot_length = sg.get("slotLength", slot_length)
            epoch_length = sg.get("epochLength", epoch_length)
            security_param = sg.get("securityParam", security_param)
            active_slot_coeff = sg.get("activeSlotsCoeff", active_slot_coeff)
            protocol_params = sg.get("protocolParams", None)
            slots_per_kes_period = sg.get("slotsPerKESPeriod", 129600)
            genesis_bytes = genesis_path.read_bytes()  # Hash raw file bytes, not re-encoded JSON
            genesis_hash = hashlib.blake2b(genesis_bytes, digest_size=32).digest()
            initial_pool_stakes = _parse_genesis_stake(sg)
            typer.echo(f"Genesis: systemStart={system_start.isoformat()}, "
                       f"slotLength={slot_length}s, epochLength={epoch_length}, "
                       f"pools={len(initial_pool_stakes)}")

    # Parse peers
    peer_list: list[PeerAddress] = []
    if peers:
        for p in peers.split(","):
            p = p.strip()
            if not p:
                continue
            if ":" in p:
                h, pt = p.rsplit(":", 1)
                peer_list.append(PeerAddress(host=h, port=int(pt)))
            else:
                peer_list.append(PeerAddress(host=p, port=3001))

    typer.echo(f"Peers: {len(peer_list)} configured")

    # Load pool keys for block production (optional)
    pool_keys: PoolKeys | None = None
    if vrf_key and cold_skey:
        pool_keys = _load_pool_keys(
            vrf_key_path=vrf_key,
            vrf_vkey_path=vrf_vkey,
            cold_vkey_path=cold_vkey,
            cold_skey_path=cold_skey,
        )
        typer.echo("Block producer mode: pool keys loaded")
    else:
        typer.echo("Relay mode: no pool keys configured")

    config = NodeConfig(
        network_magic=network_magic,
        slot_length=slot_length,
        epoch_length=epoch_length,
        security_param=security_param,
        active_slot_coeff=active_slot_coeff,
        system_start=system_start,
        host=host,
        port=port,
        socket_path=socket_path,
        pool_keys=pool_keys,
        peers=peer_list,
        db_path=Path(db_path),
        genesis_hash=genesis_hash,
        protocol_params=protocol_params,
        permissive_validation=permissive_validation,
        slots_per_kes_period=slots_per_kes_period,
        initial_pool_stakes=initial_pool_stakes,
        mithril_snapshot_path=Path(mithril_snapshot) if mithril_snapshot else None,
    )

    run_node(config)  # Sync — handles its own asyncio for init, then threads


def _parse_genesis_stake(sg: dict) -> dict[bytes, int]:
    """Compute initial pool stake from shelley-genesis.json.

    Combines initialFunds + staking.stake delegations to sum lovelace
    per pool. Falls back to pledge values if no delegated funds.
    """
    staking = sg.get("staking", {})
    pools_data = staking.get("pools", {})
    stake_delegations = staking.get("stake", {})
    initial_funds = sg.get("initialFunds", {})

    pool_stakes: dict[bytes, int] = {}

    if initial_funds and stake_delegations:
        staker_to_pool: dict[str, bytes] = {}
        for staker_hex, pool_hex in stake_delegations.items():
            staker_to_pool[staker_hex.lower()] = bytes.fromhex(pool_hex)

        for addr_hex, lovelace in initial_funds.items():
            if len(addr_hex) >= 114:
                staking_cred = addr_hex[-56:].lower()
                pool_id = staker_to_pool.get(staking_cred)
                if pool_id is not None:
                    pool_stakes[pool_id] = pool_stakes.get(pool_id, 0) + lovelace

    if not pool_stakes and pools_data:
        for pool_hex, pool_info in pools_data.items():
            pool_stakes[bytes.fromhex(pool_hex)] = pool_info.get("pledge", 0)

    return pool_stakes


def _load_pool_keys(
    vrf_key_path: str,
    vrf_vkey_path: str | None,
    cold_vkey_path: str | None,
    cold_skey_path: str,
) -> Any:
    """Load pool key material from cardano-cli generated key files.

    Reads the cborHex field from JSON key files and decodes the raw key bytes.
    KES keys and opcert are generated at runtime from the cold key.
    """
    import json

    from vibe.cardano.node import PoolKeys

    def _read_key_bytes(path: str) -> bytes:
        """Read raw key bytes from a cardano-cli JSON key file."""
        with open(path) as f:
            data = json.load(f)
        cbor_hex = data["cborHex"]
        # Strip the 4-char CBOR wrapper prefix (e.g. "5820" for 32-byte keys)
        return bytes.fromhex(cbor_hex[4:])

    vrf_sk = _read_key_bytes(vrf_key_path)
    cold_sk = _read_key_bytes(cold_skey_path)

    cold_vk = b""
    if cold_vkey_path:
        cold_vk = _read_key_bytes(cold_vkey_path)

    vrf_vk = b""
    if vrf_vkey_path:
        vrf_vk = _read_key_bytes(vrf_vkey_path)

    return PoolKeys(
        cold_vk=cold_vk,
        cold_sk=cold_sk,
        vrf_sk=vrf_sk,
        vrf_vk=vrf_vk,
    )


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
            UNION ALL
            SELECT 'spec_sections', count(*) FROM spec_sections
            UNION ALL
            SELECT 'cross_references', count(*) FROM cross_references
            UNION ALL
            SELECT 'test_specifications', count(*) FROM test_specifications
            UNION ALL
            SELECT 'gap_analysis', count(*) FROM gap_analysis
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
        from vibe.tools.db.session import get_session
        from vibe.tools.embed.client import EmbeddingClient
        from vibe.tools.ingest.config import GITHUB_REPOS
        from vibe.tools.ingest.github import GitHubIngestor

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
        from vibe.tools.db.session import get_session
        from vibe.tools.embed.client import EmbeddingClient
        from vibe.tools.ingest.specs.pipeline import SpecIngestor

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
        from vibe.tools.db.session import get_session
        from vibe.tools.embed.client import EmbeddingClient
        from vibe.tools.ingest.code import CodeIngestor
        from vibe.tools.ingest.config import CODE_REPOS

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


@db_app.command(name="export-specs")
def export_specs_cmd() -> None:
    """Export pre-converted spec markdown to docs/specs/ organized by era.

    Reads era metadata from the database, then copies pre-converted markdown
    from data/specs/ to docs/specs/{era}/ with clean filenames and index pages.
    """
    from vibe.tools.export_specs import export_specs

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


# ===========================================================================
# Research commands
# ===========================================================================


@research_app.callback(invoke_without_command=True)
def research_callback(ctx: typer.Context):
    """Research and analysis commands."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


VALID_SUBSYSTEMS = [
    "networking", "miniprotocols-n2n", "miniprotocols-n2c", "consensus",
    "ledger", "plutus", "serialization", "mempool", "storage", "block-production",
]


@research_app.command(name="reset")
def research_reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    force: bool = typer.Option(False, "--force", "-f", help="Skip ALL confirmations."),
) -> None:
    """Clear all research pipeline output (spec_sections, cross_references, gaps, tests).

    Also resets the extraction_processed markers on spec_documents so
    the pipeline can re-run from scratch.

    THIS IS DESTRUCTIVE. Use --force in scripts.
    """
    import asyncio

    if not force:
        typer.echo("WARNING: This will DELETE all data from:")
        typer.echo("  - spec_sections")
        typer.echo("  - cross_references")
        typer.echo("  - gap_analysis")
        typer.echo("  - test_specifications")
        typer.echo("  - extraction_processed markers on spec_documents")
        typer.echo("")
        if not yes:
            if not typer.confirm("Are you sure?"):
                typer.echo("Aborted.")
                raise typer.Exit()

    async def _run():
        from vibe.tools.db.pool import get_pool, close_pool

        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM test_specifications")
            await conn.execute("DELETE FROM gap_analysis")
            await conn.execute("DELETE FROM cross_references")
            await conn.execute("DELETE FROM spec_sections")
            await conn.execute(
                "UPDATE spec_documents SET metadata = metadata - 'extraction_processed' "
                "WHERE metadata ? 'extraction_processed'"
            )
        await close_pool()
        typer.echo("Research data cleared. Ready for re-extraction.")

    asyncio.run(_run())


@research_app.command(name="extract-rules")
def extract_rules(
    subsystem: str = typer.Argument(
        help="Subsystem to extract rules for. Use 'all' for all subsystems. "
        "Valid values: all, "
        "networking, miniprotocols-n2n, miniprotocols-n2c, consensus, "
        "ledger, plutus, serialization, mempool, storage, block-production",
    ),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Max spec chunks to process per subsystem"),
    concurrency: int = typer.Option(3, "--concurrency", "-c", help="Number of chunks to process in parallel"),
) -> None:
    """Run the PydanticAI rule extraction and linking pipeline.

    Use 'all' to run for every subsystem sequentially.

    Extracts spec rules, finds implementing code and Haskell tests,
    detects spec-vs-code gaps, and proposes Hypothesis tests.

    Requires either AWS credentials (for Bedrock, default) or ANTHROPIC_API_KEY.
    Override models via EXTRACTION_MODEL and LINKING_MODEL env vars.
    """
    import asyncio

    subsystems = VALID_SUBSYSTEMS if subsystem == "all" else [subsystem]

    for s in subsystems:
        if s not in VALID_SUBSYSTEMS:
            typer.echo(
                f"Invalid subsystem: '{s}'\n"
                f"Valid options: all, {', '.join(VALID_SUBSYSTEMS)}",
                err=True,
            )
            raise typer.Exit(1)

    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

    async def _run():
        from vibe.tools.db.pool import get_pool, close_pool
        from vibe.tools.research.pipeline import run_pipeline

        total_stats = {
            "chunks_processed": 0, "rules_extracted": 0,
            "links_created": 0, "gaps_found": 0, "tests_proposed": 0,
        }

        for s in subsystems:
            pool = await get_pool()
            async with pool.acquire() as conn:
                typer.echo(f"\n{'='*60}")
                typer.echo(f"  Extracting rules for: {s}")
                typer.echo(f"{'='*60}")

                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TextColumn("{task.completed}/{task.total}"),
                    TimeElapsedColumn(),
                ) as progress:
                    task = progress.add_task(f"[green]{s}", total=0)
                    stats = await run_pipeline(conn, s, limit=limit, progress=progress, concurrency=concurrency)

            for key in total_stats:
                total_stats[key] += stats.get(key, 0)

            # Query per-subsystem totals
            pool2 = await get_pool()
            async with pool2.acquire() as conn2:
                db_stats = await conn2.fetchrow("""
                    SELECT
                        (SELECT COUNT(*) FROM spec_sections WHERE subsystem = $1) AS rules,
                        (SELECT COUNT(*) FROM cross_references cr
                         JOIN spec_sections ss ON cr.source_id = ss.id AND cr.source_type = 'spec_section'
                         WHERE ss.subsystem = $1) AS links,
                        (SELECT COUNT(*) FROM gap_analysis WHERE subsystem = $1) AS gaps,
                        (SELECT COUNT(*) FROM test_specifications WHERE subsystem = $1) AS tests
                """, s)

            typer.echo(f"\n  {s}: {db_stats['rules']} rules, {db_stats['links']} links, "
                       f"{db_stats['gaps']} gaps, {db_stats['tests']} tests")

        await close_pool()

        if len(subsystems) > 1:
            typer.echo(f"\n{'='*60}")
            typer.echo(f"  ALL SUBSYSTEMS COMPLETE")
            typer.echo(f"{'='*60}")
            typer.echo(f"  Chunks processed:  {total_stats['chunks_processed']}")
            typer.echo(f"  Rules extracted:   {total_stats['rules_extracted']}")
            typer.echo(f"  Links created:     {total_stats['links_created']}")
            typer.echo(f"  Gaps found:        {total_stats['gaps_found']}")
            typer.echo(f"  Tests proposed:    {total_stats['tests_proposed']}")

    asyncio.run(_run())


@research_app.command(name="qa-validate")
def qa_validate(
    subsystem: str = typer.Argument(
        help="Subsystem to validate. Use 'all' for all subsystems. "
        "Valid values: all, "
        "networking, miniprotocols-n2n, miniprotocols-n2c, consensus, "
        "ledger, plutus, serialization, mempool, storage, block-production",
    ),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Max entries to validate per subsystem"),
    concurrency: int = typer.Option(5, "--concurrency", "-c", help="Parallel validations"),
    gaps_only: bool = typer.Option(False, "--gaps-only", help="Only validate gaps, skip xref checks"),
    xrefs_only: bool = typer.Option(False, "--xrefs-only", help="Only validate cross-references, skip gaps"),
) -> None:
    """QA validation of extracted rules, gaps, and cross-references.

    Use 'all' to validate every subsystem sequentially.

    Validates pipeline output by:
    - Searching vendor repos (git grep) to verify "missing implementation" gaps
    - Categorizing gaps (perf optimization, post-spec addition, genuine violation, etc.)
    - Assessing severity (critical, important, informational, false positive)
    - Spot-checking cross-reference accuracy

    Requires AWS credentials (Bedrock) or ANTHROPIC_API_KEY.
    Override model via QA_MODEL env var.
    """
    import asyncio

    subsystems = VALID_SUBSYSTEMS if subsystem == "all" else [subsystem]

    for s in subsystems:
        if s not in VALID_SUBSYSTEMS:
            typer.echo(
                f"Invalid subsystem: '{s}'\n"
                f"Valid options: all, {', '.join(VALID_SUBSYSTEMS)}",
                err=True,
            )
            raise typer.Exit(1)

    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

    async def _run():
        from vibe.tools.db.pool import get_pool, close_pool
        from vibe.tools.research.qa_validate import validate_gaps, validate_xrefs

        pool = await get_pool()

        for s in subsystems:
            if len(subsystems) > 1:
                typer.echo(f"\n{'='*60}")
                typer.echo(f"  QA Validating: {s}")
                typer.echo(f"{'='*60}")

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
            ) as progress:
                if not xrefs_only:
                    gap_task = progress.add_task(f"[green]{s} gaps", total=0)
                    gap_stats = await validate_gaps(
                        pool, s, limit=limit,
                        concurrency=concurrency, progress=progress, task_id=gap_task,
                    )
                    typer.echo(f"\n=== Gap Validation ({s}) ===")
                    typer.echo(f"  Validated:          {gap_stats['gaps_validated']}")
                    typer.echo(f"  Search failures:    {gap_stats['search_failures_resolved']}")
                    typer.echo(f"  False positives:    {gap_stats['false_positives']}")
                    typer.echo(f"  Critical:           {gap_stats['critical']}")
                    typer.echo(f"  Important:          {gap_stats['important']}")
                    typer.echo(f"  Informational:      {gap_stats['informational']}")

                if not gaps_only:
                    xref_task = progress.add_task(f"[blue]{s} xrefs", total=0)
                    xref_stats = await validate_xrefs(
                        pool, s, limit=limit,
                        concurrency=concurrency, progress=progress, task_id=xref_task,
                    )
                    typer.echo(f"\n=== Cross-Reference Validation ({s}) ===")
                    typer.echo(f"  Checked:            {xref_stats['checked']}")
                    typer.echo(f"  Accurate:           {xref_stats['accurate']}")
                    typer.echo(f"  Inaccurate:         {xref_stats['inaccurate']}")

        await close_pool()

    asyncio.run(_run())


# ===========================================================================
# Eval commands
# ===========================================================================


@eval_app.callback(invoke_without_command=True)
def eval_callback(ctx: typer.Context):
    """Evaluation and benchmarking commands."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@eval_app.command(name="pycardano")
def eval_pycardano(
    ogmios_url: str = typer.Option(
        "ws://localhost:1337",
        "--ogmios-url", "-u",
        help="Ogmios WebSocket URL.",
    ),
) -> None:
    """Evaluate pycardano block deserialization coverage per era.

    Connects to the Docker Compose Ogmios instance, fetches one block
    from each Cardano era (Byron through Conway), attempts to deserialize
    with pycardano, and reports field-level coverage.

    Requires: docker compose up cardano-node ogmios
    """
    import asyncio

    from vibe.cardano.serialization.eval_pycardano import run_evaluation, print_results

    typer.echo("pycardano Deserialization Coverage Evaluation")
    typer.echo(f"Ogmios: {ogmios_url}")
    typer.echo("")

    results = asyncio.run(run_evaluation(ogmios_url))
    print_results(results)
