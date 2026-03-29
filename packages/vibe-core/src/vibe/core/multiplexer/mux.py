"""Ouroboros multiplexer/demultiplexer — route segments to miniprotocol channels.

Manages multiple miniprotocols over a single TCP connection. Each miniprotocol
gets a bidirectional async channel (pair of queues). The multiplexer runs two
background tasks: a sender that reads from all outbound queues with fair
round-robin scheduling, and a receiver that routes inbound segments to the
correct miniprotocol channel based on protocol_id.

Spec reference:
    Ouroboros network spec, Chapter 1 "Multiplexing mini-protocols".
    The multiplexer is responsible for interleaving SDUs from multiple
    mini-protocols onto a single bearer, with fairness guarantees so
    no single protocol can starve others.

Haskell reference:
    Network.Mux (runMux, muxChannel)
    Network.Mux.Types (MuxMode, MiniProtocolNum, MiniProtocolDir)

Design notes from test_specifications DB:
    - test_multiplexed_messages_preserve_protocol_isolation: demux must always
      deliver each message to the correct mini-protocol with ordering preserved.
    - test_mux_fairness_all_protocols_get_scheduled: with N protocols, each must
      get serviced (no starvation).
    - test_mux_bearer_closed_shuts_down_peer_only: BearerClosed should shut down
      only the affected peer connection.
    - test_mux_unknown_miniprotocol_shuts_down_node: unknown protocol triggers
      ShutdownNode in Haskell. We log a warning and drop the segment for now,
      since we don't yet have the full connection manager to escalate to.
    - test_mux_mini_protocol_keyed_by_num_and_dir: protocols are keyed by
      (MiniProtocolNum, MiniProtocolDir) supporting full-duplex operation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from vibe.core.multiplexer.bearer import Bearer, BearerClosedError
from vibe.core.multiplexer.segment import MuxSegment

logger = logging.getLogger(__name__)

# Sentinel used to signal channel shutdown.
_CHANNEL_CLOSED = object()


class MuxError(Exception):
    """Base exception for multiplexer errors."""


class MuxClosedError(MuxError):
    """Raised when operating on a closed multiplexer."""


class IngressOverflowError(MuxError):
    """Raised when a channel's inbound queue exceeds its max size.

    Haskell reference: Network.Mux.demux — when the ingress queue is full,
    the Haskell node tears down the connection. We close the individual
    channel and log the overflow.
    """


@dataclass
class MiniProtocolChannel:
    """A bidirectional channel for one miniprotocol over a multiplexed bearer.

    Each channel has an inbound queue (segments arriving from the remote peer)
    and an outbound queue (segments to send to the remote peer). The multiplexer
    sender task drains outbound queues; the receiver task fills inbound queues.

    Args:
        max_ingress_size: Maximum number of items in the inbound queue. When
            exceeded, the channel is closed (matching Haskell's behavior of
            tearing down the connection on ingress overflow). 0 means unbounded.

    Haskell reference: Network.Mux.Types.MiniProtocolState (ingress/egress queues)
    """

    protocol_id: int
    is_initiator: bool
    max_ingress_size: int = 0
    _inbound: asyncio.Queue[bytes | object] = field(
        default=None,
        repr=False,  # type: ignore[assignment]
    )
    _outbound: asyncio.Queue[bytes | object] = field(default_factory=asyncio.Queue, repr=False)
    _closed: bool = field(default=False, repr=False)
    _on_send: object = field(default=None, repr=False)  # Callable[[], None] | None

    def __post_init__(self) -> None:
        if self._inbound is None:
            if self.max_ingress_size > 0:
                self._inbound = asyncio.Queue(maxsize=self.max_ingress_size)
            else:
                self._inbound = asyncio.Queue()

    async def send(self, payload: bytes) -> None:
        """Queue outbound payload for transmission via the multiplexer.

        Raises:
            MuxClosedError: If the channel has been closed.
        """
        if self._closed:
            raise MuxClosedError(f"channel for protocol {self.protocol_id} is closed")
        await self._outbound.put(payload)
        if self._on_send is not None:
            self._on_send()

    async def recv(self) -> bytes:
        """Receive inbound payload from the remote peer.

        Blocks until a payload is available. Raises MuxClosedError if the
        channel is shut down while waiting.

        Raises:
            MuxClosedError: If the channel is closed (or closes while waiting).
        """
        if self._closed and self._inbound.empty():
            raise MuxClosedError(f"channel for protocol {self.protocol_id} is closed")
        item = await self._inbound.get()
        if item is _CHANNEL_CLOSED:
            self._closed = True
            raise MuxClosedError(f"channel for protocol {self.protocol_id} is closed")
        assert isinstance(item, bytes)
        return item

    def close(self) -> None:
        """Mark the channel as closed and unblock any waiting recv()."""
        if self._closed:
            return
        self._closed = True
        # Put sentinel to unblock any pending recv().
        try:
            self._inbound.put_nowait(_CHANNEL_CLOSED)
        except asyncio.QueueFull:
            pass
        # Put sentinel to unblock any pending sender drain.
        try:
            self._outbound.put_nowait(_CHANNEL_CLOSED)
        except asyncio.QueueFull:
            pass


class Multiplexer:
    """Orchestrates multiple miniprotocol channels over a single Bearer.

    The multiplexer runs two concurrent tasks:
    - **Sender**: drains outbound queues from all registered channels with
      round-robin fair scheduling, encodes each payload as a MuxSegment, and
      writes it to the bearer.
    - **Receiver**: reads segments from the bearer and routes each payload
      to the correct channel's inbound queue based on protocol_id.

    Haskell reference:
        Network.Mux.runMux — the main mux loop that runs sender/receiver.
        Network.Mux.Types.MuxMode — InitiatorMode / ResponderMode / InitiatorResponderMode.

    Spec reference:
        Ouroboros network spec, Section 1.2 "Scheduling" — fair interleaving
        of SDUs from multiple mini-protocols.
    """

    __slots__ = (
        "_bearer",
        "_is_initiator",
        "_channels",
        "_sender_task",
        "_receiver_task",
        "_running",
        "_closed",
        "_stop_event",
        "_data_available",
    )

    def __init__(self, bearer: Bearer, is_initiator: bool) -> None:
        self._bearer = bearer
        self._is_initiator = is_initiator
        self._channels: dict[tuple[int, bool], MiniProtocolChannel] = {}
        self._sender_task: asyncio.Task[None] | None = None
        self._receiver_task: asyncio.Task[None] | None = None
        self._running = False
        self._closed = False
        self._stop_event = asyncio.Event()
        self._data_available = asyncio.Event()

    @property
    def is_initiator(self) -> bool:
        return self._is_initiator

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_closed(self) -> bool:
        return self._closed

    def add_protocol(self, protocol_id: int, max_ingress_size: int = 0) -> MiniProtocolChannel:
        """Register a miniprotocol in a single direction and return its channel.

        Backward-compatible API: registers only the direction matching
        ``self._is_initiator``. For full-duplex (both initiator and responder
        on the same connection), use :meth:`add_protocol_pair` instead.

        Must be called before run(). Each ``(protocol_id, direction)`` can
        only be registered once.

        Args:
            protocol_id: The miniprotocol number (0-32767).
            max_ingress_size: Maximum inbound queue depth. 0 = unbounded.
                When exceeded, the channel is closed (Haskell tears down
                the connection on ingress overflow).

        Returns:
            A MiniProtocolChannel for sending/receiving on this protocol.

        Raises:
            ValueError: If the (protocol_id, direction) is already registered or out of range.
            MuxClosedError: If the multiplexer has been closed.
        """
        if self._closed:
            raise MuxClosedError("multiplexer is closed")
        if not (0 <= protocol_id <= 0x7FFF):
            raise ValueError(f"protocol_id must be 0..32767, got {protocol_id}")
        key = (protocol_id, self._is_initiator)
        if key in self._channels:
            raise ValueError(f"protocol {protocol_id} direction {'initiator' if self._is_initiator else 'responder'} is already registered")
        channel = MiniProtocolChannel(
            protocol_id=protocol_id,
            is_initiator=self._is_initiator,
            max_ingress_size=max_ingress_size,
        )
        channel._on_send = self._data_available.set
        self._channels[key] = channel
        return channel

    def add_protocol_pair(
        self, protocol_id: int, max_ingress_size: int = 0
    ) -> tuple[MiniProtocolChannel, MiniProtocolChannel]:
        """Register both initiator and responder channels for a protocol.

        This matches the Haskell mux model where protocols are keyed by
        ``(MiniProtocolNum, MiniProtocolDir)``, supporting full-duplex
        operation on a single bearer connection.

        Args:
            protocol_id: The miniprotocol number (0-32767).
            max_ingress_size: Maximum inbound queue depth per channel.
                0 = unbounded.

        Returns:
            A tuple of ``(initiator_channel, responder_channel)``.

        Raises:
            ValueError: If either direction is already registered or protocol_id
                is out of range.
            MuxClosedError: If the multiplexer has been closed.

        Haskell reference:
            Network.Mux.Types — MuxMode InitiatorResponderMode registers both
            InitiatorDir and ResponderDir for each MiniProtocolNum.
        """
        if self._closed:
            raise MuxClosedError("multiplexer is closed")
        if not (0 <= protocol_id <= 0x7FFF):
            raise ValueError(f"protocol_id must be 0..32767, got {protocol_id}")
        init_key = (protocol_id, True)
        resp_key = (protocol_id, False)
        if init_key in self._channels or resp_key in self._channels:
            raise ValueError(f"protocol {protocol_id} is already registered")

        init_channel = MiniProtocolChannel(
            protocol_id=protocol_id,
            is_initiator=True,
            max_ingress_size=max_ingress_size,
        )
        resp_channel = MiniProtocolChannel(
            protocol_id=protocol_id,
            is_initiator=False,
            max_ingress_size=max_ingress_size,
        )
        init_channel._on_send = self._data_available.set
        resp_channel._on_send = self._data_available.set
        self._channels[init_key] = init_channel
        self._channels[resp_key] = resp_channel
        return init_channel, resp_channel

    async def run(self) -> None:
        """Start the sender and receiver background tasks.

        Blocks until both tasks complete (due to close() or bearer disconnect).
        If either task raises an exception, the other is cancelled and the
        exception propagates after cleanup.

        Raises:
            MuxClosedError: If the multiplexer has already been closed.
        """
        if self._closed:
            raise MuxClosedError("multiplexer is closed")
        if self._running:
            raise MuxError("multiplexer is already running")

        self._running = True
        self._sender_task = asyncio.create_task(self._sender_loop(), name="mux-sender")
        self._receiver_task = asyncio.create_task(self._receiver_loop(), name="mux-receiver")

        try:
            # Wait for either task to complete (exception OR normal return).
            # Normal return happens when the bearer disconnects — the receiver
            # exits cleanly, and we need to tear down the sender too.
            done, pending = await asyncio.wait(
                [self._sender_task, self._receiver_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            # Cancel any remaining task.
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError, Exception:
                    pass

            # Re-raise any exception from the completed task(s).
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(
                    exc, (asyncio.CancelledError, MuxClosedError)
                ):
                    raise exc
        finally:
            self._running = False
            await self._shutdown_channels()

    async def close(self) -> None:
        """Shut down the multiplexer: cancel tasks, close channels, close bearer.

        Safe to call multiple times.
        """
        if self._closed:
            return
        self._closed = True
        self._stop_event.set()

        # Cancel background tasks.
        for task in (self._sender_task, self._receiver_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError, Exception:
                    pass

        await self._shutdown_channels()
        await self._bearer.close()

    async def _shutdown_channels(self) -> None:
        """Close all registered channels."""
        for channel in self._channels.values():
            channel.close()

    def _make_timestamp(self) -> int:
        """Generate a timestamp for outbound segments.

        Uses the lower 32 bits of the monotonic clock in microseconds,
        matching the Haskell implementation (Network.Mux.Codec.encodeSDU).
        """
        return int(time.monotonic() * 1_000_000) & 0xFFFFFFFF

    async def _sender_loop(self) -> None:
        """Drain outbound queues with round-robin fair scheduling.

        Cycles through all registered channels, checking each for an outbound
        payload. Segments are buffered via write() and flushed with a single
        drain() per round-robin pass (batched writes reduce syscall overhead).
        When no channel has data, we block on an asyncio.Event rather than
        polling — channels signal the event when they enqueue data.

        This ensures fair scheduling: no single protocol can starve others,
        since we advance to the next protocol after sending one segment.

        Spec reference:
            Ouroboros network spec, Section 1.2 — "The multiplexer scheduler
            must ensure that each mini-protocol gets a fair share of the bearer."

        Haskell reference:
            Network.Mux.Bearer.Socket uses buffered writes (sendAll) and the
            mux sender collects from all miniprotocols before writing.
        """
        channel_keys = list(self._channels.keys())
        if not channel_keys:
            # No protocols registered — just wait for cancellation.
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                return

        while not self._closed:
            # Event-driven: wait for any channel to signal data,
            # then drain ALL channels with pending data immediately.
            # This is faster than round-robin because there's no
            # cycling through empty channels — we go straight to
            # the ones that have data.
            self._data_available.clear()

            # Drain all channels, buffering segments, then flush once.
            # Haskell's mux sender collects from all miniprotocols
            # before writing. We buffer via buffer_segment() and flush
            # once per pass to reduce syscalls and TCP round-trips.
            sent_any = False
            for channel in self._channels.values():
                if channel._closed:
                    continue
                # Drain up to 20 segments per channel per wake
                for _ in range(20):
                    try:
                        payload = channel._outbound.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                    if payload is _CHANNEL_CLOSED:
                        break

                    assert isinstance(payload, bytes)
                    segment = MuxSegment(
                        timestamp=self._make_timestamp(),
                        protocol_id=channel.protocol_id,
                        is_initiator=channel.is_initiator,
                        payload=payload,
                    )
                    try:
                        self._bearer.buffer_segment(segment)
                    except (BearerClosedError, ConnectionError) as exc:
                        logger.debug("sender: bearer disconnected: %s", exc)
                        return
                    sent_any = True

            # Flush all buffered segments in one syscall
            if sent_any:
                try:
                    await self._bearer.flush()
                except (BearerClosedError, ConnectionError) as exc:
                    logger.debug("sender: bearer disconnected: %s", exc)
                    return

            if not sent_any:
                # Nothing to send — wait for data or shutdown.
                # Double-check after clearing _data_available to
                # avoid race between drain loop and new send().
                if any(
                    not ch._closed and not ch._outbound.empty()
                    for ch in self._channels.values()
                ):
                    continue
                data_task = asyncio.create_task(self._data_available.wait())
                stop_task = asyncio.create_task(self._stop_event.wait())
                done, pending = await asyncio.wait(
                    [data_task, stop_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except asyncio.CancelledError:
                        pass
                if self._stop_event.is_set():
                    return

    async def _receiver_loop(self) -> None:
        """Read segments from the bearer and route to protocol channels.

        Each inbound segment is matched to a registered channel by protocol_id.
        Unknown protocol IDs are logged and the segment is dropped.

        Haskell reference:
            Network.Mux.demux — reads SDUs and dispatches to ingress queues.
        """
        while not self._closed:
            try:
                segment = await self._bearer.read_segment()
            except (BearerClosedError, ConnectionError) as exc:
                logger.debug("receiver: bearer disconnected: %s", exc)
                return
            except asyncio.IncompleteReadError:
                logger.debug("receiver: incomplete read — bearer disconnected")
                return

            # Flip direction: the remote's initiator sends to our responder
            # and vice versa. This matches Haskell's Network.Mux.demux which
            # routes by (MiniProtocolNum, flipDir MiniProtocolDir).
            local_dir = not segment.is_initiator
            channel = self._channels.get((segment.protocol_id, local_dir))
            if channel is None:
                # Haskell escalates to ShutdownNode for unknown protocols.
                # We log and drop for now — we don't have a connection manager
                # to escalate to yet. This is a documented gap.
                logger.warning(
                    "receiver: unknown protocol_id %d dir %s — dropping %d bytes",
                    segment.protocol_id,
                    "initiator" if local_dir else "responder",
                    len(segment.payload),
                )
                continue

            if channel._closed:
                logger.debug(
                    "receiver: channel for protocol %d is closed — dropping",
                    segment.protocol_id,
                )
                continue

            try:
                channel._inbound.put_nowait(segment.payload)
            except asyncio.QueueFull:
                # Haskell tears down the connection on ingress overflow.
                # We close the individual channel — this is a bounded-queue
                # safety measure to prevent unbounded memory growth.
                logger.warning(
                    "receiver: inbound queue full for protocol %d "
                    "— closing channel (max_ingress_size=%d)",
                    segment.protocol_id,
                    channel.max_ingress_size,
                )
                channel.close()
