"""M6.7.4 — Forge loop end-to-end benchmark.

Measures the full block forge cycle from slot tick to block ready,
targeting < 200ms. Since VRF requires the native extension (which may
not be built), we mock the leader proof and measure the forge_block
function directly — this covers header construction, body assembly,
KES signing, CBOR encoding, and hashing.

Run: uv run pytest tests/benchmark/test_bench_forge.py -v --benchmark-only
"""

from __future__ import annotations

import hashlib
import os

import cbor2pure as cbor2
import pytest

from vibe.cardano.crypto.kes import (
    CARDANO_KES_DEPTH,
    KesSecretKey,
    kes_derive_vk,
    kes_keygen_from_seed,
    kes_sign,
)
from vibe.cardano.crypto.ocert import OperationalCert
from vibe.cardano.forge.block import forge_block
from vibe.cardano.forge.leader import LeaderProof


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _random_bytes(n: int, seed: int = 0) -> bytes:
    """Deterministic pseudo-random bytes."""
    import random
    rng = random.Random(seed)
    return bytes(rng.getrandbits(8) for _ in range(n))


@pytest.fixture(scope="session")
def kes_key() -> KesSecretKey:
    """KES key at mainnet depth 6 for forge benchmarks."""
    return kes_keygen_from_seed(b"forge-bench-kes-seed-32-bytes!!!", depth=CARDANO_KES_DEPTH)


@pytest.fixture(scope="session")
def pool_vk() -> bytes:
    """Pool cold verification key (32 bytes)."""
    return _random_bytes(32, seed=1)


@pytest.fixture(scope="session")
def vrf_vk() -> bytes:
    """VRF verification key (32 bytes)."""
    return _random_bytes(32, seed=2)


@pytest.fixture(scope="session")
def ocert(kes_key: KesSecretKey) -> OperationalCert:
    """Operational certificate for forge benchmarks."""
    kes_vk = kes_derive_vk(kes_key)
    cold_sig = _random_bytes(64, seed=3)  # Mock cold signature
    return OperationalCert(
        kes_vk=kes_vk,
        cert_count=1,
        kes_period_start=0,
        cold_sig=cold_sig,
    )


@pytest.fixture(scope="session")
def leader_proof() -> LeaderProof:
    """Mock leader proof (avoids VRF native extension requirement)."""
    return LeaderProof(
        vrf_proof=_random_bytes(80, seed=10),
        vrf_output=_random_bytes(64, seed=11),
        slot=1000,
    )


@pytest.fixture(scope="session")
def prev_header_hash() -> bytes:
    """Previous block header hash."""
    return hashlib.blake2b(b"previous-block", digest_size=32).digest()


@pytest.fixture(scope="session")
def sample_txs() -> list[bytes]:
    """10 synthetic CBOR-encoded transactions (~256 bytes each)."""
    txs = []
    for i in range(10):
        # Build a minimal CBOR transaction-like structure
        tx_body = {
            0: [{0: _random_bytes(32, seed=100 + i), 1: 0}],  # inputs
            1: [{0: _random_bytes(32, seed=200 + i), 1: 2_000_000}],  # outputs
            2: 200_000,  # fee
        }
        tx = [tx_body, {}, True, None]  # [body, witnesses, is_valid, aux]
        txs.append(cbor2.dumps(tx))
    return txs


# ---------------------------------------------------------------------------
# Forge sub-component benchmarks
# ---------------------------------------------------------------------------

class TestForgeComponents:
    """Benchmark individual components of the forge loop."""

    def test_body_hash(self, benchmark) -> None:
        """Blake2b-256 of block body CBOR (~4KB)."""
        body = cbor2.dumps([[], [], None, []])
        benchmark.pedantic(
            hashlib.blake2b,
            args=(body,),
            kwargs={"digest_size": 32},
            rounds=100,
        )

    def test_header_body_cbor_encode(self, benchmark, vrf_vk, pool_vk, ocert) -> None:
        """CBOR encode the header body (Babbage format)."""
        header_body = [
            101,                          # block_number
            1000,                         # slot
            _random_bytes(32, seed=1),    # prev_hash
            pool_vk,                      # issuer_vk
            vrf_vk,                       # vrf_vk
            [_random_bytes(64, 10), _random_bytes(80, 11)],  # vrf_result
            128,                          # body_size
            _random_bytes(32, seed=4),    # body_hash
            [ocert.kes_vk, ocert.cert_count, ocert.kes_period_start, ocert.cold_sig],
            [10, 0],                      # protocol_version
        ]
        benchmark.pedantic(cbor2.dumps, args=(header_body,), rounds=100)

    def test_kes_sign_header(self, benchmark, kes_key) -> None:
        """KES sign the header body (the hot path in forge)."""
        header_body_cbor = _random_bytes(256, seed=99)
        benchmark.pedantic(
            kes_sign, args=(kes_key, 0, header_body_cbor), rounds=100
        )

    def test_full_block_cbor_encode(self, benchmark, sample_txs) -> None:
        """CBOR encode a complete block array (header + body)."""
        # Simulate the full block structure
        header = [
            list(range(10)),  # header_body (placeholder)
            _random_bytes(448, seed=99),  # KES signature
        ]
        body_parts = [sample_txs, [], None, []]
        full_block = [header] + body_parts

        benchmark.pedantic(cbor2.dumps, args=(full_block,), rounds=100)


# ---------------------------------------------------------------------------
# End-to-end forge benchmark
# ---------------------------------------------------------------------------

class TestForgeEndToEnd:
    """Benchmark the complete forge_block function.

    Target: < 200ms for the full cycle (slot tick to block ready).
    """

    def test_forge_block_empty(
        self,
        benchmark,
        leader_proof: LeaderProof,
        prev_header_hash: bytes,
        kes_key: KesSecretKey,
        ocert: OperationalCert,
        pool_vk: bytes,
        vrf_vk: bytes,
    ) -> None:
        """Forge a block with no transactions (empty body)."""
        result = benchmark.pedantic(
            forge_block,
            args=(
                leader_proof,
                100,  # prev_block_number
                prev_header_hash,
                [],   # mempool_txs (empty)
                kes_key,
                0,    # kes_period
                ocert,
                pool_vk,
                vrf_vk,
            ),
            rounds=100,
        )
        assert result.block.block_number == 101
        assert result.block.slot == 1000
        assert len(result.cbor) > 0

    def test_forge_block_10_txs(
        self,
        benchmark,
        leader_proof: LeaderProof,
        prev_header_hash: bytes,
        kes_key: KesSecretKey,
        ocert: OperationalCert,
        pool_vk: bytes,
        vrf_vk: bytes,
        sample_txs: list[bytes],
    ) -> None:
        """Forge a block with 10 transactions."""
        result = benchmark.pedantic(
            forge_block,
            args=(
                leader_proof,
                100,
                prev_header_hash,
                sample_txs,
                kes_key,
                0,
                ocert,
                pool_vk,
                vrf_vk,
            ),
            rounds=100,
        )
        assert result.block.block_number == 101
        assert len(result.cbor) > 0

    def test_forge_block_100_txs(
        self,
        benchmark,
        leader_proof: LeaderProof,
        prev_header_hash: bytes,
        kes_key: KesSecretKey,
        ocert: OperationalCert,
        pool_vk: bytes,
        vrf_vk: bytes,
    ) -> None:
        """Forge a block with 100 transactions (stress test)."""
        txs = []
        for i in range(100):
            tx_body = {
                0: [{0: _random_bytes(32, seed=1000 + i), 1: 0}],
                1: [{0: _random_bytes(32, seed=2000 + i), 1: 2_000_000}],
                2: 200_000,
            }
            txs.append(cbor2.dumps([tx_body, {}, True, None]))

        result = benchmark.pedantic(
            forge_block,
            args=(
                leader_proof,
                100,
                prev_header_hash,
                txs,
                kes_key,
                0,
                ocert,
                pool_vk,
                vrf_vk,
            ),
            rounds=100,
        )
        assert result.block.block_number == 101
        assert len(result.cbor) > 0

    def test_forge_under_200ms(
        self,
        leader_proof: LeaderProof,
        prev_header_hash: bytes,
        kes_key: KesSecretKey,
        ocert: OperationalCert,
        pool_vk: bytes,
        vrf_vk: bytes,
        sample_txs: list[bytes],
    ) -> None:
        """Assert the forge loop completes in < 200ms.

        This is a hard requirement — the node must forge blocks within
        a single slot's budget. On Cardano mainnet, slots are 1 second,
        so 200ms gives ample margin for network propagation.
        """
        import time

        times = []
        for _ in range(10):
            start = time.perf_counter()
            forge_block(
                leader_proof,
                100,
                prev_header_hash,
                sample_txs,
                kes_key,
                0,
                ocert,
                pool_vk,
                vrf_vk,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            times.append(elapsed_ms)

        avg_ms = sum(times) / len(times)
        max_ms = max(times)
        assert avg_ms < 200, f"Average forge time {avg_ms:.1f}ms exceeds 200ms target"
        assert max_ms < 500, f"Max forge time {max_ms:.1f}ms exceeds 500ms ceiling"
