"""Tests for KES secret key serialization — Haskell-compatible 608-byte format.

Tests cover:
    * Round-trip serialize/deserialize at depth 0 (leaf)
    * Round-trip serialize/deserialize at depth 6 (Cardano mainnet)
    * Deserialized key produces verifiable signatures
    * Serialized size matches expected 608 bytes for depth 6
    * Deterministic keygen from seed produces consistent results

Spec references:
    * Shelley formal spec, Figure 2 -- KES cryptographic definitions
    * ``rawSerialiseSignKeyKES`` / ``rawDeserialiseSignKeyKES`` in
      ``Cardano.Crypto.KES.Sum``
"""

from __future__ import annotations

import pytest

from vibe.cardano.crypto.kes import (
    CARDANO_KES_DEPTH,
    kes_derive_vk,
    kes_keygen,
    kes_keygen_from_seed,
    kes_sign,
    kes_verify,
)
from vibe.cardano.crypto.kes_serialization import (
    deserialize_kes_sk,
    kes_sk_serialized_size,
    serialize_kes_sk,
)


class TestKesSerialization:
    """Tests for KES secret key serialization round-trips."""

    def test_roundtrip_depth_0(self) -> None:
        """Keygen -> serialize -> deserialize preserves VK at depth 0."""
        sk = kes_keygen(0)
        vk_original = kes_derive_vk(sk)

        data = serialize_kes_sk(sk)
        assert len(data) == 32  # depth 0 = 32 bytes

        sk2 = deserialize_kes_sk(data, 0)
        vk_roundtrip = kes_derive_vk(sk2)

        assert vk_original == vk_roundtrip

    def test_roundtrip_depth_1(self) -> None:
        """Keygen -> serialize -> deserialize preserves VK at depth 1."""
        sk = kes_keygen(1)
        vk_original = kes_derive_vk(sk)

        data = serialize_kes_sk(sk)
        assert len(data) == kes_sk_serialized_size(1)  # 128

        sk2 = deserialize_kes_sk(data, 1)
        vk_roundtrip = kes_derive_vk(sk2)

        assert vk_original == vk_roundtrip

    def test_roundtrip_depth_3(self) -> None:
        """Keygen -> serialize -> deserialize preserves VK at depth 3."""
        sk = kes_keygen(3)
        vk_original = kes_derive_vk(sk)

        data = serialize_kes_sk(sk)
        assert len(data) == kes_sk_serialized_size(3)  # 320

        sk2 = deserialize_kes_sk(data, 3)
        vk_roundtrip = kes_derive_vk(sk2)

        assert vk_original == vk_roundtrip

    def test_roundtrip_depth_6(self) -> None:
        """Keygen -> serialize -> deserialize preserves VK at depth 6."""
        sk = kes_keygen(CARDANO_KES_DEPTH)
        vk_original = kes_derive_vk(sk)

        data = serialize_kes_sk(sk)
        assert len(data) == 608  # depth 6 = 608 bytes

        sk2 = deserialize_kes_sk(data, CARDANO_KES_DEPTH)
        vk_roundtrip = kes_derive_vk(sk2)

        assert vk_original == vk_roundtrip

    def test_size_depth_6(self) -> None:
        """Serialized size is exactly 608 bytes for depth 6."""
        assert kes_sk_serialized_size(CARDANO_KES_DEPTH) == 608

        sk = kes_keygen(CARDANO_KES_DEPTH)
        data = serialize_kes_sk(sk)
        assert len(data) == 608

    def test_size_formula(self) -> None:
        """Size formula: size(0)=32, size(d)=size(d-1)+96."""
        assert kes_sk_serialized_size(0) == 32
        assert kes_sk_serialized_size(1) == 128
        assert kes_sk_serialized_size(2) == 224
        assert kes_sk_serialized_size(3) == 320
        assert kes_sk_serialized_size(4) == 416
        assert kes_sk_serialized_size(5) == 512
        assert kes_sk_serialized_size(6) == 608


class TestDeserializedKeySigns:
    """Tests that deserialized keys can produce verifiable signatures."""

    def test_deserialized_key_signs_depth_0(self) -> None:
        """Deserialized depth-0 key produces verifiable signatures."""
        sk = kes_keygen(0)
        vk = kes_derive_vk(sk)

        data = serialize_kes_sk(sk)
        sk2 = deserialize_kes_sk(data, 0)

        msg = b"test message for depth 0 signing"
        sig = kes_sign(sk2, 0, msg)
        assert kes_verify(vk, 0, 0, sig, msg)

    def test_deserialized_key_signs_depth_3(self) -> None:
        """Deserialized depth-3 key produces verifiable signatures at period 0."""
        sk = kes_keygen(3)
        vk = kes_derive_vk(sk)

        data = serialize_kes_sk(sk)
        sk2 = deserialize_kes_sk(data, 3)

        msg = b"test message for depth 3 signing"
        sig = kes_sign(sk2, 0, msg)
        assert kes_verify(vk, 3, 0, sig, msg)

    def test_deserialized_key_signs_depth_6(self) -> None:
        """Deserialized depth-6 key produces verifiable signatures at period 0."""
        sk = kes_keygen(CARDANO_KES_DEPTH)
        vk = kes_derive_vk(sk)

        data = serialize_kes_sk(sk)
        sk2 = deserialize_kes_sk(data, CARDANO_KES_DEPTH)

        msg = b"Cardano block header body bytes"
        sig = kes_sign(sk2, 0, msg)
        assert kes_verify(vk, CARDANO_KES_DEPTH, 0, sig, msg)

    def test_deserialized_key_signs_multiple_periods(self) -> None:
        """Deserialized depth-2 key signs and verifies at multiple periods."""
        sk = kes_keygen(2)
        vk = kes_derive_vk(sk)

        data = serialize_kes_sk(sk)
        sk2 = deserialize_kes_sk(data, 2)

        msg = b"multi-period test"
        # Period 0 should work (active left path)
        sig0 = kes_sign(sk2, 0, msg)
        assert kes_verify(vk, 2, 0, sig0, msg)


class TestDeterministicKeygen:
    """Tests for deterministic KES keygen from seed."""

    def test_same_seed_same_vk(self) -> None:
        """Same seed produces same VK."""
        seed = b"\xab" * 32
        sk1 = kes_keygen_from_seed(seed, 3)
        sk2 = kes_keygen_from_seed(seed, 3)

        assert kes_derive_vk(sk1) == kes_derive_vk(sk2)

    def test_different_seeds_different_vks(self) -> None:
        """Different seeds produce different VKs."""
        seed1 = b"\xab" * 32
        seed2 = b"\xcd" * 32
        sk1 = kes_keygen_from_seed(seed1, 3)
        sk2 = kes_keygen_from_seed(seed2, 3)

        assert kes_derive_vk(sk1) != kes_derive_vk(sk2)

    def test_seed_keygen_signs(self) -> None:
        """Key generated from seed can sign and verify."""
        seed = b"\x42" * 32
        sk = kes_keygen_from_seed(seed, CARDANO_KES_DEPTH)
        vk = kes_derive_vk(sk)

        msg = b"deterministic signing test"
        sig = kes_sign(sk, 0, msg)
        assert kes_verify(vk, CARDANO_KES_DEPTH, 0, sig, msg)

    def test_bad_seed_length_raises(self) -> None:
        """Seed not exactly 32 bytes raises ValueError."""
        with pytest.raises(ValueError, match="32 bytes"):
            kes_keygen_from_seed(b"\x00" * 31, 3)

        with pytest.raises(ValueError, match="32 bytes"):
            kes_keygen_from_seed(b"\x00" * 33, 3)


class TestDeserializationErrors:
    """Tests for error handling in deserialization."""

    def test_wrong_size_raises(self) -> None:
        """Data of wrong size raises ValueError."""
        with pytest.raises(ValueError, match="size mismatch"):
            deserialize_kes_sk(b"\x00" * 100, 6)

    def test_wrong_size_depth_0(self) -> None:
        """Wrong size for depth 0 raises ValueError."""
        with pytest.raises(ValueError, match="size mismatch"):
            deserialize_kes_sk(b"\x00" * 33, 0)
