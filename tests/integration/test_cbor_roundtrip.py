"""Test CBOR roundtrip preservation for block hashes.

Verifies that blocks received via block-fetch produce the same hash
as headers received via chain-sync — ensuring our CBOR decode/re-encode
pipeline doesn't alter block hashes.

Requires a running Haskell node on localhost:30001.
"""

import asyncio
import hashlib

import pytest

import cbor2pure as cbor2

from vibe.core.multiplexer import Bearer, Multiplexer
from vibe.cardano.network.handshake_protocol import run_handshake_client
from vibe.cardano.network.blockfetch_protocol import (
    BlockFetchClient,
    BlockFetchProtocol,
    BlockFetchCodec,
)
from vibe.cardano.network.chainsync_protocol import (
    ChainSyncProtocol,
    ChainSyncCodec,
    ChainSyncClient,
    CsMsgRollForward,
)
from vibe.core.protocols.runner import ProtocolRunner
from vibe.core.protocols.agency import PeerRole
from vibe.cardano.network.chainsync import ORIGIN, Point


@pytest.mark.integration
@pytest.mark.asyncio
async def test_block_hash_roundtrip():
    """Block-fetch block hash must match chain-sync header hash."""
    try:
        r, w = await asyncio.wait_for(
            asyncio.open_connection("localhost", 30001), timeout=3
        )
    except (ConnectionRefusedError, TimeoutError):
        pytest.skip("No Haskell node on localhost:30001")

    bearer = Bearer(r, w)
    mux = Multiplexer(bearer, is_initiator=True)
    ch0 = mux.add_protocol(0)
    ch2 = mux.add_protocol(2)
    ch3 = mux.add_protocol(3)
    mux_task = asyncio.create_task(mux.run())

    try:
        await run_handshake_client(ch0, 42)

        cs = ChainSyncClient(
            ProtocolRunner(
                PeerRole.Initiator, ChainSyncProtocol(), ChainSyncCodec(), ch2
            )
        )
        await cs.find_intersection([ORIGIN])
        await cs.request_next()  # rollback

        # Get 3 headers and their hashes
        cs_points = []
        for _ in range(3):
            resp = await cs.request_next()
            assert isinstance(resp, CsMsgRollForward)
            header_bytes = resp.header[1].value
            inner = cbor2.loads(header_bytes)
            slot = inner[0][1]
            block_hash = hashlib.blake2b(header_bytes, digest_size=32).digest()
            cs_points.append((slot, block_hash, header_bytes))

        # Block-fetch the same blocks
        bf = BlockFetchClient(
            ProtocolRunner(
                PeerRole.Initiator, BlockFetchProtocol(), BlockFetchCodec(), ch3
            )
        )
        blocks = await asyncio.wait_for(
            bf.request_range(
                Point(slot=cs_points[0][0], hash=cs_points[0][1]),
                Point(slot=cs_points[-1][0], hash=cs_points[-1][1]),
            ),
            timeout=15,
        )

        assert blocks is not None, "Block-fetch returned NoBlocks"
        assert len(blocks) == 3, f"Expected 3 blocks, got {len(blocks)}"

        # For each block, verify hash matches chain-sync
        for i, block_cbor in enumerate(blocks):
            decoded = cbor2.loads(block_cbor)

            # Unwrap tag-24
            if hasattr(decoded, "tag") and decoded.tag == 24:
                inner_bytes = decoded.value
                inner = cbor2.loads(inner_bytes)
            else:
                inner = decoded

            # [era_int, [header, tx_bodies, ...]]
            if isinstance(inner, list) and isinstance(inner[0], int):
                block_body = inner[1]
            else:
                block_body = inner

            bf_header = block_body[0]
            bf_header_cbor = cbor2.dumps(bf_header)
            bf_hash = hashlib.blake2b(bf_header_cbor, digest_size=32).digest()

            cs_slot, cs_hash, cs_header_bytes = cs_points[i]

            # The critical assertion: hashes must match
            assert bf_hash == cs_hash, (
                f"Block {i} hash mismatch: "
                f"chain-sync={cs_hash.hex()[:16]}, "
                f"block-fetch={bf_hash.hex()[:16]}"
            )

            # Header bytes should also match
            assert bf_header_cbor == cs_header_bytes, (
                f"Block {i} header bytes differ: "
                f"cs={len(cs_header_bytes)}B, bf={len(bf_header_cbor)}B"
            )

    finally:
        await mux.close()
        mux_task.cancel()


@pytest.mark.asyncio
async def test_cbor_roundtrip_preserves_bytes():
    """cbor2pure decode → re-encode preserves bytes exactly."""
    # Test with various CBOR structures typical in Cardano blocks
    test_cases = [
        # Simple array
        cbor2.dumps([1, 2, 3]),
        # Nested arrays
        cbor2.dumps([[1, 2], [3, 4], None, []]),
        # CBOR tag
        cbor2.dumps(cbor2.CBORTag(6, [[0, 100, None], b"\x00" * 32])),
        # Bytes
        cbor2.dumps(b"\xde\xad\xbe\xef" * 100),
        # Mixed
        cbor2.dumps([cbor2.CBORTag(24, b"\x82\x01\x02"), 42, b"\xff"]),
    ]

    for i, original in enumerate(test_cases):
        decoded = cbor2.loads(original)
        reencoded = cbor2.dumps(decoded)
        assert original == reencoded, (
            f"Case {i}: roundtrip changed bytes "
            f"({len(original)}B → {len(reencoded)}B)"
        )
        orig_hash = hashlib.blake2b(original, digest_size=32).digest()
        re_hash = hashlib.blake2b(reencoded, digest_size=32).digest()
        assert orig_hash == re_hash, f"Case {i}: hash changed on roundtrip"
