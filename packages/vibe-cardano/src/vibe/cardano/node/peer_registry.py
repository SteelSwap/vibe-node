"""Peer registry for the peer sharing protocol.

Tracks connected peer addresses and provides deterministic salt-rotated
selection for peer sharing responses.

Haskell reference:
    computePeerSharingPeers in Ouroboros.Network.PeerSharing

    The Haskell implementation maintains a sticky peer list that rotates
    based on a salt value. The salt changes every ps_POLICY_PEER_SHARE_STICKY_TIME
    seconds (823s), ensuring that the same set of peers is shared within a
    time window (stability) but different peers are shared after rotation
    (diversity). The maximum number of peers shared per request is capped
    at ps_POLICY_PEER_SHARE_MAX_PEERS (10).
"""

from __future__ import annotations

import hashlib
import logging
import random
import struct
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PeerAddress:
    """A peer's network address for sharing.

    Attributes:
        ip: The IP address (IPv4 or IPv6 string).
        port: The TCP port number.
        is_ipv6: Whether this is an IPv6 address.
    """

    ip: str
    port: int
    is_ipv6: bool = False


class PeerRegistry:
    """Tracks connected peers and provides salt-rotated selection for peer sharing.

    Haskell reference: computePeerSharingPeers in PeerSharing.hs

    The registry maintains a set of connected peer addresses. When asked for
    peers to share, it returns a deterministic subset based on a salt that
    rotates every POLICY_STICKY_TIME seconds. This ensures:
    - Same peers are shared within a time window (stability)
    - Different peers are shared after salt rotation (diversity)
    - Never shares more than POLICY_MAX_PEERS per request
    """

    POLICY_MAX_PEERS: int = 10
    POLICY_STICKY_TIME: float = 823.0  # seconds, matches Haskell ps_POLICY_PEER_SHARE_STICKY_TIME

    def __init__(self) -> None:
        self._peers: dict[str, PeerAddress] = {}  # "ip:port" -> PeerAddress
        self._salt: int = random.randint(0, 2**32 - 1)
        self._salt_expires: float = time.monotonic() + self.POLICY_STICKY_TIME

    @property
    def peer_count(self) -> int:
        """Number of peers currently registered."""
        return len(self._peers)

    def _peer_key(self, addr: PeerAddress) -> str:
        """Canonical string key for a peer address."""
        return f"{addr.ip}:{addr.port}"

    def add_peer(self, addr: PeerAddress) -> None:
        """Register a connected peer.

        Duplicate additions (same ip:port) are silently ignored.
        """
        key = self._peer_key(addr)
        if key not in self._peers:
            self._peers[key] = addr
            logger.debug("PeerRegistry: added %s (%d total)", key, len(self._peers))

    def remove_peer(self, addr: PeerAddress) -> None:
        """Unregister a disconnected peer.

        Removing a peer that isn't registered is silently ignored.
        """
        key = self._peer_key(addr)
        if key in self._peers:
            del self._peers[key]
            logger.debug("PeerRegistry: removed %s (%d total)", key, len(self._peers))

    def _maybe_rotate_salt(self) -> None:
        """Rotate the selection salt if the sticky time has elapsed."""
        now = time.monotonic()
        if now >= self._salt_expires:
            self._salt = random.randint(0, 2**32 - 1)
            self._salt_expires = now + self.POLICY_STICKY_TIME
            logger.debug(
                "PeerRegistry: salt rotated (next rotation in %.0fs)",
                self.POLICY_STICKY_TIME,
            )

    def _peer_sort_key(self, addr: PeerAddress) -> bytes:
        """Deterministic sort key using salt + peer address hash.

        The SHA-256 hash of (salt || "ip:port") produces a uniform
        pseudo-random ordering that is stable for the lifetime of the
        current salt. This matches the Haskell approach of using a
        salted hash for deterministic peer selection.
        """
        h = hashlib.sha256()
        h.update(struct.pack(">I", self._salt))
        h.update(f"{addr.ip}:{addr.port}".encode())
        return h.digest()

    def get_peers(
        self,
        amount: int,
        *,
        exclude: PeerAddress | None = None,
    ) -> list[PeerAddress]:
        """Return up to ``amount`` peers (capped at POLICY_MAX_PEERS).

        Uses deterministic salt-based selection that rotates every
        POLICY_STICKY_TIME seconds, matching Haskell's sticky peer list.

        Args:
            amount: Maximum number of peers requested.
            exclude: Optional peer to exclude (typically the requesting peer).

        Returns:
            A list of up to min(amount, POLICY_MAX_PEERS) peer addresses,
            deterministically selected based on the current salt.
        """
        self._maybe_rotate_salt()

        candidates = [p for p in self._peers.values() if p != exclude]
        n = min(amount, self.POLICY_MAX_PEERS, len(candidates))
        if n == 0:
            return []

        candidates.sort(key=self._peer_sort_key)
        return candidates[:n]
