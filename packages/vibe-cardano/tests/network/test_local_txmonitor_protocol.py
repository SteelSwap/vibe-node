"""Tests for local tx-monitor miniprotocol typed protocol FSM and codec.

Tests cover:
- Protocol state machine: initial state, agency at each state, valid messages
- Typed message wrappers: construction, state transitions
- Codec: encode/decode round-trip through the LocalTxMonitorCodec
- Server acquire/next/has/sizes flow via mocked channels
- Hypothesis CBOR round-trip through codec
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import cbor2
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.core.protocols import Agency, Message, ProtocolError

from vibe.cardano.network.local_txmonitor import (
    MsgAcquire,
    MsgAcquired,
    MsgAwaitAcquire,
    MsgDone,
    MsgGetSizes,
    MsgHasTx,
    MsgNextTx,
    MsgRelease,
    MsgReplyGetSizes,
    MsgReplyHasTx,
    MsgReplyNextTx,
)
from vibe.cardano.network.local_txmonitor_protocol import (
    LocalTxMonitorCodec,
    LocalTxMonitorProtocol,
    LocalTxMonitorServer,
    LocalTxMonitorState,
    LtmMsgAcquire,
    LtmMsgAcquired,
    LtmMsgAwaitAcquire,
    LtmMsgAwaitAcquireIdle,
    LtmMsgDone,
    LtmMsgGetSizes,
    LtmMsgHasTx,
    LtmMsgNextTx,
    LtmMsgRelease,
    LtmMsgReplyGetSizes,
    LtmMsgReplyHasTx,
    LtmMsgReplyNextTx,
)


# ---------------------------------------------------------------------------
# Protocol state machine tests
# ---------------------------------------------------------------------------


class TestLocalTxMonitorProtocol:
    """Verify the protocol state machine definition."""

    def setup_method(self) -> None:
        self.protocol = LocalTxMonitorProtocol()

    def test_initial_state(self) -> None:
        assert self.protocol.initial_state() == LocalTxMonitorState.StIdle

    def test_agency_idle(self) -> None:
        assert self.protocol.agency(LocalTxMonitorState.StIdle) == Agency.Client

    def test_agency_acquiring(self) -> None:
        assert (
            self.protocol.agency(LocalTxMonitorState.StAcquiring)
            == Agency.Server
        )

    def test_agency_acquired(self) -> None:
        assert (
            self.protocol.agency(LocalTxMonitorState.StAcquired)
            == Agency.Client
        )

    def test_agency_busy_next_tx(self) -> None:
        assert (
            self.protocol.agency(LocalTxMonitorState.StBusyNextTx)
            == Agency.Server
        )

    def test_agency_busy_has_tx(self) -> None:
        assert (
            self.protocol.agency(LocalTxMonitorState.StBusyHasTx)
            == Agency.Server
        )

    def test_agency_busy_get_sizes(self) -> None:
        assert (
            self.protocol.agency(LocalTxMonitorState.StBusyGetSizes)
            == Agency.Server
        )

    def test_agency_done(self) -> None:
        assert (
            self.protocol.agency(LocalTxMonitorState.StDone) == Agency.Nobody
        )

    def test_valid_messages_idle(self) -> None:
        msgs = self.protocol.valid_messages(LocalTxMonitorState.StIdle)
        assert LtmMsgAcquire in msgs
        assert LtmMsgAwaitAcquireIdle in msgs
        assert LtmMsgDone in msgs
        assert len(msgs) == 3

    def test_valid_messages_acquiring(self) -> None:
        msgs = self.protocol.valid_messages(LocalTxMonitorState.StAcquiring)
        assert LtmMsgAcquired in msgs
        assert len(msgs) == 1

    def test_valid_messages_acquired(self) -> None:
        msgs = self.protocol.valid_messages(LocalTxMonitorState.StAcquired)
        assert LtmMsgRelease in msgs
        assert LtmMsgNextTx in msgs
        assert LtmMsgHasTx in msgs
        assert LtmMsgGetSizes in msgs
        assert LtmMsgAwaitAcquire in msgs
        assert len(msgs) == 5

    def test_valid_messages_busy_next_tx(self) -> None:
        msgs = self.protocol.valid_messages(LocalTxMonitorState.StBusyNextTx)
        assert LtmMsgReplyNextTx in msgs
        assert len(msgs) == 1

    def test_valid_messages_busy_has_tx(self) -> None:
        msgs = self.protocol.valid_messages(LocalTxMonitorState.StBusyHasTx)
        assert LtmMsgReplyHasTx in msgs
        assert len(msgs) == 1

    def test_valid_messages_busy_get_sizes(self) -> None:
        msgs = self.protocol.valid_messages(
            LocalTxMonitorState.StBusyGetSizes
        )
        assert LtmMsgReplyGetSizes in msgs
        assert len(msgs) == 1

    def test_valid_messages_done(self) -> None:
        msgs = self.protocol.valid_messages(LocalTxMonitorState.StDone)
        assert len(msgs) == 0


# ---------------------------------------------------------------------------
# Typed message wrapper tests
# ---------------------------------------------------------------------------


class TestTypedMessages:
    """Verify typed message wrappers carry correct state transitions."""

    def test_ltm_msg_acquire(self) -> None:
        msg = LtmMsgAcquire()
        assert msg.from_state == LocalTxMonitorState.StIdle
        assert msg.to_state == LocalTxMonitorState.StAcquiring

    def test_ltm_msg_acquired(self) -> None:
        msg = LtmMsgAcquired(slot=100)
        assert msg.from_state == LocalTxMonitorState.StAcquiring
        assert msg.to_state == LocalTxMonitorState.StAcquired
        assert msg.slot == 100

    def test_ltm_msg_await_acquire_from_acquired(self) -> None:
        msg = LtmMsgAwaitAcquire()
        assert msg.from_state == LocalTxMonitorState.StAcquired
        assert msg.to_state == LocalTxMonitorState.StAcquiring

    def test_ltm_msg_await_acquire_from_idle(self) -> None:
        msg = LtmMsgAwaitAcquireIdle()
        assert msg.from_state == LocalTxMonitorState.StIdle
        assert msg.to_state == LocalTxMonitorState.StAcquiring

    def test_ltm_msg_release(self) -> None:
        msg = LtmMsgRelease()
        assert msg.from_state == LocalTxMonitorState.StAcquired
        assert msg.to_state == LocalTxMonitorState.StIdle

    def test_ltm_msg_next_tx(self) -> None:
        msg = LtmMsgNextTx()
        assert msg.from_state == LocalTxMonitorState.StAcquired
        assert msg.to_state == LocalTxMonitorState.StBusyNextTx

    def test_ltm_msg_reply_next_tx(self) -> None:
        msg = LtmMsgReplyNextTx(tx=(6, b"\x01"))
        assert msg.from_state == LocalTxMonitorState.StBusyNextTx
        assert msg.to_state == LocalTxMonitorState.StAcquired
        assert msg.tx == (6, b"\x01")

    def test_ltm_msg_reply_next_tx_nothing(self) -> None:
        msg = LtmMsgReplyNextTx(tx=None)
        assert msg.tx is None

    def test_ltm_msg_has_tx(self) -> None:
        msg = LtmMsgHasTx(tx_id=b"\xab" * 32)
        assert msg.from_state == LocalTxMonitorState.StAcquired
        assert msg.to_state == LocalTxMonitorState.StBusyHasTx
        assert msg.tx_id == b"\xab" * 32

    def test_ltm_msg_reply_has_tx(self) -> None:
        msg = LtmMsgReplyHasTx(has_tx=True)
        assert msg.from_state == LocalTxMonitorState.StBusyHasTx
        assert msg.to_state == LocalTxMonitorState.StAcquired
        assert msg.has_tx is True

    def test_ltm_msg_get_sizes(self) -> None:
        msg = LtmMsgGetSizes()
        assert msg.from_state == LocalTxMonitorState.StAcquired
        assert msg.to_state == LocalTxMonitorState.StBusyGetSizes

    def test_ltm_msg_reply_get_sizes(self) -> None:
        msg = LtmMsgReplyGetSizes(
            num_txs=10, total_size=5000, num_bytes=6000
        )
        assert msg.from_state == LocalTxMonitorState.StBusyGetSizes
        assert msg.to_state == LocalTxMonitorState.StAcquired
        assert msg.num_txs == 10
        assert msg.total_size == 5000
        assert msg.num_bytes == 6000

    def test_ltm_msg_done(self) -> None:
        msg = LtmMsgDone()
        assert msg.from_state == LocalTxMonitorState.StIdle
        assert msg.to_state == LocalTxMonitorState.StDone


# ---------------------------------------------------------------------------
# Codec tests
# ---------------------------------------------------------------------------


class TestLocalTxMonitorCodec:
    """Verify the codec encodes and decodes correctly."""

    def setup_method(self) -> None:
        self.codec = LocalTxMonitorCodec()

    def test_round_trip_acquire(self) -> None:
        original = LtmMsgAcquire()
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, (LtmMsgAcquire,))

    def test_round_trip_acquired(self) -> None:
        original = LtmMsgAcquired(slot=42000)
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LtmMsgAcquired)
        assert decoded.slot == 42000

    def test_round_trip_release(self) -> None:
        original = LtmMsgRelease()
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LtmMsgRelease)

    def test_round_trip_next_tx(self) -> None:
        original = LtmMsgNextTx()
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LtmMsgNextTx)

    def test_round_trip_reply_next_tx_nothing(self) -> None:
        original = LtmMsgReplyNextTx(tx=None)
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LtmMsgReplyNextTx)
        assert decoded.tx is None

    def test_round_trip_reply_next_tx_just(self) -> None:
        original = LtmMsgReplyNextTx(tx=(6, b"\x01\x02"))
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LtmMsgReplyNextTx)
        assert decoded.tx is not None
        assert decoded.tx[0] == 6
        assert decoded.tx[1] == b"\x01\x02"

    def test_round_trip_has_tx(self) -> None:
        tx_id = b"\xab" * 32
        original = LtmMsgHasTx(tx_id=tx_id)
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LtmMsgHasTx)
        assert decoded.tx_id == tx_id

    def test_round_trip_reply_has_tx(self) -> None:
        for val in [True, False]:
            original = LtmMsgReplyHasTx(has_tx=val)
            decoded = self.codec.decode(self.codec.encode(original))
            assert isinstance(decoded, LtmMsgReplyHasTx)
            assert decoded.has_tx == val

    def test_round_trip_get_sizes(self) -> None:
        original = LtmMsgGetSizes()
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LtmMsgGetSizes)

    def test_round_trip_reply_get_sizes(self) -> None:
        original = LtmMsgReplyGetSizes(
            num_txs=10, total_size=5000, num_bytes=6000
        )
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LtmMsgReplyGetSizes)
        assert decoded.num_txs == 10
        assert decoded.total_size == 5000
        assert decoded.num_bytes == 6000

    def test_round_trip_done(self) -> None:
        original = LtmMsgDone()
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LtmMsgDone)

    @given(slot=st.integers(min_value=0, max_value=2**63))
    @settings(max_examples=200)
    def test_hypothesis_round_trip_acquired(self, slot: int) -> None:
        original = LtmMsgAcquired(slot=slot)
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LtmMsgAcquired)
        assert decoded.slot == slot

    @given(
        era_id=st.integers(min_value=0, max_value=10),
        tx_bytes=st.binary(min_size=1, max_size=500),
    )
    @settings(max_examples=200)
    def test_hypothesis_round_trip_reply_next_tx(
        self, era_id: int, tx_bytes: bytes
    ) -> None:
        original = LtmMsgReplyNextTx(tx=(era_id, tx_bytes))
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LtmMsgReplyNextTx)
        assert decoded.tx is not None
        assert decoded.tx[0] == era_id
        assert decoded.tx[1] == tx_bytes

    @given(tx_id=st.binary(min_size=32, max_size=32))
    @settings(max_examples=200)
    def test_hypothesis_round_trip_has_tx(self, tx_id: bytes) -> None:
        original = LtmMsgHasTx(tx_id=tx_id)
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LtmMsgHasTx)
        assert decoded.tx_id == tx_id


# ---------------------------------------------------------------------------
# FSM transition tests
# ---------------------------------------------------------------------------


class TestFSMTransitions:
    """Verify the full state machine transition graph."""

    def setup_method(self) -> None:
        self.protocol = LocalTxMonitorProtocol()

    def test_full_acquire_query_release_done_cycle(self) -> None:
        """Walk through: acquire -> next_tx -> has_tx -> get_sizes -> release -> done."""
        state = self.protocol.initial_state()
        assert state == LocalTxMonitorState.StIdle

        # Acquire
        acquire = LtmMsgAcquire()
        assert acquire.from_state == state
        state = acquire.to_state
        assert state == LocalTxMonitorState.StAcquiring

        # Acquired
        acquired = LtmMsgAcquired(slot=100)
        assert acquired.from_state == state
        state = acquired.to_state
        assert state == LocalTxMonitorState.StAcquired

        # NextTx
        next_tx = LtmMsgNextTx()
        assert next_tx.from_state == state
        state = next_tx.to_state
        assert state == LocalTxMonitorState.StBusyNextTx

        # ReplyNextTx (with a tx)
        reply = LtmMsgReplyNextTx(tx=(6, b"\x01"))
        assert reply.from_state == state
        state = reply.to_state
        assert state == LocalTxMonitorState.StAcquired

        # HasTx
        has_tx = LtmMsgHasTx(tx_id=b"\xab" * 32)
        assert has_tx.from_state == state
        state = has_tx.to_state
        assert state == LocalTxMonitorState.StBusyHasTx

        # ReplyHasTx
        reply_has = LtmMsgReplyHasTx(has_tx=True)
        assert reply_has.from_state == state
        state = reply_has.to_state
        assert state == LocalTxMonitorState.StAcquired

        # GetSizes
        get_sizes = LtmMsgGetSizes()
        assert get_sizes.from_state == state
        state = get_sizes.to_state
        assert state == LocalTxMonitorState.StBusyGetSizes

        # ReplyGetSizes
        reply_sizes = LtmMsgReplyGetSizes(
            num_txs=5, total_size=1000, num_bytes=1200
        )
        assert reply_sizes.from_state == state
        state = reply_sizes.to_state
        assert state == LocalTxMonitorState.StAcquired

        # Release
        release = LtmMsgRelease()
        assert release.from_state == state
        state = release.to_state
        assert state == LocalTxMonitorState.StIdle

        # Done
        done = LtmMsgDone()
        assert done.from_state == state
        state = done.to_state
        assert state == LocalTxMonitorState.StDone
        assert self.protocol.agency(state) == Agency.Nobody

    def test_await_acquire_from_idle(self) -> None:
        """MsgAwaitAcquire from StIdle."""
        msg = LtmMsgAwaitAcquireIdle()
        assert msg.from_state == LocalTxMonitorState.StIdle
        assert msg.to_state == LocalTxMonitorState.StAcquiring

    def test_await_acquire_from_acquired(self) -> None:
        """MsgAwaitAcquire from StAcquired (re-acquire)."""
        msg = LtmMsgAwaitAcquire()
        assert msg.from_state == LocalTxMonitorState.StAcquired
        assert msg.to_state == LocalTxMonitorState.StAcquiring

    def test_iterate_all_txs(self) -> None:
        """Iterate through multiple NextTx until Nothing."""
        state = LocalTxMonitorState.StAcquired

        for _ in range(3):
            next_tx = LtmMsgNextTx()
            assert next_tx.from_state == state
            state = next_tx.to_state
            reply = LtmMsgReplyNextTx(tx=(6, b"\x01"))
            assert reply.from_state == state
            state = reply.to_state
            assert state == LocalTxMonitorState.StAcquired

        # Final NextTx returns Nothing
        next_tx = LtmMsgNextTx()
        state = next_tx.to_state
        reply_none = LtmMsgReplyNextTx(tx=None)
        assert reply_none.from_state == state
        state = reply_none.to_state
        assert state == LocalTxMonitorState.StAcquired


# ---------------------------------------------------------------------------
# Server tests
# ---------------------------------------------------------------------------


class TestLocalTxMonitorServer:
    """Test the high-level LocalTxMonitorServer."""

    def _make_server(self) -> tuple[LocalTxMonitorServer, MagicMock]:
        runner = MagicMock()
        runner.state = LocalTxMonitorState.StIdle
        runner.is_done = False
        runner.send_message = AsyncMock()
        runner.recv_message = AsyncMock()
        server = LocalTxMonitorServer(runner)
        return server, runner

    @pytest.mark.asyncio
    async def test_send_acquired(self) -> None:
        server, runner = self._make_server()
        await server.send_acquired(slot=42000)
        runner.send_message.assert_called_once()
        sent = runner.send_message.call_args[0][0]
        assert isinstance(sent, LtmMsgAcquired)
        assert sent.slot == 42000

    @pytest.mark.asyncio
    async def test_send_reply_next_tx_just(self) -> None:
        server, runner = self._make_server()
        await server.send_reply_next_tx(tx=(6, b"\x01"))
        sent = runner.send_message.call_args[0][0]
        assert isinstance(sent, LtmMsgReplyNextTx)
        assert sent.tx == (6, b"\x01")

    @pytest.mark.asyncio
    async def test_send_reply_next_tx_nothing(self) -> None:
        server, runner = self._make_server()
        await server.send_reply_next_tx(tx=None)
        sent = runner.send_message.call_args[0][0]
        assert isinstance(sent, LtmMsgReplyNextTx)
        assert sent.tx is None

    @pytest.mark.asyncio
    async def test_send_reply_has_tx(self) -> None:
        server, runner = self._make_server()
        await server.send_reply_has_tx(has_tx=True)
        sent = runner.send_message.call_args[0][0]
        assert isinstance(sent, LtmMsgReplyHasTx)
        assert sent.has_tx is True

    @pytest.mark.asyncio
    async def test_send_reply_get_sizes(self) -> None:
        server, runner = self._make_server()
        await server.send_reply_get_sizes(
            num_txs=10, total_size=5000, num_bytes=6000
        )
        sent = runner.send_message.call_args[0][0]
        assert isinstance(sent, LtmMsgReplyGetSizes)
        assert sent.num_txs == 10
        assert sent.total_size == 5000
        assert sent.num_bytes == 6000


# ---------------------------------------------------------------------------
# Direct client-server pairing test
# ---------------------------------------------------------------------------


class TestDirectClientServer:
    """Direct client-server pairing via message passing."""

    @staticmethod
    def _make_connected_channels() -> tuple[MagicMock, MagicMock]:
        client_to_server: asyncio.Queue[bytes] = asyncio.Queue()
        server_to_client: asyncio.Queue[bytes] = asyncio.Queue()

        client_channel = MagicMock()
        server_channel = MagicMock()

        async def client_send(data: bytes) -> None:
            await client_to_server.put(data)

        async def client_recv() -> bytes:
            return await server_to_client.get()

        async def server_send(data: bytes) -> None:
            await server_to_client.put(data)

        async def server_recv() -> bytes:
            return await client_to_server.get()

        client_channel.send = AsyncMock(side_effect=client_send)
        client_channel.recv = AsyncMock(side_effect=client_recv)
        server_channel.send = AsyncMock(side_effect=server_send)
        server_channel.recv = AsyncMock(side_effect=server_recv)

        return client_channel, server_channel

    @pytest.mark.asyncio
    async def test_acquire_next_has_sizes_release_done(self) -> None:
        """Full flow: acquire -> next_tx -> has_tx -> get_sizes -> release -> done."""
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner

        client_ch, server_ch = self._make_connected_channels()

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=LocalTxMonitorProtocol(),
            codec=LocalTxMonitorCodec(),
            channel=client_ch,
        )
        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=LocalTxMonitorProtocol(),
            codec=LocalTxMonitorCodec(),
            channel=server_ch,
        )
        server = LocalTxMonitorServer(server_runner)

        tx_id = b"\xab" * 32

        async def server_task() -> dict:
            # Expect Acquire
            msg = await server.recv_client_message()
            assert isinstance(msg, LtmMsgAcquire)
            await server.send_acquired(slot=42000)

            # Expect NextTx
            msg = await server.recv_client_message()
            assert isinstance(msg, LtmMsgNextTx)
            await server.send_reply_next_tx(tx=(6, b"\x84"))

            # Expect NextTx again (returns Nothing)
            msg = await server.recv_client_message()
            assert isinstance(msg, LtmMsgNextTx)
            await server.send_reply_next_tx(tx=None)

            # Expect HasTx
            msg = await server.recv_client_message()
            assert isinstance(msg, LtmMsgHasTx)
            assert msg.tx_id == tx_id
            await server.send_reply_has_tx(has_tx=True)

            # Expect GetSizes
            msg = await server.recv_client_message()
            assert isinstance(msg, LtmMsgGetSizes)
            await server.send_reply_get_sizes(
                num_txs=5, total_size=1000, num_bytes=1200
            )

            # Expect Release
            msg = await server.recv_client_message()
            assert isinstance(msg, LtmMsgRelease)

            # Expect Done
            msg = await server.recv_client_message()
            assert isinstance(msg, LtmMsgDone)

            return {"completed": True}

        task = asyncio.create_task(server_task())

        # Client: Acquire
        await client_runner.send_message(LtmMsgAcquire())
        resp = await client_runner.recv_message()
        assert isinstance(resp, LtmMsgAcquired)
        assert resp.slot == 42000

        # Client: NextTx (returns a tx)
        await client_runner.send_message(LtmMsgNextTx())
        resp = await client_runner.recv_message()
        assert isinstance(resp, LtmMsgReplyNextTx)
        assert resp.tx is not None
        assert resp.tx[0] == 6

        # Client: NextTx (returns Nothing)
        await client_runner.send_message(LtmMsgNextTx())
        resp = await client_runner.recv_message()
        assert isinstance(resp, LtmMsgReplyNextTx)
        assert resp.tx is None

        # Client: HasTx
        await client_runner.send_message(LtmMsgHasTx(tx_id=tx_id))
        resp = await client_runner.recv_message()
        assert isinstance(resp, LtmMsgReplyHasTx)
        assert resp.has_tx is True

        # Client: GetSizes
        await client_runner.send_message(LtmMsgGetSizes())
        resp = await client_runner.recv_message()
        assert isinstance(resp, LtmMsgReplyGetSizes)
        assert resp.num_txs == 5
        assert resp.total_size == 1000
        assert resp.num_bytes == 1200

        # Client: Release
        await client_runner.send_message(LtmMsgRelease())

        # Client: Done
        await client_runner.send_message(LtmMsgDone())

        result = await task
        assert result["completed"] is True

    @pytest.mark.asyncio
    async def test_immediate_done(self) -> None:
        """Client sends done immediately from StIdle."""
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner

        client_ch, server_ch = self._make_connected_channels()

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=LocalTxMonitorProtocol(),
            codec=LocalTxMonitorCodec(),
            channel=client_ch,
        )
        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=LocalTxMonitorProtocol(),
            codec=LocalTxMonitorCodec(),
            channel=server_ch,
        )
        server = LocalTxMonitorServer(server_runner)

        async def server_task() -> str:
            msg = await server.recv_client_message()
            assert isinstance(msg, LtmMsgDone)
            return "done"

        task = asyncio.create_task(server_task())
        await client_runner.send_message(LtmMsgDone())
        result = await task
        assert result == "done"

    @pytest.mark.asyncio
    async def test_multiple_acquire_cycles(self) -> None:
        """Acquire, query, release, acquire again."""
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner

        client_ch, server_ch = self._make_connected_channels()

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=LocalTxMonitorProtocol(),
            codec=LocalTxMonitorCodec(),
            channel=client_ch,
        )
        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=LocalTxMonitorProtocol(),
            codec=LocalTxMonitorCodec(),
            channel=server_ch,
        )
        server = LocalTxMonitorServer(server_runner)

        async def server_task() -> int:
            cycle_count = 0
            for slot in [100, 200]:
                msg = await server.recv_client_message()
                assert isinstance(msg, LtmMsgAcquire)
                await server.send_acquired(slot=slot)

                msg = await server.recv_client_message()
                assert isinstance(msg, LtmMsgGetSizes)
                await server.send_reply_get_sizes(
                    num_txs=slot // 10,
                    total_size=slot * 10,
                    num_bytes=slot * 12,
                )

                msg = await server.recv_client_message()
                assert isinstance(msg, LtmMsgRelease)
                cycle_count += 1

            msg = await server.recv_client_message()
            assert isinstance(msg, LtmMsgDone)
            return cycle_count

        task = asyncio.create_task(server_task())

        for slot in [100, 200]:
            await client_runner.send_message(LtmMsgAcquire())
            resp = await client_runner.recv_message()
            assert isinstance(resp, LtmMsgAcquired)
            assert resp.slot == slot

            await client_runner.send_message(LtmMsgGetSizes())
            resp = await client_runner.recv_message()
            assert isinstance(resp, LtmMsgReplyGetSizes)
            assert resp.num_txs == slot // 10

            await client_runner.send_message(LtmMsgRelease())

        await client_runner.send_message(LtmMsgDone())
        cycle_count = await task
        assert cycle_count == 2
