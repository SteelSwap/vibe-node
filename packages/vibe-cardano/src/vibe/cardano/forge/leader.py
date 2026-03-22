"""Leader schedule check -- VRF-based slot leader election.

Determines whether a stake pool is elected to produce a block in a given
slot by computing the VRF proof over the epoch nonce and slot number, then
checking the output against the Praos leader threshold.

The VRF input (alpha string) is constructed as:
    alpha = epoch_nonce || slot_to_bytes(slot)

where slot_to_bytes encodes the slot as an 8-byte big-endian unsigned integer.
This matches the Haskell node's ``mkInputVRF`` which encodes the nonce and
slot into the VRF alpha string.

Spec references:
    - Ouroboros Praos paper, Section 4, Definition 6 (slot leader election)
    - Shelley formal spec, Section 16.1, Figure 62 (VRF verification)
    - Shelley formal spec, Section 3.3 (chain state, isSlotLeader)

Haskell references:
    - Cardano.Protocol.TPraos.Rules.Overlay.checkVRFValue
    - Ouroboros.Consensus.Shelley.Node.Forging.forgeShelleyBlock
    - Cardano.Protocol.TPraos.BHeader.mkSeed (VRF input construction)
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass

from vibe.cardano.crypto.vrf import (
    VRF_OUTPUT_SIZE,
    VRF_PROOF_SIZE,
    certified_nat_max_check,
    vrf_proof_to_hash,
    vrf_prove,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LeaderProof:
    """Proof that a pool was elected as slot leader.

    Contains the VRF proof and output needed to construct the block header.
    A verifier can check this proof against the pool's VRF verification key
    and the epoch nonce to confirm the pool was legitimately elected.

    Spec ref: Shelley formal spec, Section 16.1 -- VRF certified output
    Haskell ref: ``checkIsLeader`` in
        ``Ouroboros.Consensus.Protocol.Praos``

    Attributes:
        vrf_proof: The 80-byte VRF proof (Gamma || c || s).
        vrf_output: The 64-byte VRF output hash (SHA-512 of proof).
        slot: The slot for which leadership was proven.
    """

    vrf_proof: bytes
    vrf_output: bytes
    slot: int

    def __post_init__(self) -> None:
        if len(self.vrf_proof) != VRF_PROOF_SIZE:
            raise ValueError(
                f"VRF proof must be {VRF_PROOF_SIZE} bytes, "
                f"got {len(self.vrf_proof)}"
            )
        if len(self.vrf_output) != VRF_OUTPUT_SIZE:
            raise ValueError(
                f"VRF output must be {VRF_OUTPUT_SIZE} bytes, "
                f"got {len(self.vrf_output)}"
            )


def _mk_seed(uc_nonce: bytes, slot: int, epoch_nonce: bytes) -> bytes:
    """Construct the VRF seed following Haskell's ``mkSeed`` (TPraos era).

    mkSeed ucNonce slot eNonce =
      (ucNonce `xor`) . blake2b_256 $ (slot_be64 ++ eNonce)

    Haskell ref: ``Cardano.Protocol.TPraos.BHeader.mkSeed``

    Args:
        uc_nonce: Universal constant (seedEta or seedL), 32 bytes.
            seedEta = blake2b_256(0_u64), seedL = blake2b_256(1_u64).
        slot: Slot number.
        epoch_nonce: 32-byte epoch nonce.

    Returns:
        32-byte VRF seed.
    """
    import hashlib
    # Step 1: slot_be64 || epoch_nonce
    payload = struct.pack(">Q", slot) + epoch_nonce
    # Step 2: blake2b-256
    h = hashlib.blake2b(payload, digest_size=32).digest()
    # Step 3: XOR with universal constant
    return bytes(a ^ b for a, b in zip(h, uc_nonce))


# Universal constants from Haskell: mkNonceFromNumber n = blake2b_256(n as Word64)
import hashlib as _hl
SEED_ETA: bytes = _hl.blake2b(struct.pack(">Q", 0), digest_size=32).digest()
SEED_L: bytes = _hl.blake2b(struct.pack(">Q", 1), digest_size=32).digest()


def _mk_input_vrf(slot: int, epoch_nonce: bytes) -> bytes:
    """Construct the unified VRF input for Praos (Babbage/Conway).

    Unlike TPraos ``mkSeed``, this does NOT XOR with a universal constant.
    Praos uses a single VRF evaluation per slot instead of two separate
    ones for nonce/leader.

    mkInputVRF slot eNonce = blake2b_256(slot_be64 ++ eNonce)

    Haskell ref: ``Ouroboros.Consensus.Protocol.Praos.VRF.mkInputVRF``

    Args:
        slot: Slot number.
        epoch_nonce: 32-byte epoch nonce.

    Returns:
        32-byte VRF input hash.
    """
    import hashlib
    payload = struct.pack(">Q", slot) + epoch_nonce
    return hashlib.blake2b(payload, digest_size=32).digest()


def _make_vrf_input(epoch_nonce: bytes, slot: int) -> bytes:
    """Construct the VRF alpha string for leader election.

    Uses Praos ``mkInputVRF`` (Babbage/Conway): single VRF evaluation
    with no universal constant XOR.

    Haskell ref: ``mkInputVRF slot epochNonce`` in
        ``Ouroboros.Consensus.Protocol.Praos.VRF``
    """
    return _mk_input_vrf(slot, epoch_nonce)


def check_leadership(
    slot: int,
    vrf_sk: bytes,
    pool_vrf_vk: bytes,
    relative_stake: float,
    active_slot_coeff: float,
    epoch_nonce: bytes,
) -> LeaderProof | None:
    """Check whether a pool is the slot leader for the given slot.

    Computes the VRF proof over the epoch nonce and slot, extracts the
    VRF output, and checks whether the output satisfies the Praos leader
    threshold for the pool's relative stake.

    If elected, returns a ``LeaderProof`` containing the VRF proof and
    output needed for the block header. If not elected, returns None.

    Spec ref:
        Ouroboros Praos, Section 4, Definition 6 (slot leader election):
            y = VRF.Eval(sk, eta || slot)
            isLeader(y) iff certifiedNat(y) / 2^512 < 1 - (1 - f)^sigma

    Haskell ref:
        ``checkIsLeader`` in ``Ouroboros.Consensus.Protocol.Praos``

    Args:
        slot: The slot to check leadership for.
        vrf_sk: VRF secret key (64 bytes).
        pool_vrf_vk: Pool's VRF verification key (32 bytes). Retained
            for future verification use but not needed for the check itself.
        relative_stake: Pool's relative stake (0.0 to 1.0).
        active_slot_coeff: Active slot coefficient f (0.0 to 1.0 exclusive).
        epoch_nonce: 32-byte epoch nonce for the current epoch.

    Returns:
        ``LeaderProof`` if the pool is elected, ``None`` otherwise.

    Raises:
        NotImplementedError: If the native VRF extension is not available.
        ValueError: If key sizes are incorrect.
    """
    # Construct VRF input: epoch_nonce || slot_as_bytes
    alpha = _make_vrf_input(epoch_nonce, slot)

    # Generate VRF proof
    proof = vrf_prove(vrf_sk, alpha)

    # Extract VRF output from the proof
    output = vrf_proof_to_hash(proof)

    # Check the Praos leader threshold
    if certified_nat_max_check(output, relative_stake, active_slot_coeff):
        logger.info("Elected leader for slot %d (stake=%.4f%%, f=%.4f)", slot, relative_stake * 100, active_slot_coeff, extra={"event": "forge.elected", "slot": slot, "relative_stake": relative_stake, "active_slot_coeff": active_slot_coeff})
        return LeaderProof(
            vrf_proof=proof,
            vrf_output=output,
            slot=slot,
        )

    logger.debug(
        "Slot %d: not elected (stake=%.6f, f=%.4f)",
        slot,
        relative_stake,
        active_slot_coeff,
    )
    return None
