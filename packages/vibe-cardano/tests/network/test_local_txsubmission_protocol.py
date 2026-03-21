"""Tests for local tx-submission miniprotocol typed protocol FSM and codec.

Tests cover:
- Protocol state machine: initial state, agency at each state, valid messages
- Typed message wrappers: construction, state transitions
- Codec: encode/decode round-trip through the LocalTxSubmissionCodec
- Server accept/reject flow via mocked channels
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

from vibe.cardano.network.local_txsubmission import (
    MsgAcceptTx,
    MsgDone,
    MsgRejectTx,
    MsgSubmitTx,
)
from vibe.cardano.network.local_txsubmission_protocol import (
    LocalTxSubmissionCodec,
    LocalTxSubmissionProtocol,
    LocalTxSubmissionServer,
    LocalTxSubmissionState,
    LtsMsgAcceptTx,
    LtsMsgDone,
    LtsMsgRejectTx,
    LtsMsgSubmitTx,
)


# ---------------------------------------------------------------------------
# Protocol state machine tests
# ---------------------------------------------------------------------------


class TestLocalTxSubmissionProtocol:
    """Verify the protocol state machine definition."""

    def setup_method(self) -> None:
        self.protocol = LocalTxSubmissionProtocol()

    def test_initial_state(self) -> None:
        assert self.protocol.initial_state() == LocalTxSubmissionState.StIdle

    def test_agency_idle(self) -> None:
        assert (
            self.protocol.agency(LocalTxSubmissionState.StIdle)
            == Agency.Client
        )

    def test_agency_busy(self) -> None:
        assert (
            self.protocol.agency(LocalTxSubmissionState.StBusy)
            == Agency.Server
        )

    def test_agency_done(self) -> None:
        assert (
            self.protocol.agency(LocalTxSubmissionState.StDone)
            == Agency.Nobody
        )

    def test_valid_messages_idle(self) -> None:
        msgs = self.protocol.valid_messages(LocalTxSubmissionState.StIdle)
        assert LtsMsgSubmitTx in msgs
        assert LtsMsgDone in msgs
        assert len(msgs) == 2

    def test_valid_messages_busy(self) -> None:
        msgs = self.protocol.valid_messages(LocalTxSubmissionState.StBusy)
        assert LtsMsgAcceptTx in msgs
        assert LtsMsgRejectTx in msgs
        assert len(msgs) == 2

    def test_valid_messages_done(self) -> None:
        msgs = self.protocol.valid_messages(LocalTxSubmissionState.StDone)
        assert len(msgs) == 0


# ---------------------------------------------------------------------------
# Typed message wrapper tests
# ---------------------------------------------------------------------------


class TestTypedMessages:
    """Verify typed message wrappers carry correct state transitions."""

    def test_lts_msg_submit_tx(self) -> None:
        msg = LtsMsgSubmitTx(era_id=6, tx_bytes=b"\x01\x02")
        assert msg.from_state == LocalTxSubmissionState.StIdle
        assert msg.to_state == LocalTxSubmissionState.StBusy
        assert msg.era_id == 6
        assert msg.tx_bytes == b"\x01\x02"
        assert msg.inner == MsgSubmitTx(era_id=6, tx_bytes=b"\x01\x02")

    def test_lts_msg_accept_tx(self) -> None:
        msg = LtsMsgAcceptTx()
        assert msg.from_state == LocalTxSubmissionState.StBusy
        assert msg.to_state == LocalTxSubmissionState.StIdle
        assert msg.inner == MsgAcceptTx()

    def test_lts_msg_reject_tx(self) -> None:
        reason = cbor2.dumps("bad tx")
        msg = LtsMsgRejectTx(reason=reason)
        assert msg.from_state == LocalTxSubmissionState.StBusy
        assert msg.to_state == LocalTxSubmissionState.StIdle
        assert msg.reason == reason
        assert msg.inner == MsgRejectTx(reason=reason)

    def test_lts_msg_done(self) -> None:
        msg = LtsMsgDone()
        assert msg.from_state == LocalTxSubmissionState.StIdle
        assert msg.to_state == LocalTxSubmissionState.StDone
        assert msg.inner == MsgDone()


# ---------------------------------------------------------------------------
# Codec tests
# ---------------------------------------------------------------------------


class TestLocalTxSubmissionCodec:
    """Verify the codec encodes and decodes correctly."""

    def setup_method(self) -> None:
        self.codec = LocalTxSubmissionCodec()

    def test_encode_submit_tx(self) -> None:
        msg = LtsMsgSubmitTx(era_id=6, tx_bytes=b"\x01\x02")
        encoded = self.codec.encode(msg)
        assert isinstance(encoded, bytes)
        assert len(encoded) > 0

    def test_encode_accept_tx(self) -> None:
        msg = LtsMsgAcceptTx()
        encoded = self.codec.encode(msg)
        assert isinstance(encoded, bytes)

    def test_encode_reject_tx(self) -> None:
        msg = LtsMsgRejectTx(reason=cbor2.dumps("error"))
        encoded = self.codec.encode(msg)
        assert isinstance(encoded, bytes)

    def test_encode_done(self) -> None:
        msg = LtsMsgDone()
        encoded = self.codec.encode(msg)
        assert isinstance(encoded, bytes)

    def test_round_trip_submit_tx(self) -> None:
        original = LtsMsgSubmitTx(era_id=6, tx_bytes=b"\x01\x02\x03")
        encoded = self.codec.encode(original)
        decoded = self.codec.decode(encoded)
        assert isinstance(decoded, LtsMsgSubmitTx)
        assert decoded.era_id == original.era_id
        assert decoded.tx_bytes == original.tx_bytes

    def test_round_trip_accept_tx(self) -> None:
        original = LtsMsgAcceptTx()
        encoded = self.codec.encode(original)
        decoded = self.codec.decode(encoded)
        assert isinstance(decoded, LtsMsgAcceptTx)

    def test_round_trip_reject_tx(self) -> None:
        reason = cbor2.dumps({"error": "insufficient funds"})
        original = LtsMsgRejectTx(reason=reason)
        encoded = self.codec.encode(original)
        decoded = self.codec.decode(encoded)
        assert isinstance(decoded, LtsMsgRejectTx)
        assert cbor2.loads(decoded.reason) == cbor2.loads(original.reason)

    def test_round_trip_done(self) -> None:
        original = LtsMsgDone()
        encoded = self.codec.encode(original)
        decoded = self.codec.decode(encoded)
        assert isinstance(decoded, LtsMsgDone)

    def test_decode_preserves_state_transitions(self) -> None:
        """Decoded messages have correct from_state/to_state."""
        submit = LtsMsgSubmitTx(era_id=6, tx_bytes=b"\x01")
        decoded = self.codec.decode(self.codec.encode(submit))
        assert decoded.from_state == LocalTxSubmissionState.StIdle
        assert decoded.to_state == LocalTxSubmissionState.StBusy

        accept = LtsMsgAcceptTx()
        decoded_accept = self.codec.decode(self.codec.encode(accept))
        assert decoded_accept.from_state == LocalTxSubmissionState.StBusy
        assert decoded_accept.to_state == LocalTxSubmissionState.StIdle

        done = LtsMsgDone()
        decoded_done = self.codec.decode(self.codec.encode(done))
        assert decoded_done.from_state == LocalTxSubmissionState.StIdle
        assert decoded_done.to_state == LocalTxSubmissionState.StDone

    @given(
        era_id=st.integers(min_value=0, max_value=10),
        tx_bytes=st.binary(min_size=1, max_size=500),
    )
    @settings(max_examples=200)
    def test_hypothesis_round_trip_submit_tx(
        self, era_id: int, tx_bytes: bytes
    ) -> None:
        """Property: encode->decode is identity for submit messages."""
        original = LtsMsgSubmitTx(era_id=era_id, tx_bytes=tx_bytes)
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LtsMsgSubmitTx)
        assert decoded.era_id == era_id
        assert decoded.tx_bytes == tx_bytes

    @given(reason_str=st.text(max_size=100))
    @settings(max_examples=100)
    def test_hypothesis_round_trip_reject_tx(self, reason_str: str) -> None:
        """Property: encode->decode preserves rejection reason."""
        reason = cbor2.dumps(reason_str)
        original = LtsMsgRejectTx(reason=reason)
        decoded = self.codec.decode(self.codec.encode(original))
        assert isinstance(decoded, LtsMsgRejectTx)
        assert cbor2.loads(decoded.reason) == reason_str


# ---------------------------------------------------------------------------
# FSM transition tests
# ---------------------------------------------------------------------------


class TestFSMTransitions:
    """Verify the full state machine transition graph."""

    def setup_method(self) -> None:
        self.protocol = LocalTxSubmissionProtocol()

    def test_idle_to_busy_via_submit(self) -> None:
        msg = LtsMsgSubmitTx(era_id=6, tx_bytes=b"\x01")
        assert msg.from_state == LocalTxSubmissionState.StIdle
        assert msg.to_state == LocalTxSubmissionState.StBusy
        assert self.protocol.agency(msg.from_state) == Agency.Client

    def test_busy_to_idle_via_accept(self) -> None:
        msg = LtsMsgAcceptTx()
        assert msg.from_state == LocalTxSubmissionState.StBusy
        assert msg.to_state == LocalTxSubmissionState.StIdle
        assert self.protocol.agency(msg.from_state) == Agency.Server

    def test_busy_to_idle_via_reject(self) -> None:
        msg = LtsMsgRejectTx(reason=cbor2.dumps("err"))
        assert msg.from_state == LocalTxSubmissionState.StBusy
        assert msg.to_state == LocalTxSubmissionState.StIdle
        assert self.protocol.agency(msg.from_state) == Agency.Server

    def test_idle_to_done_via_msg_done(self) -> None:
        msg = LtsMsgDone()
        assert msg.from_state == LocalTxSubmissionState.StIdle
        assert msg.to_state == LocalTxSubmissionState.StDone
        assert self.protocol.agency(msg.from_state) == Agency.Client

    def test_done_is_terminal(self) -> None:
        assert (
            self.protocol.agency(LocalTxSubmissionState.StDone)
            == Agency.Nobody
        )
        assert (
            len(self.protocol.valid_messages(LocalTxSubmissionState.StDone))
            == 0
        )

    def test_full_submit_accept_done_cycle(self) -> None:
        """Walk through submit -> accept -> done cycle."""
        state = self.protocol.initial_state()
        assert state == LocalTxSubmissionState.StIdle

        submit = LtsMsgSubmitTx(era_id=6, tx_bytes=b"\x01")
        assert submit.from_state == state
        state = submit.to_state
        assert state == LocalTxSubmissionState.StBusy

        accept = LtsMsgAcceptTx()
        assert accept.from_state == state
        state = accept.to_state
        assert state == LocalTxSubmissionState.StIdle

        done = LtsMsgDone()
        assert done.from_state == state
        state = done.to_state
        assert state == LocalTxSubmissionState.StDone
        assert self.protocol.agency(state) == Agency.Nobody

    def test_full_submit_reject_done_cycle(self) -> None:
        """Walk through submit -> reject -> done cycle."""
        state = self.protocol.initial_state()

        submit = LtsMsgSubmitTx(era_id=5, tx_bytes=b"\xff")
        state = submit.to_state

        reject = LtsMsgRejectTx(reason=cbor2.dumps("bad"))
        assert reject.from_state == state
        state = reject.to_state
        assert state == LocalTxSubmissionState.StIdle

        done = LtsMsgDone()
        state = done.to_state
        assert state == LocalTxSubmissionState.StDone

    def test_multiple_submit_cycles(self) -> None:
        """Multiple submit/accept before done is valid."""
        state = self.protocol.initial_state()

        for i in range(5):
            submit = LtsMsgSubmitTx(era_id=6, tx_bytes=bytes([i]))
            assert submit.from_state == state
            state = submit.to_state
            assert state == LocalTxSubmissionState.StBusy

            accept = LtsMsgAcceptTx()
            assert accept.from_state == state
            state = accept.to_state
            assert state == LocalTxSubmissionState.StIdle

        done = LtsMsgDone()
        assert done.from_state == state
        state = done.to_state
        assert state == LocalTxSubmissionState.StDone


# ---------------------------------------------------------------------------
# Server tests
# ---------------------------------------------------------------------------


class TestLocalTxSubmissionServer:
    """Test the high-level LocalTxSubmissionServer."""

    def _make_server(self) -> tuple[LocalTxSubmissionServer, MagicMock]:
        runner = MagicMock()
        runner.state = LocalTxSubmissionState.StIdle
        runner.is_done = False
        runner.send_message = AsyncMock()
        runner.recv_message = AsyncMock()
        server = LocalTxSubmissionServer(runner)
        return server, runner

    @pytest.mark.asyncio
    async def test_recv_submit_tx(self) -> None:
        server, runner = self._make_server()
        runner.recv_message.return_value = LtsMsgSubmitTx(
            era_id=6, tx_bytes=b"\x01"
        )
        msg = await server.recv_client_message()
        assert isinstance(msg, LtsMsgSubmitTx)
        assert msg.era_id == 6

    @pytest.mark.asyncio
    async def test_recv_done(self) -> None:
        server, runner = self._make_server()
        runner.recv_message.return_value = LtsMsgDone()
        msg = await server.recv_client_message()
        assert isinstance(msg, LtsMsgDone)

    @pytest.mark.asyncio
    async def test_accept_tx(self) -> None:
        server, runner = self._make_server()
        await server.accept_tx()
        runner.send_message.assert_called_once()
        sent = runner.send_message.call_args[0][0]
        assert isinstance(sent, LtsMsgAcceptTx)

    @pytest.mark.asyncio
    async def test_reject_tx(self) -> None:
        server, runner = self._make_server()
        reason = cbor2.dumps("error")
        await server.reject_tx(reason)
        runner.send_message.assert_called_once()
        sent = runner.send_message.call_args[0][0]
        assert isinstance(sent, LtsMsgRejectTx)
        assert sent.reason == reason

    def test_state_property(self) -> None:
        server, runner = self._make_server()
        runner.state = LocalTxSubmissionState.StBusy
        assert server.state == LocalTxSubmissionState.StBusy

    def test_is_done_property(self) -> None:
        server, runner = self._make_server()
        runner.is_done = True
        assert server.is_done is True


# ---------------------------------------------------------------------------
# Direct client-server pairing test
# ---------------------------------------------------------------------------


class TestDirectClientServer:
    """Direct client-server pairing via message passing.

    Follows the Haskell prop_direct test pattern.
    """

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
    async def test_submit_accept_done(self) -> None:
        """Client submits a tx, server accepts, client sends done."""
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner
        from vibe.cardano.network.local_txsubmission_protocol import (
            LocalTxSubmissionProtocol,
            LocalTxSubmissionCodec,
            LocalTxSubmissionServer,
        )

        client_ch, server_ch = self._make_connected_channels()

        # Client side (Initiator)
        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=LocalTxSubmissionProtocol(),
            codec=LocalTxSubmissionCodec(),
            channel=client_ch,
        )

        # Server side (Responder)
        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=LocalTxSubmissionProtocol(),
            codec=LocalTxSubmissionCodec(),
            channel=server_ch,
        )
        server = LocalTxSubmissionServer(server_runner)

        async def server_task() -> str:
            msg = await server.recv_client_message()
            assert isinstance(msg, LtsMsgSubmitTx)
            assert msg.era_id == 6
            await server.accept_tx()
            msg2 = await server.recv_client_message()
            assert isinstance(msg2, LtsMsgDone)
            return "accepted"

        task = asyncio.create_task(server_task())

        # Client sends submit
        await client_runner.send_message(
            LtsMsgSubmitTx(era_id=6, tx_bytes=b"\x84\xa4")
        )
        # Client receives accept
        response = await client_runner.recv_message()
        assert isinstance(response, LtsMsgAcceptTx)
        # Client sends done
        await client_runner.send_message(LtsMsgDone())

        result = await task
        assert result == "accepted"

    @pytest.mark.asyncio
    async def test_submit_reject_done(self) -> None:
        """Client submits a tx, server rejects, client sends done."""
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner
        from vibe.cardano.network.local_txsubmission_protocol import (
            LocalTxSubmissionProtocol,
            LocalTxSubmissionCodec,
            LocalTxSubmissionServer,
        )

        client_ch, server_ch = self._make_connected_channels()

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=LocalTxSubmissionProtocol(),
            codec=LocalTxSubmissionCodec(),
            channel=client_ch,
        )
        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=LocalTxSubmissionProtocol(),
            codec=LocalTxSubmissionCodec(),
            channel=server_ch,
        )
        server = LocalTxSubmissionServer(server_runner)

        reason = cbor2.dumps("insufficient funds")

        async def server_task() -> str:
            msg = await server.recv_client_message()
            assert isinstance(msg, LtsMsgSubmitTx)
            await server.reject_tx(reason)
            msg2 = await server.recv_client_message()
            assert isinstance(msg2, LtsMsgDone)
            return "rejected"

        task = asyncio.create_task(server_task())

        await client_runner.send_message(
            LtsMsgSubmitTx(era_id=6, tx_bytes=b"\xff")
        )
        response = await client_runner.recv_message()
        assert isinstance(response, LtsMsgRejectTx)
        assert cbor2.loads(response.reason) == "insufficient funds"

        await client_runner.send_message(LtsMsgDone())
        result = await task
        assert result == "rejected"

    @pytest.mark.asyncio
    async def test_immediate_done(self) -> None:
        """Client sends done immediately without submitting."""
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner
        from vibe.cardano.network.local_txsubmission_protocol import (
            LocalTxSubmissionProtocol,
            LocalTxSubmissionCodec,
            LocalTxSubmissionServer,
        )

        client_ch, server_ch = self._make_connected_channels()

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=LocalTxSubmissionProtocol(),
            codec=LocalTxSubmissionCodec(),
            channel=client_ch,
        )
        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=LocalTxSubmissionProtocol(),
            codec=LocalTxSubmissionCodec(),
            channel=server_ch,
        )
        server = LocalTxSubmissionServer(server_runner)

        async def server_task() -> str:
            msg = await server.recv_client_message()
            assert isinstance(msg, LtsMsgDone)
            return "done"

        task = asyncio.create_task(server_task())
        await client_runner.send_message(LtsMsgDone())
        result = await task
        assert result == "done"

    @given(
        txs=st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=10),
                st.binary(min_size=1, max_size=100),
                st.booleans(),  # accept or reject
            ),
            min_size=1,
            max_size=5,
        )
    )
    @settings(max_examples=30)
    @pytest.mark.asyncio
    async def test_hypothesis_multi_submit(
        self, txs: list[tuple[int, bytes, bool]]
    ) -> None:
        """Property: any sequence of submits with accept/reject roundtrips."""
        from vibe.core.protocols.agency import PeerRole
        from vibe.core.protocols.runner import ProtocolRunner
        from vibe.cardano.network.local_txsubmission_protocol import (
            LocalTxSubmissionProtocol,
            LocalTxSubmissionCodec,
            LocalTxSubmissionServer,
        )

        client_ch, server_ch = self._make_connected_channels()

        client_runner = ProtocolRunner(
            role=PeerRole.Initiator,
            protocol=LocalTxSubmissionProtocol(),
            codec=LocalTxSubmissionCodec(),
            channel=client_ch,
        )
        server_runner = ProtocolRunner(
            role=PeerRole.Responder,
            protocol=LocalTxSubmissionProtocol(),
            codec=LocalTxSubmissionCodec(),
            channel=server_ch,
        )
        server = LocalTxSubmissionServer(server_runner)

        async def server_task() -> list[bool]:
            results = []
            for _ in range(len(txs)):
                msg = await server.recv_client_message()
                assert isinstance(msg, LtsMsgSubmitTx)
                era_id, tx_bytes, should_accept = txs[len(results)]
                if should_accept:
                    await server.accept_tx()
                    results.append(True)
                else:
                    await server.reject_tx(cbor2.dumps("rejected"))
                    results.append(False)
            msg_done = await server.recv_client_message()
            assert isinstance(msg_done, LtsMsgDone)
            return results

        task = asyncio.create_task(server_task())

        for era_id, tx_bytes, should_accept in txs:
            await client_runner.send_message(
                LtsMsgSubmitTx(era_id=era_id, tx_bytes=tx_bytes)
            )
            response = await client_runner.recv_message()
            if should_accept:
                assert isinstance(response, LtsMsgAcceptTx)
            else:
                assert isinstance(response, LtsMsgRejectTx)

        await client_runner.send_message(LtsMsgDone())
        results = await task
        assert len(results) == len(txs)
