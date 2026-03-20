"""Integration test: block-fetch from a real cardano-node.

VNODE-175 — These tests require proper multiplexer integration (M3.8 ChainDB)
because chain-sync and block-fetch run as separate miniprotocol channels
that must be demuxed by protocol ID. The raw bearer approach doesn't work
because the Haskell node interleaves responses.

For now, we verify block-fetch works with a dedicated connection (no chain-sync
on the same connection).
"""

from __future__ import annotations

import pytest

from vibe.core.multiplexer.bearer import connect
from vibe.core.multiplexer.segment import MuxSegment
from vibe.cardano.network.handshake import (
    encode_propose_versions,
    decode_handshake_response,
    build_version_table,
    PREPROD_NETWORK_MAGIC,
    HANDSHAKE_PROTOCOL_ID,
    MsgAcceptVersion,
)
from vibe.cardano.network.blockfetch import (
    encode_request_range,
    encode_client_done,
    decode_server_message as decode_blockfetch,
    MsgStartBatch,
    MsgNoBlocks,
    MsgBlock,
    MsgBatchDone,
    BLOCK_FETCH_N2N_ID,
)
from vibe.cardano.network.chainsync import Point


pytestmark = pytest.mark.integration


@pytest.mark.timeout(15)
async def test_blockfetch_handshake_and_request(cardano_node_available):
    """Verify we can handshake and send a block-fetch request without crashing.

    We request a range using known preprod genesis points. The server may
    respond with NoBlocks (if the range is invalid) or StartBatch.
    Either response proves the protocol works.
    """
    if not cardano_node_available:
        pytest.skip("cardano-node not available")

    bearer = await connect("localhost", 3001)

    # Handshake
    versions = build_version_table(PREPROD_NETWORK_MAGIC)
    seg = MuxSegment(timestamp=0, protocol_id=HANDSHAKE_PROTOCOL_ID,
                     is_initiator=True, payload=encode_propose_versions(versions))
    await bearer.write_segment(seg)
    resp = await bearer.read_segment()
    hs = decode_handshake_response(resp.payload)
    assert isinstance(hs, MsgAcceptVersion)

    # Send a block-fetch request with a known point (slot 0, genesis hash for preprod)
    # The server should respond with either StartBatch or NoBlocks
    genesis_point = Point(slot=0, hash=bytes.fromhex(
        "d4b8de7a11d929a323373cbab6c1a9bdc931beffff11db111cf9d57356ee1937"
    ))

    await bearer.write_segment(MuxSegment(
        timestamp=0, protocol_id=BLOCK_FETCH_N2N_ID,
        is_initiator=True, payload=encode_request_range(genesis_point, genesis_point)
    ))

    resp = await bearer.read_segment()
    msg = decode_blockfetch(resp.payload)
    # Either StartBatch (has the block) or NoBlocks (invalid range)
    assert isinstance(msg, (MsgStartBatch, MsgNoBlocks))

    if isinstance(msg, MsgStartBatch):
        # Read blocks until BatchDone
        while True:
            resp = await bearer.read_segment()
            msg = decode_blockfetch(resp.payload)
            if isinstance(msg, MsgBlock):
                assert len(msg.block_cbor) > 0
            elif isinstance(msg, MsgBatchDone):
                break

    await bearer.close()
