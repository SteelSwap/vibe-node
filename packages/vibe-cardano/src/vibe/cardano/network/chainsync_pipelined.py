"""Pipelined chain-sync client — dramatically faster chain synchronization.

The standard chain-sync client sends one MsgRequestNext, waits for the
response (MsgRollForward/MsgRollBackward/MsgAwaitReply), processes it,
then sends the next request. With a round-trip time of ~50ms to a remote
peer, this caps throughput at ~20 headers/second.

The pipelined client sends up to max_in_flight MsgRequestNext messages
without waiting for responses, then collects responses asynchronously.
With max_in_flight=300, we can have 300 headers in the pipeline at once,
turning a latency-bound protocol into a throughput-bound one.

Key design decision: rollback handling.
    When a MsgRollBackward arrives, all subsequent in-flight responses are
    invalid — they reference chain state that no longer exists. The pipeline
    must be drained (all pending responses collected and discarded), the
    rollback processed, and then new requests sent from the correct point.

    This matches the Haskell implementation:
    Ouroboros.Network.Protocol.ChainSync.ClientPipelined
        - ChainSyncClientPipelined uses PipelineDecision to manage depth
        - On rollback, the receiver drains the pipeline before yielding

Haskell reference:
    Ouroboros/Network/Protocol/ChainSync/ClientPipelined.hs
    The Haskell client uses a pipelined peer with Collect/Pipeline/CollectDone
    constructors. Our version is imperative but achieves the same flow:
    pipeline requests, collect responses, handle rollbacks by draining.

Spec reference:
    Ouroboros network spec, Section 3.2 "Chain Sync Mini-Protocol"
    combined with Section 2.3 "Pipelining"
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable

from vibe.core.protocols.pipelining import PipelinedRunner
from vibe.core.protocols.agency import PeerRole

from vibe.cardano.network.chainsync import (
    PointOrOrigin,
    Tip,
    ORIGIN,
)
from vibe.cardano.network.chainsync_protocol import (
    ChainSyncProtocol,
    ChainSyncCodec,
    CsMsgRequestNext,
    CsMsgRollForward,
    CsMsgRollBackward,
    CsMsgAwaitReply,
    CsMsgFindIntersect,
    CsMsgIntersectFound,
    CsMsgIntersectNotFound,
    CsMsgDone,
)
from vibe.core.protocols.runner import ProtocolRunner
from vibe.core.protocols.agency import ProtocolError

__all__ = [
    "PipelinedChainSyncClient",
    "run_pipelined_chain_sync",
]

logger = logging.getLogger(__name__)

#: Type alias for roll-forward callback.
OnRollForward = Callable[[bytes, Tip], Awaitable[None]]

#: Type alias for roll-backward callback.
OnRollBackward = Callable[[PointOrOrigin, Tip], Awaitable[None]]


class PipelinedChainSyncClient:
    """Pipelined chain-sync client for high-throughput synchronization.

    Sends multiple MsgRequestNext messages without waiting for responses,
    then collects responses asynchronously. Handles rollbacks by draining
    the pipeline and restarting from the rollback point.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for chain-sync.
    max_in_flight : int
        Maximum number of pipelined MsgRequestNext messages. Higher values
        increase throughput but use more memory for buffered responses.
        Default: 300 (matches typical Haskell node configuration).
    """

    __slots__ = ("_channel", "_max_in_flight", "_codec", "_protocol")

    def __init__(
        self,
        channel: Any,
        max_in_flight: int = 300,
    ) -> None:
        self._channel = channel
        self._max_in_flight = max_in_flight
        self._codec = ChainSyncCodec()
        self._protocol = ChainSyncProtocol()

    async def find_intersection(
        self, points: list[PointOrOrigin]
    ) -> tuple[PointOrOrigin | None, Tip]:
        """Find the intersection point with the server (non-pipelined).

        Intersection finding is always sequential — we need the result
        before we can start pipelining. This uses a standard ProtocolRunner
        for the handshake phase.

        Parameters
        ----------
        points : list[PointOrOrigin]
            Candidate intersection points, highest slot first.

        Returns
        -------
        tuple[PointOrOrigin | None, Tip]
            The intersection point (or None if not found) and server tip.
        """
        # Use the channel directly for the intersection phase.
        # Send FindIntersect and wait for response.
        msg = CsMsgFindIntersect(points)
        data = self._codec.encode(msg)
        await self._channel.send(data)

        resp_data = await self._channel.recv()
        response = self._codec.decode(resp_data)

        if isinstance(response, CsMsgIntersectFound):
            return (response.point, response.tip)
        elif isinstance(response, CsMsgIntersectNotFound):
            return (None, response.tip)
        else:
            raise ProtocolError(
                f"Unexpected response to FindIntersect: "
                f"{type(response).__name__}"
            )

    async def run_pipelined_sync(
        self,
        on_roll_forward: OnRollForward,
        on_roll_backward: OnRollBackward,
        *,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Run the pipelined sync loop.

        Sends MsgRequestNext in batches up to max_in_flight, collects
        responses, and dispatches to callbacks. On rollback, drains the
        pipeline before processing the rollback.

        Parameters
        ----------
        on_roll_forward : OnRollForward
            Async callback for each roll-forward (header, tip).
        on_roll_backward : OnRollBackward
            Async callback for each roll-backward (point, tip).
        stop_event : asyncio.Event | None
            If set, the sync loop exits gracefully.
        """
        pipeline = PipelinedRunner(
            channel=self._channel,
            codec=self._codec,
            max_in_flight=self._max_in_flight,
        )

        async with pipeline:
            # Sender task: continuously pipelines MsgRequestNext.
            sender_task = asyncio.create_task(
                self._sender_loop(pipeline, stop_event),
                name="chainsync-pipelined-sender",
            )

            try:
                await self._collector_loop(
                    pipeline, on_roll_forward, on_roll_backward, stop_event
                )
            finally:
                sender_task.cancel()
                try:
                    await sender_task
                except asyncio.CancelledError:
                    pass

    async def _sender_loop(
        self,
        pipeline: PipelinedRunner,
        stop_event: asyncio.Event | None,
    ) -> None:
        """Continuously send MsgRequestNext into the pipeline.

        Runs until cancelled or stop_event is set. The pipeline's
        backpressure (semaphore) automatically throttles sending when
        max_in_flight is reached.
        """
        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    return

                msg = CsMsgRequestNext()
                await pipeline.send_request(msg)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.error("Pipelined chain-sync sender error: %s", exc)
            raise

    async def _collector_loop(
        self,
        pipeline: PipelinedRunner,
        on_roll_forward: OnRollForward,
        on_roll_backward: OnRollBackward,
        stop_event: asyncio.Event | None,
    ) -> None:
        """Collect responses from the pipeline and dispatch to callbacks.

        On rollback: drain all in-flight responses, then process the
        rollback. The sender will automatically resume filling the
        pipeline from the new chain tip.
        """
        while True:
            if stop_event is not None and stop_event.is_set():
                # Drain any remaining queued responses before exiting.
                while not pipeline._response_queue.empty():
                    try:
                        response = pipeline._response_queue.get_nowait()
                        if isinstance(response, Exception):
                            break
                        pipeline._in_flight -= 1
                        pipeline._semaphore.release()
                        if isinstance(response, CsMsgRollForward):
                            await on_roll_forward(response.header, response.tip)
                        elif isinstance(response, CsMsgRollBackward):
                            await on_roll_backward(response.point, response.tip)
                    except asyncio.QueueEmpty:
                        break
                logger.info("Pipelined chain-sync: stop requested, drained remaining")
                return

            # Use a short timeout so we can check stop_event periodically.
            try:
                response = await asyncio.wait_for(
                    pipeline.collect_response(), timeout=0.05
                )
            except asyncio.TimeoutError:
                continue

            if isinstance(response, CsMsgRollForward):
                await on_roll_forward(response.header, response.tip)

            elif isinstance(response, CsMsgRollBackward):
                # Drain the pipeline — all subsequent in-flight responses
                # reference chain state that no longer exists.
                drained = await pipeline.drain()
                logger.info(
                    "Pipelined chain-sync: rollback to %s, "
                    "drained %d in-flight responses",
                    response.point,
                    len(drained),
                )
                await on_roll_backward(response.point, response.tip)

            elif isinstance(response, CsMsgAwaitReply):
                # At tip — server has no new blocks. The next response
                # from the pipeline will be the actual RollForward/RollBackward
                # once the server has new data. We just continue collecting.
                logger.debug(
                    "Pipelined chain-sync: at tip, awaiting new block"
                )
                # Collect the follow-up response (MustReply — no more AwaitReply).
                follow_up = await pipeline.collect_response()
                if isinstance(follow_up, CsMsgRollForward):
                    await on_roll_forward(follow_up.header, follow_up.tip)
                elif isinstance(follow_up, CsMsgRollBackward):
                    drained = await pipeline.drain()
                    logger.info(
                        "Pipelined chain-sync: rollback after await, "
                        "drained %d in-flight",
                        len(drained),
                    )
                    await on_roll_backward(follow_up.point, follow_up.tip)

            else:
                raise ProtocolError(
                    f"Unexpected pipelined chain-sync response: "
                    f"{type(response).__name__}"
                )


async def run_pipelined_chain_sync(
    channel: Any,
    known_points: list[PointOrOrigin],
    on_roll_forward: OnRollForward,
    on_roll_backward: OnRollBackward,
    *,
    max_in_flight: int = 300,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run a pipelined chain-sync session from intersection to tip.

    This is the main entry point for pipelined chain synchronization.
    It mirrors run_chain_sync() from chainsync_protocol.py but uses
    pipelining for dramatically faster throughput.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for chain-sync.
    known_points : list[PointOrOrigin]
        Points to find intersection from (highest slot first).
    on_roll_forward : OnRollForward
        Async callback for each roll-forward.
    on_roll_backward : OnRollBackward
        Async callback for each roll-backward.
    max_in_flight : int
        Maximum pipeline depth (default: 300).
    stop_event : asyncio.Event | None
        If set, exit the sync loop.

    Raises
    ------
    ProtocolError
        If no intersection is found with the server.
    """
    client = PipelinedChainSyncClient(
        channel=channel,
        max_in_flight=max_in_flight,
    )

    # Step 1: Find intersection (always sequential).
    if not known_points:
        known_points = [ORIGIN]

    intersection, tip = await client.find_intersection(known_points)
    if intersection is None:
        raise ProtocolError(
            "No intersection found with the server. The consumer's "
            "known points do not overlap with the producer's chain."
        )

    logger.info(
        "Pipelined chain-sync intersection found: %s "
        "(server tip: block %d, pipeline depth: %d)",
        intersection,
        tip.block_number,
        max_in_flight,
    )

    # Step 2: Pipelined sync loop.
    await client.run_pipelined_sync(
        on_roll_forward=on_roll_forward,
        on_roll_backward=on_roll_backward,
        stop_event=stop_event,
    )
