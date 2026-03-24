"""Inbound connection handlers for N2N and N2C servers.

Handles incoming TCP (N2N) and Unix socket (N2C) connections:
- Multiplexer setup with appropriate miniprotocol bundles
- Handshake responder
- Miniprotocol server launch (chain-sync, block-fetch, keep-alive, etc.)

Haskell references:
    - Ouroboros.Network.Server2.run -- inbound connection manager
    - Ouroboros.Network.Snocket.localSnocket -- Unix socket connections
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from vibe.cardano.network.blockfetch import BLOCK_FETCH_N2N_ID
from vibe.cardano.network.chainsync import CHAIN_SYNC_N2C_ID, CHAIN_SYNC_N2N_ID
from vibe.cardano.network.handshake import HANDSHAKE_PROTOCOL_ID
from vibe.cardano.network.keepalive import KEEP_ALIVE_PROTOCOL_ID
from vibe.cardano.network.local_statequery import LOCAL_STATE_QUERY_PROTOCOL_ID
from vibe.cardano.network.local_txmonitor import LOCAL_TX_MONITOR_ID
from vibe.cardano.network.local_txsubmission import LOCAL_TX_SUBMISSION_ID
from vibe.cardano.network.txsubmission import TX_SUBMISSION_N2N_ID
from vibe.core.multiplexer import (
    Bearer,
    BearerClosedError,
    MiniProtocolChannel,
    Multiplexer,
    MuxClosedError,
)

__all__ = [
    "N2N_PROTOCOL_IDS",
    "N2C_PROTOCOL_IDS",
    "setup_n2n_mux",
    "setup_n2c_mux",
    "run_n2n_server",
    "run_n2c_server",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Miniprotocol ID constants -- collected here for the bundle builders
# ---------------------------------------------------------------------------

# N2N miniprotocol IDs (from the individual codec modules):
#   0 = Handshake
#   2 = Chain-Sync (N2N)
#   3 = Block-Fetch
#   4 = Tx-Submission (N2N)
#   8 = Keep-Alive
N2N_PROTOCOL_IDS: list[int] = [
    HANDSHAKE_PROTOCOL_ID,  # 0
    CHAIN_SYNC_N2N_ID,  # 2
    BLOCK_FETCH_N2N_ID,  # 3
    TX_SUBMISSION_N2N_ID,  # 4
    KEEP_ALIVE_PROTOCOL_ID,  # 8
]

# N2C miniprotocol IDs:
#   0 = Handshake
#   5 = Local Chain-Sync (N2C)
#   6 = Local Tx-Submission
#   7 = Local State-Query
#   9 = Local Tx-Monitor
N2C_PROTOCOL_IDS: list[int] = [
    HANDSHAKE_PROTOCOL_ID,  # 0
    CHAIN_SYNC_N2C_ID,  # 5
    LOCAL_TX_SUBMISSION_ID,  # 6
    LOCAL_STATE_QUERY_PROTOCOL_ID,  # 7
    LOCAL_TX_MONITOR_ID,  # 9
]


def setup_n2n_mux(bearer: Bearer, is_initiator: bool) -> Multiplexer:
    """Create a Multiplexer with the N2N miniprotocol bundle registered.

    Args:
        bearer: The TCP bearer for this connection.
        is_initiator: True if we initiated the connection.

    Returns:
        A configured Multiplexer ready to run().
    """
    mux = Multiplexer(bearer, is_initiator=is_initiator)
    for proto_id in N2N_PROTOCOL_IDS:
        mux.add_protocol(proto_id)
    return mux


def setup_n2c_mux(bearer: Bearer) -> Multiplexer:
    """Create a Multiplexer with the N2C miniprotocol bundle registered.

    N2C connections are always responder-side (we are the node, the
    client connects to us via Unix socket).

    Args:
        bearer: The Unix socket bearer for this connection.

    Returns:
        A configured Multiplexer ready to run().
    """
    mux = Multiplexer(bearer, is_initiator=False)
    for proto_id in N2C_PROTOCOL_IDS:
        mux.add_protocol(proto_id)
    return mux


async def run_n2n_server(
    host: str,
    port: int,
    network_magic: int,
    node_kernel: Any,
    mempool: Any,
    shutdown_event: asyncio.Event,
    chain_db: Any = None,
) -> None:
    """Run the TCP listener for inbound N2N peer connections.

    For each incoming connection:
    1. Wrap in a Bearer + Multiplexer
    2. Run handshake responder on channel 0
    3. Launch chain-sync server, keep-alive server, block-fetch server
    4. Run until disconnect or shutdown

    Haskell ref:
        ``Ouroboros.Network.Server2.run`` -- the server side of the
        connection manager that accepts inbound connections.

    Args:
        host: Bind address.
        port: Bind port.
        network_magic: Network magic for handshake negotiation.
        shutdown_event: Set when the node is shutting down.
    """
    from vibe.cardano.network.blockfetch_protocol import run_block_fetch_server
    from vibe.cardano.network.chainsync_protocol import run_chain_sync_server
    from vibe.cardano.network.handshake_protocol import (
        HandshakeError,
        run_handshake_server,
    )
    from vibe.cardano.network.keepalive_protocol import run_keep_alive_server

    conn_tasks: list[asyncio.Task[None]] = []

    async def handle_connection(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer_info = writer.get_extra_info("peername")
        logger.info(
            "Peer %s connected (inbound)",
            peer_info,
            extra={"event": "peer.inbound", "peer": str(peer_info)},
        )

        bearer = Bearer(reader, writer)
        mux = Multiplexer(bearer, is_initiator=False)

        # Register N2N miniprotocol channels.
        channels: dict[int, MiniProtocolChannel] = {}
        for proto_id in N2N_PROTOCOL_IDS:
            channels[proto_id] = mux.add_protocol(proto_id)

        # Start the mux in background.
        mux_task = asyncio.create_task(mux.run(), name=f"mux-inbound-{peer_info}")
        stop = asyncio.Event()
        follower = None

        try:
            # Run handshake responder on channel 0.
            hs_channel = channels[HANDSHAKE_PROTOCOL_ID]
            result = await run_handshake_server(hs_channel, network_magic)
            logger.info(
                "Peer %s handshake accepted (inbound, v%d)",
                peer_info,
                result.version_number,
                extra={
                    "event": "peer.handshake",
                    "peer": str(peer_info),
                    "direction": "inbound",
                    "version": result.version_number,
                },
            )

            # Helper: wrap server coroutines so MuxClosedError on
            # peer disconnect doesn't produce "Task exception never retrieved"
            async def _safe_server(coro, name: str) -> None:
                try:
                    await coro
                except MuxClosedError, BearerClosedError:
                    logger.debug("N2N inbound %s: %s disconnected", peer_info, name)
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    logger.debug("N2N inbound %s: %s error: %s", peer_info, name, exc)

            # Launch keep-alive server (echo pings back).
            asyncio.create_task(
                _safe_server(
                    run_keep_alive_server(
                        channels[KEEP_ALIVE_PROTOCOL_ID],
                        stop_event=stop,
                    ),
                    "keep-alive",
                ),
                name=f"ka-server-{peer_info}",
            )

            # Launch chain-sync server (serve our headers to the peer).
            # Follower comes from ChainDB (source of truth for selected chain).
            if chain_db is not None:
                follower = chain_db.new_follower()
                asyncio.create_task(
                    _safe_server(
                        run_chain_sync_server(
                            channels[CHAIN_SYNC_N2N_ID],
                            follower=follower,
                            stop_event=stop,
                        ),
                        "chain-sync",
                    ),
                    name=f"cs-server-{peer_info}",
                )

            # Launch block-fetch server (serve full blocks to the peer).
            # Uses chain_db for block lookups (volatile + immutable).
            if chain_db is not None:
                asyncio.create_task(
                    _safe_server(
                        run_block_fetch_server(
                            channels[BLOCK_FETCH_N2N_ID],
                            block_provider=chain_db,
                            stop_event=stop,
                        ),
                        "block-fetch",
                    ),
                    name=f"bf-server-{peer_info}",
                )

            # Launch tx-submission server (pull txs from peer into mempool).
            if mempool is not None:
                from vibe.cardano.network.txsubmission_protocol import (
                    run_tx_submission_server,
                )

                async def _on_tx_ids(txids: list[tuple[bytes, int]]) -> None:
                    logger.debug(
                        "N2N inbound %s: received %d tx IDs",
                        peer_info,
                        len(txids),
                    )

                async def _on_txs(txs: list[bytes]) -> None:
                    for tx_cbor in txs:
                        try:
                            await mempool.add_tx(tx_cbor)
                            logger.debug(
                                "N2N inbound %s: added tx to mempool (%d bytes)",
                                peer_info,
                                len(tx_cbor),
                            )
                        except Exception as exc:
                            logger.debug(
                                "N2N inbound %s: tx rejected: %s",
                                peer_info,
                                exc,
                            )

                asyncio.create_task(
                    _safe_server(
                        run_tx_submission_server(
                            channels[TX_SUBMISSION_N2N_ID],
                            on_tx_ids_received=_on_tx_ids,
                            on_txs_received=_on_txs,
                            stop_event=stop,
                        ),
                        "tx-submission",
                    ),
                    name=f"txsub-server-{peer_info}",
                )

            # Wait for mux to end (peer disconnect) or shutdown.
            done, _ = await asyncio.wait(
                [mux_task, asyncio.create_task(shutdown_event.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )

        except (HandshakeError, ConnectionError, MuxClosedError) as exc:
            logger.debug("N2N inbound %s: %s", peer_info, exc)
        except Exception as exc:
            logger.debug("N2N inbound %s ended: %s", peer_info, exc)
        finally:
            stop.set()
            if follower is not None and chain_db is not None:
                chain_db.close_follower(follower.id)
            await mux.close()
            if not mux_task.done():
                mux_task.cancel()
                try:
                    await mux_task
                except asyncio.CancelledError, Exception:
                    pass

    try:
        server = await asyncio.start_server(handle_connection, host, port)
        addrs = [s.getsockname() for s in server.sockets]
        logger.info(
            "N2N server listening on %s",
            addrs,
            extra={"event": "server.n2n.listening", "addresses": str(addrs)},
        )

        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        if "server" in locals():
            server.close()
            await server.wait_closed()
        for task in conn_tasks:
            if not task.done():
                task.cancel()


async def run_n2c_server(
    socket_path: str,
    network_magic: int,
    chain_db: Any,
    ledger_db: Any,
    mempool: Any,
    shutdown_event: asyncio.Event,
) -> None:
    """Run the Unix socket listener for N2C local client connections.

    For each incoming connection:
    1. Wrap in a Bearer + Multiplexer
    2. Run N2C handshake responder on channel 0
    3. Launch all 4 N2C miniprotocol servers on their channels
    4. Run until disconnect or shutdown

    Haskell ref:
        ``Ouroboros.Network.Snocket.localSnocket`` -- the local (Unix
        socket) snocket used for node-to-client connections.

    Args:
        socket_path: Path to the Unix domain socket.
        network_magic: Network magic for handshake negotiation.
        chain_db: The ChainDB instance (for local chain-sync).
        ledger_db: The LedgerDB instance (for local state-query).
        shutdown_event: Set when the node is shutting down.
    """
    from vibe.cardano.network.handshake_protocol import (
        HandshakeError,
        run_handshake_server_n2c,
    )
    from vibe.cardano.network.local_chainsync_protocol import create_local_chainsync_server
    from vibe.cardano.network.local_statequery_protocol import run_local_state_query_server
    from vibe.cardano.network.local_txmonitor_protocol import run_local_tx_monitor_server
    from vibe.cardano.network.local_txsubmission_protocol import run_local_tx_submission_server

    conn_tasks: list[asyncio.Task[None]] = []

    async def handle_connection(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        logger.info(
            "N2C client connected via %s",
            socket_path,
            extra={"event": "n2c.connected", "socket": socket_path},
        )

        bearer = Bearer(reader, writer)
        mux = Multiplexer(bearer, is_initiator=False)

        # Register N2C miniprotocol channels.
        channels: dict[int, MiniProtocolChannel] = {}
        for proto_id in N2C_PROTOCOL_IDS:
            channels[proto_id] = mux.add_protocol(proto_id)

        # Start the mux in background.
        mux_task = asyncio.create_task(mux.run(), name="mux-n2c")
        stop = asyncio.Event()

        try:
            # Run N2C handshake responder on channel 0.
            hs_channel = channels[HANDSHAKE_PROTOCOL_ID]
            hs_result = await run_handshake_server_n2c(hs_channel, network_magic)
            logger.info(
                "N2C handshake accepted (v%d, query=%s)",
                hs_result.version_number,
                hs_result.version_data.query,
                extra={
                    "event": "n2c.handshake",
                    "version": hs_result.version_number,
                    "query": hs_result.version_data.query,
                },
            )

            # Launch local chain-sync server (protocol 5).
            if chain_db is not None:
                cs_server = create_local_chainsync_server(
                    channels[CHAIN_SYNC_N2C_ID],
                    chain_db,
                )
                asyncio.create_task(
                    cs_server.run(),
                    name="n2c-local-chainsync",
                )
            else:
                logger.warning("N2C local chain-sync: skipped (no ChainDB available)")

            # Launch local tx-submission server (protocol 6).
            async def _validate_and_add_tx(era_id: int, tx_bytes: bytes) -> bytes | None:
                if mempool is not None:
                    try:
                        await mempool.add_tx(tx_bytes)
                        return None  # None = accepted
                    except Exception as exc:
                        return str(exc).encode()  # Error bytes = rejected
                return b"mempool not available"

            asyncio.create_task(
                run_local_tx_submission_server(
                    channels[LOCAL_TX_SUBMISSION_ID],
                    validate_tx=_validate_and_add_tx,
                ),
                name="n2c-local-txsubmission",
            )

            # Launch local state-query server (protocol 7).
            if ledger_db is not None:
                asyncio.create_task(
                    run_local_state_query_server(
                        channels[LOCAL_STATE_QUERY_PROTOCOL_ID],
                        ledgerdb=ledger_db,
                    ),
                    name="n2c-local-statequery",
                )
            else:
                logger.warning("N2C local state-query: skipped (no LedgerDB available)")

            # Launch local tx-monitor server (protocol 9).
            _monitor_snapshot = None
            _monitor_idx = 0

            async def _acquire_snapshot() -> int:
                nonlocal _monitor_snapshot, _monitor_idx
                if mempool is not None:
                    _monitor_snapshot = await mempool.get_snapshot()
                    _monitor_idx = 0
                    return _monitor_snapshot.slot if _monitor_snapshot else 0
                return 0

            async def _get_next_tx() -> tuple[int, bytes] | None:
                nonlocal _monitor_idx
                if _monitor_snapshot and _monitor_idx < len(_monitor_snapshot.tickets):
                    ticket = _monitor_snapshot.tickets[_monitor_idx]
                    _monitor_idx += 1
                    return (ticket.validated_tx.tx_size, ticket.validated_tx.tx_cbor)
                return None

            async def _has_tx(tx_id: bytes) -> bool:
                if mempool is not None:
                    return await mempool.has_tx(tx_id)
                return False

            async def _mempool_sizes() -> tuple[int, int, int]:
                if mempool is not None:
                    return (mempool.size, mempool.total_size_bytes, mempool.capacity_bytes)
                return (0, 0, 0)

            asyncio.create_task(
                run_local_tx_monitor_server(
                    channels[LOCAL_TX_MONITOR_ID],
                    acquire_snapshot=_acquire_snapshot,
                    get_next_tx=_get_next_tx,
                    has_tx_in_snapshot=_has_tx,
                    get_mempool_sizes=_mempool_sizes,
                ),
                name="n2c-local-txmonitor",
            )

            # Wait for mux to end (client disconnect) or shutdown.
            done, _ = await asyncio.wait(
                [mux_task, asyncio.create_task(shutdown_event.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )

        except (HandshakeError, ConnectionError, MuxClosedError) as exc:
            logger.debug("N2C connection ended: %s", exc)
        except Exception as exc:
            logger.debug("N2C connection ended: %s", exc)
        finally:
            stop.set()
            await mux.close()
            if not mux_task.done():
                mux_task.cancel()
                try:
                    await mux_task
                except asyncio.CancelledError, Exception:
                    pass

    try:
        server = await asyncio.start_unix_server(handle_connection, socket_path)
        logger.info(
            "N2C server listening on %s",
            socket_path,
            extra={"event": "server.n2c.listening", "socket": socket_path},
        )

        await shutdown_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        if "server" in locals():
            server.close()
            await server.wait_closed()
        for task in conn_tasks:
            if not task.done():
                task.cancel()
