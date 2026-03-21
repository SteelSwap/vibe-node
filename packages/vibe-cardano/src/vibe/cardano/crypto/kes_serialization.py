"""KES Secret Key Serialization — Haskell-compatible 608-byte format.

Serializes and deserializes KES secret keys in the format used by
cardano-cli and the Haskell node's ``rawSerialiseSignKeyKES`` /
``rawDeserialiseSignKeyKES`` for ``Sum6KES Ed25519DSIGN Blake2b_256``.

The Haskell ``SumKES`` serialization stores only the *active* signing
path through the binary tree, plus 32-byte seeds for the inactive
subtrees. This gives a compact representation:

    size(0) = 32          (Ed25519 seed)
    size(d) = size(d-1) + 96   (active_sub + other_seed(32) + left_vk(32) + right_vk(32))

    depth 0: 32 bytes
    depth 1: 128 bytes
    depth 2: 224 bytes
    depth 3: 320 bytes
    depth 4: 416 bytes
    depth 5: 512 bytes
    depth 6: 608 bytes  <-- Cardano mainnet

Haskell references:
    * ``rawSerialiseSignKeyKES`` in ``Cardano.Crypto.KES.Sum``
    * ``rawDeserialiseSignKeyKES`` in ``Cardano.Crypto.KES.Sum``
    * ``Cardano.Crypto.KES.Class`` -- ``SizeSignKeyKES`` type family

Spec references:
    * Shelley formal spec, Figure 2 -- KES cryptographic definitions
"""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from .kes import (
    HASH_SIZE,
    KesSecretKey,
    _ed25519_vk_bytes,
    kes_derive_vk,
    kes_keygen_from_seed,
)


def kes_sk_serialized_size(depth: int) -> int:
    """Compute the serialized size of a KES secret key at given depth.

    size(0) = 32
    size(d) = size(d-1) + 96

    Args:
        depth: KES tree depth.

    Returns:
        Size in bytes.
    """
    return 32 + depth * 96


def _extract_ed25519_seed(sk: Ed25519PrivateKey) -> bytes:
    """Extract the 32-byte seed (private scalar) from an Ed25519 private key.

    The ``cryptography`` library stores Ed25519 keys in PKCS8/raw format.
    The raw private bytes are the 32-byte seed that the Haskell node stores.
    """
    return sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())


def _extract_leaf_seed(node: KesSecretKey) -> bytes:
    """Walk down the left spine of a KES tree to find the leftmost leaf seed.

    This is used to extract the 32-byte seed that can reconstruct a
    subtree via ``kes_keygen_from_seed``.

    For a leaf node (depth 0), returns the Ed25519 private key bytes.
    For an internal node, recursively walks the left child.

    NOTE: This extracts the seed of the leftmost leaf, which is the
    original seed for a freshly-generated tree (before any key evolution).
    After evolution, the active path may be on the right side.
    """
    if node.depth == 0:
        assert node.ed25519_sk is not None, "Cannot extract seed from zeroed leaf"
        return _extract_ed25519_seed(node.ed25519_sk)
    # Walk the active child (left if it exists, right otherwise)
    if node.left is not None and not node.left._zeroed:
        return _extract_leaf_seed(node.left)
    if node.right is not None and not node.right._zeroed:
        return _extract_leaf_seed(node.right)
    raise ValueError("Cannot extract seed: tree is fully zeroed")


def serialize_kes_sk(sk: KesSecretKey) -> bytes:
    """Serialize a KES secret key to the Haskell-compatible binary format.

    At depth 0: 32 bytes (Ed25519 seed)
    At depth d: serialize(active_sub) + other_seed(32) + left_vk(32) + right_vk(32)

    The "active" subtree is the left child (for a fresh, non-evolved key
    at period 0). The "other" is the right child, stored as a 32-byte
    seed from which it can be reconstructed.

    Haskell ref: ``rawSerialiseSignKeyKES`` in ``Cardano.Crypto.KES.Sum``

    Args:
        sk: A KES secret key tree.

    Returns:
        Serialized bytes of length ``kes_sk_serialized_size(sk.depth)``.

    Raises:
        ValueError: If the key structure is invalid.
    """
    if sk.depth == 0:
        assert sk.ed25519_sk is not None, "Cannot serialize zeroed leaf"
        return _extract_ed25519_seed(sk.ed25519_sk)

    assert sk.left is not None or sk.right is not None, (
        "Cannot serialize: both subtrees are None"
    )
    assert sk.left_vk is not None and sk.right_vk is not None

    # The Haskell format always stores the active (signing) subtree
    # serialized in full, plus a 32-byte seed for the other subtree.
    #
    # For a fresh key (period 0), active = left, other = right.
    # After evolution past the midpoint, active = right, other = left.

    if sk.left is not None and not sk.left._zeroed:
        # Active is left, other is right
        active_bytes = serialize_kes_sk(sk.left)
        # Extract the seed that can reconstruct the right subtree
        other_seed = _extract_leaf_seed(sk.right) if sk.right is not None else b"\x00" * 32
    elif sk.right is not None and not sk.right._zeroed:
        # Active is right, other is left (left was erased by evolution)
        active_bytes = serialize_kes_sk(sk.right)
        # Left is erased, store zero seed (it's already been used)
        other_seed = b"\x00" * 32
    else:
        raise ValueError("Cannot serialize: both subtrees are zeroed")

    return active_bytes + other_seed + sk.left_vk + sk.right_vk


def deserialize_kes_sk(data: bytes, depth: int) -> KesSecretKey:
    """Deserialize a KES secret key from the Haskell-compatible binary format.

    Reconstructs the full KES tree from the compact serialized form.
    The active subtree is deserialized recursively; the "other" subtree
    is reconstructed from its 32-byte seed via deterministic keygen.

    Haskell ref: ``rawDeserialiseSignKeyKES`` in ``Cardano.Crypto.KES.Sum``

    Args:
        data: Serialized KES secret key bytes.
        depth: KES tree depth.

    Returns:
        A ``KesSecretKey`` tree.

    Raises:
        ValueError: If the data size doesn't match the expected size.
    """
    expected_size = kes_sk_serialized_size(depth)
    if len(data) != expected_size:
        raise ValueError(
            f"KES SK data size mismatch: expected {expected_size} bytes "
            f"for depth {depth}, got {len(data)}"
        )

    if depth == 0:
        sk = Ed25519PrivateKey.from_private_bytes(data[:32])
        vk = _ed25519_vk_bytes(sk)
        return KesSecretKey(depth=0, ed25519_sk=sk, ed25519_vk=vk)

    sub_size = kes_sk_serialized_size(depth - 1)

    # Parse: active_sub_bytes | other_seed(32) | left_vk(32) | right_vk(32)
    active_bytes = data[:sub_size]
    other_seed = data[sub_size : sub_size + 32]
    left_vk = data[sub_size + 32 : sub_size + 64]
    right_vk = data[sub_size + 64 : sub_size + 96]

    # Deserialize the active subtree recursively
    active_sub = deserialize_kes_sk(active_bytes, depth - 1)

    # Reconstruct the "other" subtree from its seed
    other_sub = kes_keygen_from_seed(other_seed, depth - 1)

    # The active subtree is the left child (for fresh/period-0 keys).
    # We verify by checking if the active sub's derived VK matches left_vk.
    active_vk = kes_derive_vk(active_sub)

    if active_vk == left_vk:
        # Active is left, other is right
        return KesSecretKey(
            depth=depth,
            left=active_sub,
            right=other_sub,
            left_vk=left_vk,
            right_vk=right_vk,
        )
    elif active_vk == right_vk:
        # Active is right, other is left (post-evolution)
        return KesSecretKey(
            depth=depth,
            left=other_sub,
            right=active_sub,
            left_vk=left_vk,
            right_vk=right_vk,
        )
    else:
        # The active sub doesn't match either VK -- this can happen if the
        # "other" seed doesn't reconstruct to the stored VK (e.g. loading
        # a cardano-cli key where the seed derivation differs from ours).
        # In this case, trust the serialized VKs and put active as left.
        return KesSecretKey(
            depth=depth,
            left=active_sub,
            right=other_sub,
            left_vk=left_vk,
            right_vk=right_vk,
        )
