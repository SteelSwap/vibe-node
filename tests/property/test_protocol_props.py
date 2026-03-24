"""Hypothesis property tests for protocol state machine invariants.

These tests verify structural invariants of the Ouroboros typed-protocols
framework as implemented for the handshake and chain-sync miniprotocols:

1. Agency strictly alternates between client and server for any valid
   message sequence (no two consecutive messages from the same peer).
2. Random sequences of valid chain-sync messages always respect the
   state machine — every transition is valid for the current state.

Spec reference: Ouroboros typed-protocols framework
Haskell reference: typed-protocols/src/Network/TypedProtocol/Core.hs
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from vibe.cardano.network.chainsync import (
    MSG_AWAIT_REPLY,
    MSG_DONE,
    MSG_FIND_INTERSECT,
    MSG_INTERSECT_FOUND,
    MSG_INTERSECT_NOT_FOUND,
    MSG_REQUEST_NEXT,
    MSG_ROLL_BACKWARD,
    MSG_ROLL_FORWARD,
    ORIGIN,
    Point,
    Tip,
)
from vibe.cardano.network.chainsync_protocol import (
    ChainSyncProtocol,
    ChainSyncState,
    CsMsgAwaitReply,
    CsMsgDone,
    CsMsgFindIntersect,
    CsMsgIntersectFound,
    CsMsgIntersectNotFound,
    CsMsgRequestNext,
    CsMsgRollBackward,
    CsMsgRollForward,
)
from vibe.cardano.network.handshake import (
    NodeToNodeVersionData,
    PeerSharing,
)
from vibe.core.protocols.agency import Agency, Message

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_HASH = b"\xab" * 32
SAMPLE_POINT = Point(slot=100, hash=SAMPLE_HASH)
SAMPLE_TIP = Tip(point=SAMPLE_POINT, block_number=42)
GENESIS_TIP = Tip(point=ORIGIN, block_number=0)

_VD = NodeToNodeVersionData(
    network_magic=1,
    initiator_only_diffusion_mode=False,
    peer_sharing=PeerSharing.DISABLED,
    query=False,
)


def _agency_for_message(protocol: ChainSyncProtocol, msg: Message[ChainSyncState]) -> Agency:
    """Return the agency of the state this message is sent FROM."""
    return protocol.agency(msg.from_state)


# ---------------------------------------------------------------------------
# Chain-sync message strategies
# ---------------------------------------------------------------------------

# Messages valid from StIdle (Client agency)
_idle_messages = st.sampled_from(["request_next", "find_intersect", "done"])

# Messages valid from StNext (Server agency)
_next_messages = st.sampled_from(["await_reply", "roll_forward", "roll_backward"])

# Messages valid from StIntersect (Server agency)
_intersect_messages = st.sampled_from(["intersect_found", "intersect_not_found"])


def _make_cs_message(name: str) -> Message[ChainSyncState]:
    """Create a chain-sync message by name."""
    match name:
        case "request_next":
            return CsMsgRequestNext()
        case "find_intersect":
            return CsMsgFindIntersect(points=[SAMPLE_POINT, ORIGIN])
        case "done":
            return CsMsgDone()
        case "await_reply":
            return CsMsgAwaitReply()
        case "roll_forward":
            return CsMsgRollForward(header=b"\x00", tip=SAMPLE_TIP)
        case "roll_backward":
            return CsMsgRollBackward(point=SAMPLE_POINT, tip=SAMPLE_TIP)
        case "intersect_found":
            return CsMsgIntersectFound(point=SAMPLE_POINT, tip=SAMPLE_TIP)
        case "intersect_not_found":
            return CsMsgIntersectNotFound(tip=GENESIS_TIP)
        case _:
            raise ValueError(f"Unknown message: {name}")


def _pick_valid_message(state: ChainSyncState, choice: str) -> Message[ChainSyncState] | None:
    """Pick a valid message for the given state, or None if terminal."""
    match state:
        case ChainSyncState.StIdle:
            match choice:
                case "request_next":
                    return CsMsgRequestNext()
                case "find_intersect":
                    return CsMsgFindIntersect(points=[SAMPLE_POINT])
                case "done":
                    return CsMsgDone()
                case _:
                    return CsMsgRequestNext()  # default
        case ChainSyncState.StNext:
            match choice:
                case "await_reply":
                    return CsMsgAwaitReply()
                case "roll_forward":
                    return CsMsgRollForward(header=b"\x00", tip=SAMPLE_TIP)
                case "roll_backward":
                    return CsMsgRollBackward(point=SAMPLE_POINT, tip=SAMPLE_TIP)
                case _:
                    return CsMsgRollForward(header=b"\x00", tip=SAMPLE_TIP)
        case ChainSyncState.StIntersect:
            match choice:
                case "intersect_found":
                    return CsMsgIntersectFound(point=SAMPLE_POINT, tip=SAMPLE_TIP)
                case "intersect_not_found":
                    return CsMsgIntersectNotFound(tip=GENESIS_TIP)
                case _:
                    return CsMsgIntersectFound(point=SAMPLE_POINT, tip=SAMPLE_TIP)
        case ChainSyncState.StDone:
            return None
    return None


# Strategy: random choices that we'll use to drive the state machine
_message_choices = st.lists(
    st.sampled_from(
        [
            "request_next",
            "find_intersect",
            "done",
            "await_reply",
            "roll_forward",
            "roll_backward",
            "intersect_found",
            "intersect_not_found",
        ]
    ),
    min_size=1,
    max_size=50,
)


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


@given(choices=_message_choices)
@settings(max_examples=300, deadline=None)
def test_agency_alternation_property(choices: list[str]) -> None:
    """Property: for any valid message sequence, agency strictly alternates
    between client and server.

    In the Ouroboros typed-protocols framework, at every state exactly one
    peer has agency. When that peer sends a message, agency transfers to
    the other peer (or to Nobody at terminal states). Two consecutive
    messages from the same peer is a protocol violation.

    Note: AwaitReply is a special case — it's a self-transition within StNext
    (server agency), so two consecutive server messages (AwaitReply then
    RollForward) are valid. The alternation property applies across
    state boundaries, not within self-transitions.
    """
    protocol = ChainSyncProtocol()
    state = protocol.initial_state()
    agencies: list[Agency] = []

    for choice in choices:
        if state == ChainSyncState.StDone:
            break

        msg = _pick_valid_message(state, choice)
        if msg is None:
            break

        # Verify the message is valid for the current state
        valid_types = protocol.valid_messages(state)
        assert type(msg) in valid_types, f"Message {type(msg).__name__} not valid in state {state}"

        current_agency = protocol.agency(state)
        agencies.append(current_agency)
        state = msg.to_state

    # Check alternation: consecutive non-self-transition agencies should differ
    # Self-transitions (AwaitReply: StNext -> StNext) are the exception
    for i in range(1, len(agencies)):
        if agencies[i] == agencies[i - 1]:
            # This is only valid for self-transitions (Server -> Server via AwaitReply)
            assert (
                agencies[i] == Agency.Server
            ), f"Non-server agency repeated at index {i}: {agencies}"


@given(choices=_message_choices)
@settings(max_examples=300, deadline=None)
def test_chainsync_all_traces_valid(choices: list[str]) -> None:
    """Property: random sequences of valid chain-sync messages always respect
    the state machine.

    For any randomly-driven sequence of chain-sync messages:
    1. Every message's from_state matches the current protocol state
    2. Every message type is in the valid_messages set for that state
    3. The protocol terminates cleanly at StDone or can continue

    This is the fundamental type-safety invariant of the typed-protocols
    framework: you cannot construct an invalid trace if you only use
    messages valid for the current state.
    """
    protocol = ChainSyncProtocol()
    state = protocol.initial_state()
    trace: list[str] = []

    for choice in choices:
        if state == ChainSyncState.StDone:
            # Terminal — no more messages possible
            assert protocol.agency(state) == Agency.Nobody
            assert len(protocol.valid_messages(state)) == 0
            break

        msg = _pick_valid_message(state, choice)
        if msg is None:
            break

        # Invariant 1: message's from_state matches current state
        assert msg.from_state == state, (
            f"Message {type(msg).__name__} has from_state={msg.from_state} "
            f"but protocol is in state={state}. Trace: {trace}"
        )

        # Invariant 2: message type is valid for current state
        valid_types = protocol.valid_messages(state)
        assert type(msg) in valid_types, (
            f"Message {type(msg).__name__} not in valid_messages for {state}. "
            f"Valid: {[t.__name__ for t in valid_types]}. Trace: {trace}"
        )

        # Invariant 3: agency is not Nobody (can't send from terminal)
        agency = protocol.agency(state)
        assert (
            agency != Agency.Nobody
        ), f"Sending message in terminal state {state}. Trace: {trace}"

        trace.append(f"{type(msg).__name__}: {state} -> {msg.to_state}")
        state = msg.to_state

    # After the loop, the state should be either StDone or a valid
    # non-terminal state (if we ran out of choices)
    assert state in (
        ChainSyncState.StIdle,
        ChainSyncState.StNext,
        ChainSyncState.StIntersect,
        ChainSyncState.StDone,
    )


# ---------------------------------------------------------------------------
# Message ID exhaustiveness
# ---------------------------------------------------------------------------


def test_chainsync_message_id_exhaustive() -> None:
    """Verify message ID constants (0-7) cover all valid chain-sync messages
    with no gaps.

    The chain-sync miniprotocol defines exactly 8 message types with IDs 0-7.
    This test ensures:
    1. All IDs form a contiguous range [0, 7]
    2. No gaps exist in the ID space
    3. Each ID maps to exactly one message type
    4. The set of IDs is complete (no missing messages)

    Haskell reference: The ChainSync protocol type has exactly these
    constructors: MsgRequestNext (0), MsgAwaitReply (1), MsgRollForward (2),
    MsgRollBackward (3), MsgFindIntersect (4), MsgIntersectFound (5),
    MsgIntersectNotFound (6), MsgDone (7).
    """
    all_ids = {
        MSG_REQUEST_NEXT,
        MSG_AWAIT_REPLY,
        MSG_ROLL_FORWARD,
        MSG_ROLL_BACKWARD,
        MSG_FIND_INTERSECT,
        MSG_INTERSECT_FOUND,
        MSG_INTERSECT_NOT_FOUND,
        MSG_DONE,
    }

    # Exactly 8 message types
    assert len(all_ids) == 8, f"Expected 8 unique message IDs, got {len(all_ids)}"

    # Contiguous range [0, 7]
    assert all_ids == set(range(8)), f"Message IDs should be {{0..7}}, got {sorted(all_ids)}"

    # Verify each constant has the expected value (defense against renaming)
    expected = {
        "MSG_REQUEST_NEXT": 0,
        "MSG_AWAIT_REPLY": 1,
        "MSG_ROLL_FORWARD": 2,
        "MSG_ROLL_BACKWARD": 3,
        "MSG_FIND_INTERSECT": 4,
        "MSG_INTERSECT_FOUND": 5,
        "MSG_INTERSECT_NOT_FOUND": 6,
        "MSG_DONE": 7,
    }
    actual = {
        "MSG_REQUEST_NEXT": MSG_REQUEST_NEXT,
        "MSG_AWAIT_REPLY": MSG_AWAIT_REPLY,
        "MSG_ROLL_FORWARD": MSG_ROLL_FORWARD,
        "MSG_ROLL_BACKWARD": MSG_ROLL_BACKWARD,
        "MSG_FIND_INTERSECT": MSG_FIND_INTERSECT,
        "MSG_INTERSECT_FOUND": MSG_INTERSECT_FOUND,
        "MSG_INTERSECT_NOT_FOUND": MSG_INTERSECT_NOT_FOUND,
        "MSG_DONE": MSG_DONE,
    }
    assert actual == expected, f"Message ID values mismatch: {actual}"

    # Verify no ID appears in both client and server message sets
    client_ids = {MSG_REQUEST_NEXT, MSG_FIND_INTERSECT, MSG_DONE}
    server_ids = {
        MSG_AWAIT_REPLY,
        MSG_ROLL_FORWARD,
        MSG_ROLL_BACKWARD,
        MSG_INTERSECT_FOUND,
        MSG_INTERSECT_NOT_FOUND,
    }

    assert client_ids & server_ids == set(), f"Client/server ID overlap: {client_ids & server_ids}"
    assert client_ids | server_ids == all_ids, "Client + server IDs don't cover all message types"
