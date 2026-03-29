"""Shared miniprotocol bundle launchers for N2N connections.

Extracts the common pattern of launching responder-side and initiator-side
miniprotocol tasks into reusable functions.  Both inbound_server.py (Task 3)
and peer_manager.py (Task 4) call these instead of duplicating the setup.

Haskell reference:
    Ouroboros.Network.NodeToNode -- miniprotocol bundle definition
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

__all__ = [
    "launch_responder_bundle",
    "launch_initiator_bundle",
]

logger = logging.getLogger(__name__)


async def launch_responder_bundle(
    channels: dict[int, Any],
    chain_db: Any,
    mempool: Any,
    stop_event: asyncio.Event,
    peer_info: str = "",
) -> list[asyncio.Task[None]]:
    """Start responder-side miniprotocol tasks for an N2N connection.

    Launches keep-alive server, chain-sync server, block-fetch server,
    and tx-submission server on the appropriate channels.  Each is wrapped
    in ``_safe()`` so that peer disconnects don't produce noisy tracebacks.

    Args:
        channels: ``dict[int, MiniProtocolChannel]`` mapping protocol_id to channel.
        chain_db: ChainDB instance (or None to skip chain-sync / block-fetch).
        mempool: Mempool instance (or None to skip tx-submission).
        stop_event: Signalled on connection teardown.
        peer_info: Human-readable peer identifier for log messages.

    Returns:
        List of created ``asyncio.Task`` objects.
    """
    # Lazy imports to avoid circular dependencies.
    from vibe.cardano.network.blockfetch import BLOCK_FETCH_N2N_ID
    from vibe.cardano.network.blockfetch_protocol import run_block_fetch_server
    from vibe.cardano.network.chainsync import CHAIN_SYNC_N2N_ID
    from vibe.cardano.network.chainsync_protocol import run_chain_sync_server
    from vibe.cardano.network.keepalive import KEEP_ALIVE_PROTOCOL_ID
    from vibe.cardano.network.keepalive_protocol import run_keep_alive_server
    from vibe.cardano.network.txsubmission import TX_SUBMISSION_N2N_ID
    from vibe.cardano.network.txsubmission_protocol import run_tx_submission_server
    from vibe.core.multiplexer import BearerClosedError, MuxClosedError

    async def _safe(coro: Any, name: str) -> None:
        """Run *coro*, silencing expected disconnect errors."""
        try:
            await coro
        except (MuxClosedError, BearerClosedError):
            logger.debug("Responder %s: %s channel closed", peer_info, name)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("Responder %s: %s error: %s", peer_info, name, exc)

    tasks: list[asyncio.Task[None]] = []

    # Keep-alive server (echo pings back).
    tasks.append(
        asyncio.create_task(
            _safe(
                run_keep_alive_server(
                    channels[KEEP_ALIVE_PROTOCOL_ID],
                    stop_event=stop_event,
                ),
                "keep-alive",
            ),
            name=f"ka-server-{peer_info}",
        )
    )

    # Chain-sync server (serve our headers to the peer).
    # Follower is cleaned up when the server exits to prevent
    # accumulation — each fork switch notifies ALL followers.
    if chain_db is not None:
        follower = chain_db.new_follower()

        async def _chain_sync_with_cleanup() -> None:
            try:
                await run_chain_sync_server(
                    channels[CHAIN_SYNC_N2N_ID],
                    follower=follower,
                    stop_event=stop_event,
                )
            finally:
                chain_db.close_follower(follower.id)
                logger.debug("Closed follower %d for %s", follower.id, peer_info)

        tasks.append(
            asyncio.create_task(
                _safe(_chain_sync_with_cleanup(), "chain-sync"),
                name=f"cs-server-{peer_info}",
            )
        )

    # Block-fetch server (serve full blocks to the peer).
    if chain_db is not None:
        tasks.append(
            asyncio.create_task(
                _safe(
                    run_block_fetch_server(
                        channels[BLOCK_FETCH_N2N_ID],
                        block_provider=chain_db,
                        stop_event=stop_event,
                    ),
                    "block-fetch",
                ),
                name=f"bf-server-{peer_info}",
            )
        )

    # Tx-submission server (pull txs from peer into mempool).
    if mempool is not None:

        async def _on_tx_ids(txids: list[tuple[bytes, int]]) -> None:
            logger.debug(
                "Responder %s: received %d tx IDs", peer_info, len(txids)
            )

        async def _on_txs(txs: list[bytes]) -> None:
            for tx_cbor in txs:
                try:
                    await mempool.add_tx(tx_cbor)
                    logger.debug(
                        "Responder %s: added tx to mempool (%d bytes)",
                        peer_info,
                        len(tx_cbor),
                    )
                except Exception as exc:
                    logger.debug(
                        "Responder %s: tx rejected: %s", peer_info, exc
                    )

        tasks.append(
            asyncio.create_task(
                _safe(
                    run_tx_submission_server(
                        channels[TX_SUBMISSION_N2N_ID],
                        on_tx_ids_received=_on_tx_ids,
                        on_txs_received=_on_txs,
                        stop_event=stop_event,
                    ),
                    "tx-submission",
                ),
                name=f"txsub-server-{peer_info}",
            )
        )

    return tasks


async def launch_initiator_bundle(
    channels: dict[int, Any],
    stop_event: asyncio.Event,
    peer_info: str = "",
) -> list[asyncio.Task[None]]:
    """Start initiator-side miniprotocol tasks for an N2N connection.

    Launches keep-alive client and tx-submission client.  Chain-sync client
    and block-fetch client are NOT started here -- those are managed by
    ``peer_manager`` with specific fetch queues.

    Args:
        channels: ``dict[int, MiniProtocolChannel]`` mapping protocol_id to channel.
        stop_event: Signalled on connection teardown.
        peer_info: Human-readable peer identifier for log messages.

    Returns:
        List of created ``asyncio.Task`` objects.
    """
    # Lazy imports to avoid circular dependencies.
    from vibe.cardano.network.keepalive import KEEP_ALIVE_PROTOCOL_ID
    from vibe.cardano.network.keepalive_protocol import run_keep_alive_client
    from vibe.cardano.network.txsubmission import TX_SUBMISSION_N2N_ID
    from vibe.cardano.network.txsubmission_protocol import run_tx_submission_client
    from vibe.core.multiplexer import BearerClosedError, MuxClosedError

    async def _safe(coro: Any, name: str) -> None:
        """Run *coro*, silencing expected disconnect errors."""
        try:
            await coro
        except (MuxClosedError, BearerClosedError):
            logger.debug("Initiator %s: %s channel closed", peer_info, name)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("Initiator %s: %s error: %s", peer_info, name, exc)

    tasks: list[asyncio.Task[None]] = []

    # Keep-alive client (send periodic pings).
    tasks.append(
        asyncio.create_task(
            _safe(
                run_keep_alive_client(
                    channels[KEEP_ALIVE_PROTOCOL_ID],
                    stop_event=stop_event,
                    interval=10.0,
                    peer_info=peer_info,
                ),
                "keep-alive",
            ),
            name=f"ka-client-{peer_info}",
        )
    )

    # Tx-submission client (respond to server's pull requests).
    # Stub callbacks that return empty lists until mempool forwarding is wired.
    async def _on_request_tx_ids(
        blocking: bool, ack_count: int, req_count: int
    ) -> list[tuple[bytes, int]] | None:
        if blocking:
            # Block until stop -- we have nothing to offer yet.
            await stop_event.wait()
            return None
        return []

    async def _on_request_txs(txids: list[bytes]) -> list[bytes]:
        return []

    tasks.append(
        asyncio.create_task(
            _safe(
                run_tx_submission_client(
                    channels[TX_SUBMISSION_N2N_ID],
                    on_request_tx_ids=_on_request_tx_ids,
                    on_request_txs=_on_request_txs,
                    stop_event=stop_event,
                ),
                "tx-submission",
            ),
            name=f"txsub-client-{peer_info}",
        )
    )

    return tasks
