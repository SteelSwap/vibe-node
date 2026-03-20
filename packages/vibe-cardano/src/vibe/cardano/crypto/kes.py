"""KES (Key-Evolving Signatures) — Sum-composition over Ed25519.

Implements the iterated sum construction from MMM (Malkin-Micciancio-Miner,
Section 3.1 of https://eprint.iacr.org/2001/034) as used by Cardano's
Ouroboros Praos for block header signatures.

Cardano uses ``Sum6KES Ed25519DSIGN Blake2b_256`` — a depth-6 binary tree of
Ed25519 key pairs, giving 2^6 = 64 total time periods. The KES verification
key is a 32-byte Blake2b-256 hash (at internal nodes) or a 32-byte Ed25519
public key (at leaves).

Spec references:
    * Shelley formal spec, Section "Cryptographic primitives", Figure 2
      (KES cryptographic definitions)
    * Shelley formal spec, crypto-details.tex — "The sign_ev and verify_ev
      functions use the iterated sum construction from Section 3.1 of
      [MMM paper]. We allow up to 2^7 key evolutions."
    * ``cardano-crypto-class`` — ``Cardano.Crypto.KES.Sum``
    * ``cardano-crypto-class`` — ``Cardano.Crypto.KES.Class``

Haskell references:
    * ``SumKES`` in ``Cardano.Crypto.KES.Sum``
    * ``verifySignedKES`` in ``Cardano.Crypto.KES.Class``
    * ``rawSerialiseSigKES`` / ``rawDeserialiseSigKES``
    * ``deriveVerKeyKES`` / ``hashVerKeyKES``

This module focuses on **verification** (needed for chain sync). Signing
is also implemented for testing completeness.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ED25519_VK_SIZE = 32
"""Size of an Ed25519 verification key in bytes."""

ED25519_SIG_SIZE = 64
"""Size of an Ed25519 signature in bytes."""

HASH_SIZE = 32
"""Blake2b-256 digest size used for KES VK hashing."""

# Cardano mainnet uses depth 6 (Sum6KES = 2^6 = 64 periods)
CARDANO_KES_DEPTH = 6
"""KES tree depth on Cardano mainnet."""

MAX_KES_EVOLUTIONS = 62
"""MaxKESEvo protocol parameter on Cardano mainnet.
Although depth-6 supports 64 periods, the protocol limits to 62."""


# ---------------------------------------------------------------------------
# Low-level Ed25519 helpers (using `cryptography` library)
# ---------------------------------------------------------------------------


def _ed25519_sign(sk: Ed25519PrivateKey, msg: bytes) -> bytes:
    """Sign a message with an Ed25519 private key."""
    return sk.sign(msg)


def _ed25519_verify(vk_bytes: bytes, sig: bytes, msg: bytes) -> bool:
    """Verify an Ed25519 signature. Returns True if valid."""
    try:
        vk = Ed25519PublicKey.from_public_bytes(vk_bytes)
        vk.verify(sig, msg)
        return True
    except Exception:
        return False


def _ed25519_vk_bytes(sk: Ed25519PrivateKey) -> bytes:
    """Extract the 32-byte public key from an Ed25519 private key."""
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )

    return sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _blake2b_256(data: bytes) -> bytes:
    """Compute Blake2b-256 hash."""
    return hashlib.blake2b(data, digest_size=HASH_SIZE).digest()


# ---------------------------------------------------------------------------
# KES Verification Key
# ---------------------------------------------------------------------------


def kes_vk_hash(left_vk: bytes, right_vk: bytes) -> bytes:
    """Hash two child verification keys to produce a parent KES VK.

    In the sum-composition scheme, an internal node's verification key
    is ``Blake2b-256(vk_left || vk_right)``.

    Haskell ref: ``hashPairOfVKeys`` in ``Cardano.Crypto.KES.Sum``

    Args:
        left_vk: 32-byte verification key of the left child.
        right_vk: 32-byte verification key of the right child.

    Returns:
        32-byte Blake2b-256 hash.
    """
    return _blake2b_256(left_vk + right_vk)


# ---------------------------------------------------------------------------
# KES Secret Key (tree structure for signing)
# ---------------------------------------------------------------------------


@dataclass
class KesSecretKey:
    """A KES secret key — a binary tree of Ed25519 key pairs.

    For depth 0 (leaf): holds a single Ed25519 private key.
    For depth d > 0: holds left and right subtrees plus cached VKs.

    This structure is used for **signing** and **key evolution**.
    For verification, only the root VK (32 bytes) is needed.
    """

    depth: int
    """Tree depth. 0 = leaf (Ed25519), >0 = internal node."""

    # Leaf fields (depth == 0)
    ed25519_sk: Ed25519PrivateKey | None = None
    """Ed25519 private key (only for leaf nodes)."""

    ed25519_vk: bytes | None = None
    """Ed25519 public key bytes (only for leaf nodes, 32 bytes)."""

    # Internal node fields (depth > 0)
    left: KesSecretKey | None = None
    """Left subtree (periods [0, 2^(d-1)))."""

    right: KesSecretKey | None = None
    """Right subtree (periods [2^(d-1), 2^d))."""

    left_vk: bytes | None = None
    """Cached VK of the left subtree (32 bytes)."""

    right_vk: bytes | None = None
    """Cached VK of the right subtree (32 bytes)."""

    _zeroed: bool = False
    """True if this key has been securely erased."""


def kes_keygen(depth: int) -> KesSecretKey:
    """Generate a fresh KES key pair with the given tree depth.

    Supports 2^depth time periods.

    Haskell ref: ``genKeyKES`` in ``Cardano.Crypto.KES.Sum``

    Args:
        depth: Tree depth (0 = single Ed25519 key, 6 = Cardano mainnet).

    Returns:
        A fresh ``KesSecretKey``.
    """
    if depth == 0:
        sk = Ed25519PrivateKey.generate()
        vk = _ed25519_vk_bytes(sk)
        return KesSecretKey(depth=0, ed25519_sk=sk, ed25519_vk=vk)

    left = kes_keygen(depth - 1)
    right = kes_keygen(depth - 1)
    left_vk = kes_derive_vk(left)
    right_vk = kes_derive_vk(right)
    return KesSecretKey(
        depth=depth,
        left=left,
        right=right,
        left_vk=left_vk,
        right_vk=right_vk,
    )


def kes_derive_vk(sk: KesSecretKey) -> bytes:
    """Derive the 32-byte verification key from a KES secret key.

    For a leaf (depth 0): returns the Ed25519 public key (32 bytes).
    For an internal node: returns ``Blake2b-256(vk_left || vk_right)``.

    Haskell ref: ``deriveVerKeyKES`` in ``Cardano.Crypto.KES.Sum``

    Args:
        sk: A KES secret key.

    Returns:
        32-byte verification key.
    """
    if sk.depth == 0:
        assert sk.ed25519_vk is not None
        return sk.ed25519_vk

    assert sk.left_vk is not None and sk.right_vk is not None
    return kes_vk_hash(sk.left_vk, sk.right_vk)


# ---------------------------------------------------------------------------
# KES Signature Format
# ---------------------------------------------------------------------------

# The KES signature for SumKES is recursive:
#
# For depth 0 (SingleKES / Ed25519):
#   sig = ed25519_signature (64 bytes)
#
# For depth d (SumKES):
#   sig = inner_sig || vk_other || leaf_indicator
#   where:
#     - inner_sig is the signature from the child subtree (depth d-1)
#     - vk_other is the VK of the sibling subtree (32 bytes)
#     - leaf_indicator: if period < half, we went left and vk_other = right_vk
#                       if period >= half, we went right and vk_other = left_vk
#
# The Haskell serialization for SumKES d:
#   SigSumKES = SigKES (d-1) || VerKeyKES (d-1) || VerKeyKES (d-1)
# Wait — actually the Haskell format stores BOTH child VKs in the signature.
#
# From cardano-crypto-class SumKES:
#   data SigKES (SumKES h d) =
#       SigSumKES !(SigKES d) !(VerKeyKES d) !(VerKeyKES d)
#
# So the signature includes: child_sig, left_vk, right_vk (of the child level).
# This allows the verifier to reconstruct the full path.
#
# Size calculation for Sum6KES:
#   sig_size(0) = 64 (Ed25519 sig)
#   sig_size(d) = sig_size(d-1) + 2 * vk_size(d-1)
#   vk_size(0) = 32 (Ed25519 public key)
#   vk_size(d) = 32 (Blake2b-256 hash for d > 0)
#   BUT: for depth 0, vk_size = 32 (Ed25519 raw key)
#        for depth > 0, vk_size = 32 (Blake2b-256 hash)
#   So vk_size is always 32.
#
#   sig_size(0) = 64
#   sig_size(1) = 64 + 2*32 = 128
#   sig_size(2) = 128 + 2*32 = 192
#   sig_size(d) = 64 + d * 64 = 64 * (d + 1)
#
#   For d=6: sig_size = 64 * 7 = 448 bytes
#
# This matches: the Haskell SizeSignKES (SumKES h d) = SizeSignKES d + 2 * SizeVerKeyKES d


def kes_sig_size(depth: int) -> int:
    """Calculate the KES signature size for a given depth.

    sig_size(0) = 64 (Ed25519 signature)
    sig_size(d) = sig_size(d-1) + 2 * 32 = 64 * (d + 1)

    Haskell ref: ``SizeSignKES`` type family in ``Cardano.Crypto.KES.Sum``

    Args:
        depth: KES tree depth.

    Returns:
        Signature size in bytes.
    """
    return ED25519_SIG_SIZE + depth * 2 * ED25519_VK_SIZE


# ---------------------------------------------------------------------------
# KES Sign
# ---------------------------------------------------------------------------


def kes_sign(sk: KesSecretKey, period: int, msg: bytes) -> bytes:
    """Sign a message at a given KES time period.

    Navigates the binary tree to find the leaf for the given period,
    signs with the Ed25519 key at that leaf, and constructs the full
    signature including sibling VKs at each level.

    Haskell ref: ``signKES`` in ``Cardano.Crypto.KES.Sum``

    Args:
        sk: KES secret key.
        period: Time period (0-indexed, must be < 2^depth).
        msg: Message to sign.

    Returns:
        KES signature bytes.

    Raises:
        ValueError: If period is out of range or key has been erased.
    """
    total_periods = 1 << sk.depth

    if period < 0 or period >= total_periods:
        raise ValueError(
            f"KES period {period} out of range [0, {total_periods})"
        )

    if sk._zeroed:
        raise ValueError("Cannot sign with a zeroed KES key")

    return _kes_sign_recursive(sk, period, msg)


def _kes_sign_recursive(sk: KesSecretKey, period: int, msg: bytes) -> bytes:
    """Recursive KES signing implementation."""
    if sk.depth == 0:
        # Leaf: sign with Ed25519
        assert sk.ed25519_sk is not None, "Leaf key has been erased"
        return _ed25519_sign(sk.ed25519_sk, msg)

    half = 1 << (sk.depth - 1)

    if period < half:
        # Go left
        assert sk.left is not None, "Left subtree has been erased"
        child_sig = _kes_sign_recursive(sk.left, period, msg)
        # Signature = child_sig || left_vk || right_vk
        return child_sig + sk.left_vk + sk.right_vk
    else:
        # Go right
        assert sk.right is not None, "Right subtree has been erased"
        child_sig = _kes_sign_recursive(sk.right, period - half, msg)
        # Signature = child_sig || left_vk || right_vk
        return child_sig + sk.left_vk + sk.right_vk


# ---------------------------------------------------------------------------
# KES Verify
# ---------------------------------------------------------------------------


def kes_verify(vk: bytes, depth: int, period: int, sig: bytes, msg: bytes) -> bool:
    """Verify a KES signature.

    Reconstructs the verification key from the signature's embedded sibling
    VKs, verifies the Ed25519 signature at the leaf, and checks that the
    reconstructed root VK matches the expected VK.

    Haskell ref: ``verifySignedKES`` / ``verifySigKES`` in
        ``Cardano.Crypto.KES.Sum``

    Args:
        vk: Expected 32-byte KES verification key (root of the tree).
        depth: KES tree depth.
        period: Time period the signature claims.
        sig: KES signature bytes.
        msg: Signed message.

    Returns:
        True if the signature is valid.
    """
    total_periods = 1 << depth
    expected_size = kes_sig_size(depth)

    if period < 0 or period >= total_periods:
        return False

    if len(sig) != expected_size:
        return False

    if len(vk) != ED25519_VK_SIZE:
        return False

    return _kes_verify_recursive(vk, depth, period, sig, msg)


def _kes_verify_recursive(
    vk: bytes, depth: int, period: int, sig: bytes, msg: bytes
) -> bool:
    """Recursive KES verification implementation.

    At each level, we extract the child signature, left_vk, and right_vk
    from the serialized signature. We reconstruct the parent VK from the
    child VKs and check it matches the expected VK. Then we recurse into
    the appropriate child.
    """
    if depth == 0:
        # Leaf: verify Ed25519 signature directly
        # sig is 64 bytes (Ed25519 signature)
        # vk is the Ed25519 public key
        return _ed25519_verify(vk, sig, msg)

    # Extract components from the signature:
    # sig = child_sig || left_vk || right_vk
    child_sig_size = kes_sig_size(depth - 1)
    child_sig = sig[:child_sig_size]
    left_vk = sig[child_sig_size : child_sig_size + ED25519_VK_SIZE]
    right_vk = sig[child_sig_size + ED25519_VK_SIZE : child_sig_size + 2 * ED25519_VK_SIZE]

    # Reconstruct the parent VK and check it matches
    reconstructed_vk = kes_vk_hash(left_vk, right_vk)
    if reconstructed_vk != vk:
        return False

    # Recurse into the appropriate child
    half = 1 << (depth - 1)
    if period < half:
        return _kes_verify_recursive(left_vk, depth - 1, period, child_sig, msg)
    else:
        return _kes_verify_recursive(
            right_vk, depth - 1, period - half, child_sig, msg
        )


# ---------------------------------------------------------------------------
# KES Key Update (Evolution)
# ---------------------------------------------------------------------------


def kes_update(sk: KesSecretKey, current_period: int) -> KesSecretKey | None:
    """Evolve a KES key to the next period.

    The current period's leaf key is securely erased (zeroed), providing
    forward security. Returns None if all periods are exhausted.

    Haskell ref: ``updateKES`` in ``Cardano.Crypto.KES.Sum``

    Args:
        sk: Current KES secret key.
        current_period: The period that was just used (0-indexed).

    Returns:
        Updated KES secret key for ``current_period + 1``, or None if
        all periods are exhausted.
    """
    total_periods = 1 << sk.depth
    next_period = current_period + 1

    if next_period >= total_periods:
        return None

    return _kes_update_recursive(sk, current_period)


def _kes_update_recursive(
    sk: KesSecretKey, current_period: int
) -> KesSecretKey | None:
    """Recursive KES key update."""
    if sk.depth == 0:
        # Leaf: erase the key — it's been used
        return KesSecretKey(
            depth=0,
            ed25519_sk=None,
            ed25519_vk=sk.ed25519_vk,
            _zeroed=True,
        )

    half = 1 << (sk.depth - 1)

    if current_period < half - 1:
        # Still in the left half, not at the boundary — update left subtree
        new_left = _kes_update_recursive(sk.left, current_period)
        return KesSecretKey(
            depth=sk.depth,
            left=new_left,
            right=sk.right,
            left_vk=sk.left_vk,
            right_vk=sk.right_vk,
        )
    elif current_period == half - 1:
        # At the boundary: erase the entire left subtree, switch to right
        return KesSecretKey(
            depth=sk.depth,
            left=None,  # left subtree erased
            right=sk.right,
            left_vk=sk.left_vk,
            right_vk=sk.right_vk,
        )
    else:
        # In the right half — update right subtree
        new_right = _kes_update_recursive(sk.right, current_period - half)
        return KesSecretKey(
            depth=sk.depth,
            left=sk.left,  # already erased or None
            right=new_right,
            left_vk=sk.left_vk,
            right_vk=sk.right_vk,
        )


# ---------------------------------------------------------------------------
# Convenience: verify from raw CBOR-decoded block header data
# ---------------------------------------------------------------------------


def kes_verify_block_signature(
    kes_vk: bytes,
    kes_period: int,
    kes_sig: bytes,
    header_body_cbor: bytes,
    *,
    depth: int = CARDANO_KES_DEPTH,
) -> bool:
    """Verify a KES signature on a Cardano block header body.

    This is the top-level function used during block validation to check
    the KES signature ``sigma`` in the OCERT rule:
        V^KES_{vk_hot}(serialised(bhb))_sigma^t

    Args:
        kes_vk: 32-byte KES verification key (the hot key from the OCert).
        kes_period: The relative KES period ``t = kesPeriod(slot) - c_0``.
        kes_sig: The KES signature from the block header.
        header_body_cbor: The serialized block header body (the signed message).
        depth: KES tree depth (default: 6 for Cardano mainnet).

    Returns:
        True if the signature is valid.
    """
    return kes_verify(kes_vk, depth, kes_period, kes_sig, header_body_cbor)
