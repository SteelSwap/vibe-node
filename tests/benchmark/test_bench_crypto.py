"""M6.7.2 — Cryptographic operation benchmarks.

Measures performance of the crypto primitives used by Cardano consensus:
- VRF prove/verify (if native extension is available)
- KES sign/verify/evolve (Sum6KES over Ed25519)
- Ed25519 signature verification
- Blake2b-256 hashing at various input sizes

Run: uv run pytest tests/benchmark/test_bench_crypto.py -v --benchmark-only
"""

from __future__ import annotations

import hashlib
import os

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from vibe.cardano.crypto.kes import (
    CARDANO_KES_DEPTH,
    KesSecretKey,
    kes_derive_vk,
    kes_keygen,
    kes_keygen_from_seed,
    kes_sign,
    kes_update,
    kes_verify,
)
from vibe.cardano.crypto.vrf import (
    HAS_VRF_NATIVE,
    vrf_keypair,
    vrf_proof_to_hash,
    vrf_prove,
    vrf_verify,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def ed25519_keypair() -> tuple[Ed25519PrivateKey, bytes, bytes]:
    """Generate an Ed25519 keypair for benchmarking.

    Returns (private_key, public_key_bytes, signature).
    """
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    sk = Ed25519PrivateKey.generate()
    vk_bytes = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    msg = b"benchmark message for ed25519 signature verification"
    sig = sk.sign(msg)
    return sk, vk_bytes, sig


@pytest.fixture(scope="session")
def kes_key_depth3() -> KesSecretKey:
    """KES key with depth 3 (8 periods) for fast benchmarks."""
    return kes_keygen(depth=3)


@pytest.fixture(scope="session")
def kes_key_depth6() -> KesSecretKey:
    """KES key with Cardano mainnet depth 6 (64 periods)."""
    return kes_keygen_from_seed(b"benchmark-seed-for-kes-depth-6!!", depth=CARDANO_KES_DEPTH)


@pytest.fixture(scope="session")
def kes_depth3_sig(kes_key_depth3: KesSecretKey) -> tuple[bytes, bytes, bytes]:
    """Pre-computed KES signature at depth 3 for verify benchmarks.

    Returns (vk, signature, message).
    """
    msg = b"benchmark KES verification message"
    vk = kes_derive_vk(kes_key_depth3)
    sig = kes_sign(kes_key_depth3, period=0, msg=msg)
    return vk, sig, msg


@pytest.fixture(scope="session")
def kes_depth6_sig(kes_key_depth6: KesSecretKey) -> tuple[bytes, bytes, bytes]:
    """Pre-computed KES signature at depth 6 for verify benchmarks.

    Returns (vk, signature, message).
    """
    msg = b"benchmark KES verification message depth6"
    vk = kes_derive_vk(kes_key_depth6)
    sig = kes_sign(kes_key_depth6, period=0, msg=msg)
    return vk, sig, msg


# ---------------------------------------------------------------------------
# Blake2b-256 hashing
# ---------------------------------------------------------------------------


class TestBlake2bHashing:
    """Benchmark Blake2b-256 at various input sizes.

    Blake2b-256 is used for block hashes, tx hashes, KES VK hashing,
    and throughout the ledger rules.
    """

    @pytest.mark.parametrize(
        "size,label",
        [
            (32, "32B_hash"),
            (256, "256B_small_tx"),
            (1024, "1KB_typical_tx"),
            (4096, "4KB_script_tx"),
            (65536, "64KB_large_block"),
        ],
        ids=["32B", "256B", "1KB", "4KB", "64KB"],
    )
    def test_blake2b_256(self, benchmark, size: int, label: str) -> None:
        data = os.urandom(size)
        result = benchmark.pedantic(
            hashlib.blake2b,
            args=(data,),
            kwargs={"digest_size": 32},
            rounds=100,
        )
        assert len(result.digest()) == 32


# ---------------------------------------------------------------------------
# Ed25519
# ---------------------------------------------------------------------------


class TestEd25519:
    """Benchmark Ed25519 operations using the cryptography library.

    Ed25519 is the base signature scheme for KES leaf nodes,
    operational certificates, and cold key delegation.
    """

    def test_ed25519_sign(self, benchmark) -> None:
        sk = Ed25519PrivateKey.generate()
        msg = b"benchmark ed25519 sign"
        benchmark.pedantic(sk.sign, args=(msg,), rounds=100)

    def test_ed25519_verify(self, benchmark, ed25519_keypair) -> None:
        sk, vk_bytes, sig = ed25519_keypair
        msg = b"benchmark message for ed25519 signature verification"
        vk = Ed25519PublicKey.from_public_bytes(vk_bytes)

        def verify():
            vk.verify(sig, msg)

        benchmark.pedantic(verify, rounds=100)

    def test_ed25519_keygen(self, benchmark) -> None:
        benchmark.pedantic(Ed25519PrivateKey.generate, rounds=100)


# ---------------------------------------------------------------------------
# KES (Key-Evolving Signatures)
# ---------------------------------------------------------------------------


class TestKES:
    """Benchmark KES operations at depth 3 (fast) and depth 6 (mainnet).

    KES is the hot signing key used for block header signatures.
    Performance of sign and verify directly impacts block forge time.
    """

    def test_kes_keygen_depth3(self, benchmark) -> None:
        """KES key generation at depth 3 (8 periods)."""
        benchmark.pedantic(kes_keygen, args=(3,), rounds=100)

    def test_kes_sign_depth3(self, benchmark, kes_key_depth3: KesSecretKey) -> None:
        """KES sign at depth 3."""
        msg = b"benchmark KES sign depth 3"
        benchmark.pedantic(kes_sign, args=(kes_key_depth3, 0, msg), rounds=100)

    def test_kes_verify_depth3(self, benchmark, kes_depth3_sig) -> None:
        """KES verify at depth 3."""
        vk, sig, msg = kes_depth3_sig
        result = benchmark.pedantic(kes_verify, args=(vk, 3, 0, sig, msg), rounds=100)
        assert result is True

    def test_kes_sign_depth6(self, benchmark, kes_key_depth6: KesSecretKey) -> None:
        """KES sign at Cardano mainnet depth 6 (64 periods)."""
        msg = b"benchmark KES sign depth 6"
        benchmark.pedantic(kes_sign, args=(kes_key_depth6, 0, msg), rounds=100)

    def test_kes_verify_depth6(self, benchmark, kes_depth6_sig) -> None:
        """KES verify at Cardano mainnet depth 6 (64 periods)."""
        vk, sig, msg = kes_depth6_sig
        result = benchmark.pedantic(
            kes_verify, args=(vk, CARDANO_KES_DEPTH, 0, sig, msg), rounds=100
        )
        assert result is True

    def test_kes_derive_vk_depth3(self, benchmark, kes_key_depth3: KesSecretKey) -> None:
        """Derive verification key from KES secret key at depth 3."""
        benchmark.pedantic(kes_derive_vk, args=(kes_key_depth3,), rounds=100)

    def test_kes_derive_vk_depth6(self, benchmark, kes_key_depth6: KesSecretKey) -> None:
        """Derive verification key from KES secret key at depth 6."""
        benchmark.pedantic(kes_derive_vk, args=(kes_key_depth6,), rounds=100)

    def test_kes_update_depth3(self, benchmark) -> None:
        """KES key evolution at depth 3 (period 0 -> 1)."""

        # We need a fresh key each time since update mutates
        def setup():
            return (kes_keygen(depth=3),), {}

        def evolve(sk):
            return kes_update(sk, current_period=0)

        # Can't use setup with pedantic easily, so generate inline
        sk = kes_keygen(depth=3)
        benchmark.pedantic(kes_update, args=(sk, 0), rounds=100)


# ---------------------------------------------------------------------------
# VRF (Verifiable Random Function)
# ---------------------------------------------------------------------------


class TestVRF:
    """Benchmark VRF operations (requires native extension).

    VRF is used for slot leader election. If the native pybind11 extension
    is not built, these tests are skipped.
    """

    @pytest.fixture(scope="class")
    def vrf_keys(self):
        """Generate VRF keypair for benchmarking."""
        if not HAS_VRF_NATIVE:
            pytest.skip("VRF native extension not available")
        # vrf_keypair() returns (pk, sk) — swap to (sk, pk)
        pk, sk = vrf_keypair()
        return sk, pk

    @pytest.fixture(scope="class")
    def vrf_proof_data(self, vrf_keys):
        """Pre-computed VRF proof for verify benchmarks."""
        sk, pk = vrf_keys
        alpha = b"benchmark VRF prove/verify message"
        proof = vrf_prove(sk, alpha)
        output = vrf_proof_to_hash(proof)
        return pk, proof, output, alpha

    def test_vrf_prove(self, benchmark, vrf_keys) -> None:
        sk, pk = vrf_keys
        alpha = b"benchmark VRF prove"
        benchmark.pedantic(vrf_prove, args=(sk, alpha), rounds=100)

    def test_vrf_verify(self, benchmark, vrf_proof_data) -> None:
        pk, proof, output, alpha = vrf_proof_data
        result = benchmark.pedantic(vrf_verify, args=(pk, proof, alpha), rounds=100)
        assert result  # vrf_verify returns output bytes (truthy) on success

    def test_vrf_proof_to_hash(self, benchmark, vrf_proof_data) -> None:
        _, proof, _, _ = vrf_proof_data
        benchmark.pedantic(vrf_proof_to_hash, args=(proof,), rounds=100)

    def test_vrf_keypair(self, benchmark) -> None:
        if not HAS_VRF_NATIVE:
            pytest.skip("VRF native extension not available")
        benchmark.pedantic(vrf_keypair, rounds=100)
