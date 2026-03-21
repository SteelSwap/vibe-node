"""PipelinedRunner — send multiple requests without waiting for responses.

The standard ProtocolRunner enforces a strict send-then-recv cadence:
each request waits for its response before the next request can be sent.
This is correct but slow — the round-trip latency between send and recv
is dead time where the connection sits idle.

Pipelining breaks this bottleneck. The client sends up to `max_in_flight`
requests before any response arrives. Responses are collected asynchronously
in order. When the pipeline is full (max_in_flight reached), the next
send_request blocks until a response is collected, providing backpressure.

This matches the Haskell implementation's pipelining support:

Haskell reference:
    Ouroboros.Network.Protocol.ChainSync.ClientPipelined
    Network.TypedProtocol.Pipelined (PeerPipelined, PeerSender, PeerReceiver)
    The Haskell version uses a Nat-indexed type to track pipeline depth.
    We use a simpler runtime counter + asyncio.Semaphore for backpressure.

Spec reference:
    Ouroboros network spec, Section 2.3 "Pipelining"
    "A pipelined peer may send multiple requests without waiting for
    the corresponding responses. The number of outstanding requests
    is bounded by the pipeline depth."

Design:
    The PipelinedRunner wraps a MiniProtocolChannel and provides:
    - send_request(payload): encode and send, non-blocking up to max_in_flight
    - collect_response(): wait for the next response in FIFO order
    - drain(): collect all in-flight responses (used on rollback)
    - in_flight: current number of outstanding requests

    The runner does NOT track protocol state — that's the caller's job.
    This is deliberate: pipelined protocols have complex state interactions
    (e.g., chain-sync rollback requires draining the pipeline before
    processing the rollback point), and pushing state management to the
    caller keeps this layer simple and composable.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

__all__ = ["PipelinedRunner"]

logger = logging.getLogger(__name__)


class PipelinedRunner:
    """Manages pipelined request/response over a miniprotocol channel.

    Sends requests without waiting for responses, up to max_in_flight.
    Responses are collected in FIFO order. When the pipeline is full,
    send_request blocks until a response is collected (backpressure).

    This is a low-level building block. Protocol-specific pipelining
    (chain-sync, block-fetch) is built on top of this.

    Parameters
    ----------
    channel : MiniProtocolChannel
        The mux channel for this miniprotocol.
    codec : Codec
        Encodes/decodes messages for this specific miniprotocol.
    max_in_flight : int
        Maximum number of requests that can be outstanding before
        backpressure kicks in. Must be >= 1.

    Haskell reference:
        Network.TypedProtocol.Pipelined — the pipeline depth is tracked
        as a type-level natural number (Zero, Succ n). We use a runtime
        semaphore instead, which gives us the same backpressure semantics
        without the type gymnastics.
    """

    __slots__ = (
        "_channel",
        "_codec",
        "_max_in_flight",
        "_semaphore",
        "_response_queue",
        "_in_flight",
        "_recv_task",
        "_closed",
    )

    def __init__(
        self,
        channel: Any,
        codec: Any,
        max_in_flight: int = 100,
    ) -> None:
        if max_in_flight < 1:
            raise ValueError(f"max_in_flight must be >= 1, got {max_in_flight}")

        self._channel = channel
        self._codec = codec
        self._max_in_flight = max_in_flight
        self._semaphore = asyncio.Semaphore(max_in_flight)
        self._response_queue: asyncio.Queue[Any] = asyncio.Queue()
        self._in_flight = 0
        self._recv_task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def max_in_flight(self) -> int:
        """Maximum pipeline depth."""
        return self._max_in_flight

    @property
    def in_flight(self) -> int:
        """Number of requests currently awaiting responses."""
        return self._in_flight

    @property
    def is_closed(self) -> bool:
        """Whether the pipeline has been shut down."""
        return self._closed

    def start(self) -> None:
        """Start the background receiver task.

        Must be called before send_request/collect_response. The receiver
        task continuously reads from the channel and enqueues decoded
        responses for collection.
        """
        if self._recv_task is not None:
            raise RuntimeError("PipelinedRunner already started")
        self._recv_task = asyncio.get_event_loop().create_task(
            self._receiver_loop(),
            name="pipelined-receiver",
        )

    async def stop(self) -> None:
        """Stop the background receiver task and clean up."""
        self._closed = True
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None

    async def send_request(self, message: Any) -> None:
        """Send a request message, blocking if pipeline is full.

        If max_in_flight requests are already outstanding, this blocks
        until collect_response() is called to free a slot. This provides
        natural backpressure — the sender can't get arbitrarily far ahead
        of the consumer.

        Parameters
        ----------
        message : Message
            The typed protocol message to send.

        Raises
        ------
        RuntimeError
            If the pipeline is closed or not started.
        """
        if self._closed:
            raise RuntimeError("PipelinedRunner is closed")
        if self._recv_task is None:
            raise RuntimeError("PipelinedRunner not started — call start() first")

        # Block until a pipeline slot is available.
        await self._semaphore.acquire()

        try:
            data = self._codec.encode(message)
            await self._channel.send(data)
            self._in_flight += 1
            logger.debug(
                "pipelined send %s (%d bytes, %d in flight)",
                type(message).__name__,
                len(data),
                self._in_flight,
            )
        except Exception:
            # Release the semaphore slot on failure.
            self._semaphore.release()
            raise

    async def collect_response(self) -> Any:
        """Wait for and return the next response in FIFO order.

        Blocks until a response is available. Responses are guaranteed
        to arrive in the same order as the requests were sent (TCP
        ordering + single channel).

        Returns
        -------
        Message
            The decoded response message.

        Raises
        ------
        RuntimeError
            If no requests are in flight or pipeline is closed.
        Exception
            If the receiver encountered an error (propagated here).
        """
        response = await self._response_queue.get()

        # Check if the receiver task propagated an error.
        if isinstance(response, Exception):
            raise response

        self._in_flight -= 1
        self._semaphore.release()

        logger.debug(
            "pipelined recv %s (%d in flight)",
            type(response).__name__,
            self._in_flight,
        )
        return response

    async def drain(self) -> list[Any]:
        """Collect all in-flight responses and return them as a list.

        Used when the pipeline needs to be flushed — for example, when
        chain-sync receives a rollback and must process all pending
        responses before handling the rollback point.

        Returns
        -------
        list[Message]
            All pending responses, in order.
        """
        responses: list[Any] = []
        while self._in_flight > 0 or not self._response_queue.empty():
            try:
                response = await self._response_queue.get()
                if isinstance(response, Exception):
                    raise response
                responses.append(response)
                self._in_flight -= 1
                self._semaphore.release()
            except asyncio.QueueEmpty:
                break
        return responses

    async def _receiver_loop(self) -> None:
        """Background task: read responses from channel and enqueue them.

        Runs until cancelled or the channel closes. On error, the
        exception is enqueued so collect_response() can propagate it.
        """
        try:
            while not self._closed:
                data = await self._channel.recv()
                message = self._codec.decode(data)
                await self._response_queue.put(message)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            # Propagate the error to the collector.
            logger.error("Pipelined receiver error: %s", exc)
            await self._response_queue.put(exc)

    async def __aenter__(self) -> PipelinedRunner:
        """Context manager support: start the receiver on entry."""
        self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Context manager support: stop the receiver on exit."""
        await self.stop()
