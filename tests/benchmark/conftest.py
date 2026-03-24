"""Shared fixtures for benchmark tests.

Provides synthetic CBOR blocks for each Cardano era and common
test data used across benchmark modules.
"""

from __future__ import annotations

import cbor2pure as cbor2
import pytest

# ---------------------------------------------------------------------------
# Synthetic CBOR block builders — one per era
# ---------------------------------------------------------------------------


def _random_bytes(n: int, seed: int = 42) -> bytes:
    """Deterministic pseudo-random bytes for reproducible benchmarks."""
    import random

    rng = random.Random(seed)
    return bytes(rng.getrandbits(8) for _ in range(n))


def _make_vrf_cert() -> list:
    """Synthetic VRF certificate: [output_bytes, proof_bytes]."""
    return [_random_bytes(64, seed=10), _random_bytes(80, seed=11)]


def _make_op_cert() -> list:
    """Synthetic operational certificate as CBOR array."""
    return [
        _random_bytes(32, seed=20),  # hot_vkey (kes_vk)
        1,  # sequence_number
        0,  # kes_period
        _random_bytes(64, seed=21),  # sigma (Ed25519 signature)
    ]


def _make_shelley_header_body(slot: int = 1000, block_number: int = 100) -> list:
    """Shelley-era header body (15 inline fields, two VRF certs)."""
    return [
        block_number,  # [0] block_number
        slot,  # [1] slot
        _random_bytes(32, seed=1),  # [2] prev_hash
        _random_bytes(32, seed=2),  # [3] issuer_vkey
        _random_bytes(32, seed=3),  # [4] vrf_vkey
        _make_vrf_cert(),  # [5] nonce_vrf
        _make_vrf_cert(),  # [6] leader_vrf
        4096,  # [7] block_body_size
        _random_bytes(32, seed=4),  # [8] block_body_hash
        _random_bytes(32, seed=5),  # [9] op_cert hot_vkey
        1,  # [10] op_cert sequence_number
        0,  # [11] op_cert kes_period
        _random_bytes(64, seed=6),  # [12] op_cert sigma
        2,  # [13] protocol_version major
        0,  # [14] protocol_version minor
    ]


def _make_babbage_header_body(slot: int = 5000, block_number: int = 500) -> list:
    """Babbage/Conway header body (10 fields, single vrf_result, nested arrays)."""
    return [
        block_number,  # [0] block_number
        slot,  # [1] slot
        _random_bytes(32, seed=1),  # [2] prev_hash
        _random_bytes(32, seed=2),  # [3] issuer_vkey
        _random_bytes(32, seed=3),  # [4] vrf_vkey
        _make_vrf_cert(),  # [5] vrf_result
        4096,  # [6] block_body_size
        _random_bytes(32, seed=4),  # [7] block_body_hash
        _make_op_cert(),  # [8] operational_cert [kes_vk, n, c0, sig]
        [10, 0],  # [9] protocol_version [major, minor]
    ]


def _make_block_body() -> list:
    """Minimal block body: [tx_bodies, tx_witnesses, auxiliary, invalid_txs]."""
    return [[], [], None, []]


def _build_era_block(era_tag: int, header_body_items: list) -> bytes:
    """Build a tagged CBOR block for the given era.

    Wire format: CBORTag(era_tag, [header, body_parts...])
    header = [header_body_items, kes_signature_bytes]
    """
    kes_sig = _random_bytes(448, seed=99)  # KES signature (Sum6KES)
    header = [header_body_items, kes_sig]
    body = _make_block_body()
    # Full block = [header, tx_bodies, tx_witnesses, aux_data]
    block_array = [header] + body
    tagged = cbor2.CBORTag(era_tag, block_array)
    return cbor2.dumps(tagged)


def _build_byron_block() -> bytes:
    """Build a minimal Byron main block (tag 0).

    Byron blocks have a different structure from Shelley+:
    [header, body, extra]  where header = [consensus_data, extra_data]
    We build a plausible-enough structure for CBOR decode benchmarking.
    """
    # Byron header: [[prev_hash, proof, consensus, extra], body_proof]
    header = [
        _random_bytes(32, seed=30),  # prev_hash
        [  # consensus data
            0,  # slot
            _random_bytes(32, seed=31),  # issuer pk
            [0, _random_bytes(64, seed=32)],  # dlg_cert placeholder
            _random_bytes(64, seed=33),  # signature
        ],
        _random_bytes(32, seed=34),  # extra data
    ]
    body = [[], {}, {}]  # tx_payload, ssc_payload, dlg_payload
    extra = [{}]
    block_array = [header, body, extra]
    tagged = cbor2.CBORTag(0, block_array)
    return cbor2.dumps(tagged)


def _build_byron_ebb() -> bytes:
    """Build a minimal Byron EBB (tag 1)."""
    header = [
        0,  # protocol magic
        _random_bytes(32, seed=40),  # prev_hash
        _random_bytes(32, seed=41),  # body_proof
        [0, 0],  # consensus = [epoch, difficulty]
        b"",  # extra_data
    ]
    body = []
    block_array = [header, body]
    tagged = cbor2.CBORTag(1, block_array)
    return cbor2.dumps(tagged)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def byron_block_cbor() -> bytes:
    """Synthetic Byron main block CBOR."""
    return _build_byron_block()


@pytest.fixture(scope="session")
def byron_ebb_cbor() -> bytes:
    """Synthetic Byron EBB CBOR."""
    return _build_byron_ebb()


@pytest.fixture(scope="session")
def shelley_block_cbor() -> bytes:
    """Synthetic Shelley block CBOR (tag 2)."""
    return _build_era_block(2, _make_shelley_header_body(slot=1000, block_number=100))


@pytest.fixture(scope="session")
def allegra_block_cbor() -> bytes:
    """Synthetic Allegra block CBOR (tag 3)."""
    return _build_era_block(3, _make_shelley_header_body(slot=2000, block_number=200))


@pytest.fixture(scope="session")
def mary_block_cbor() -> bytes:
    """Synthetic Mary block CBOR (tag 4)."""
    return _build_era_block(4, _make_shelley_header_body(slot=3000, block_number=300))


@pytest.fixture(scope="session")
def alonzo_block_cbor() -> bytes:
    """Synthetic Alonzo block CBOR (tag 5)."""
    return _build_era_block(5, _make_shelley_header_body(slot=4000, block_number=400))


@pytest.fixture(scope="session")
def babbage_block_cbor() -> bytes:
    """Synthetic Babbage block CBOR (tag 6)."""
    return _build_era_block(6, _make_babbage_header_body(slot=5000, block_number=500))


@pytest.fixture(scope="session")
def conway_block_cbor() -> bytes:
    """Synthetic Conway block CBOR (tag 7)."""
    return _build_era_block(7, _make_babbage_header_body(slot=6000, block_number=600))


@pytest.fixture(scope="session")
def all_era_blocks(
    byron_block_cbor: bytes,
    byron_ebb_cbor: bytes,
    shelley_block_cbor: bytes,
    allegra_block_cbor: bytes,
    mary_block_cbor: bytes,
    alonzo_block_cbor: bytes,
    babbage_block_cbor: bytes,
    conway_block_cbor: bytes,
) -> dict[str, bytes]:
    """All era blocks keyed by era name."""
    return {
        "byron_main": byron_block_cbor,
        "byron_ebb": byron_ebb_cbor,
        "shelley": shelley_block_cbor,
        "allegra": allegra_block_cbor,
        "mary": mary_block_cbor,
        "alonzo": alonzo_block_cbor,
        "babbage": babbage_block_cbor,
        "conway": conway_block_cbor,
    }
