"""N2C (node-to-client) version negotiation tests.

Tests cover:
1. N2C version data CBOR round-trip — encode then decode recovers original
2. N2C version data must NOT decode as N2N version data (cross-isolation)
3. N2C version negotiation with known Cardano N2C version numbers

The Cardano protocol uses separate version tables for N2N and N2C connections.
N2N versions (V14, V15) carry a 4-element list: [magic, initiatorOnly,
peerSharing, query]. N2C versions (V16+) carry a 2-element list:
[magic, query]. These are deliberately incompatible to prevent a client
from accidentally connecting to a node-to-node port with node-to-client
version data or vice versa.

Haskell references:
    Ouroboros.Network.NodeToNode.Version (nodeToNodeCodecCBORTerm)
    Ouroboros.Network.NodeToClient.Version (nodeToClientCodecCBORTerm)
    Ouroboros.Network.Protocol.Handshake.Codec (codecHandshake)
"""

from __future__ import annotations

import cbor2
import pytest

from vibe.cardano.network.handshake import (
    MAINNET_NETWORK_MAGIC,
    N2N_V14,
    N2N_V15,
    PREPROD_NETWORK_MAGIC,
    PREVIEW_NETWORK_MAGIC,
    NodeToNodeVersionData,
    PeerSharing,
    _decode_version_data,
    _encode_version_data,
)

# ---------------------------------------------------------------------------
# N2C version data encoding (what N2C uses)
# ---------------------------------------------------------------------------

# N2C version numbers (from Ouroboros.Network.NodeToClient.Version)
# As of ouroboros-network-0.22:
N2C_V16: int = 16
N2C_V17: int = 17
N2C_V18: int = 18
N2C_V19: int = 19


def _encode_n2c_version_data(network_magic: int, query: bool) -> list:
    """Encode N2C version data to a CBOR-friendly list.

    N2C format (from nodeToClientCodecCBORTerm): [networkMagic, query]
    This is a 2-element list, vs N2N's 4-element list.
    """
    return [network_magic, query]


def _decode_n2c_version_data(term: list) -> tuple[int, bool]:
    """Decode N2C version data from a CBOR list.

    Returns (network_magic, query).

    Raises ValueError if the format doesn't match N2C expectations.
    """
    if not isinstance(term, list) or len(term) != 2:
        raise ValueError(f"N2C version data must be a 2-element list, got: {term!r}")

    network_magic = term[0]
    if not isinstance(network_magic, int) or network_magic < 0:
        raise ValueError(f"N2C networkMagic invalid: {network_magic}")

    query = term[1]
    if not isinstance(query, bool):
        raise ValueError(f"N2C query must be bool, got: {query!r}")

    return (network_magic, query)


# ---------------------------------------------------------------------------
# Test 5: N2C version data CBOR round-trip
# ---------------------------------------------------------------------------


class TestN2CVersionDataRoundTrip:
    """Encode N2C version data, serialize through CBOR, decode, verify match."""

    def test_mainnet_no_query(self) -> None:
        """N2C mainnet version data round-trips through CBOR."""
        original = _encode_n2c_version_data(MAINNET_NETWORK_MAGIC, query=False)
        cbor_bytes = cbor2.dumps(original)
        decoded = cbor2.loads(cbor_bytes)
        magic, query = _decode_n2c_version_data(decoded)
        assert magic == MAINNET_NETWORK_MAGIC
        assert query is False

    def test_mainnet_query(self) -> None:
        """N2C mainnet version data with query=True round-trips."""
        original = _encode_n2c_version_data(MAINNET_NETWORK_MAGIC, query=True)
        cbor_bytes = cbor2.dumps(original)
        decoded = cbor2.loads(cbor_bytes)
        magic, query = _decode_n2c_version_data(decoded)
        assert magic == MAINNET_NETWORK_MAGIC
        assert query is True

    def test_preprod(self) -> None:
        """N2C preprod version data round-trips."""
        original = _encode_n2c_version_data(PREPROD_NETWORK_MAGIC, query=False)
        cbor_bytes = cbor2.dumps(original)
        decoded = cbor2.loads(cbor_bytes)
        magic, query = _decode_n2c_version_data(decoded)
        assert magic == PREPROD_NETWORK_MAGIC
        assert query is False

    def test_preview(self) -> None:
        """N2C preview version data round-trips."""
        original = _encode_n2c_version_data(PREVIEW_NETWORK_MAGIC, query=True)
        cbor_bytes = cbor2.dumps(original)
        decoded = cbor2.loads(cbor_bytes)
        magic, query = _decode_n2c_version_data(decoded)
        assert magic == PREVIEW_NETWORK_MAGIC
        assert query is True

    def test_n2c_version_data_in_propose_format(self) -> None:
        """N2C version data in a MsgProposeVersions-like envelope round-trips.

        Wire format: [0, {versionNumber: versionData}]
        """
        version_table = {
            N2C_V16: _encode_n2c_version_data(MAINNET_NETWORK_MAGIC, False),
            N2C_V17: _encode_n2c_version_data(MAINNET_NETWORK_MAGIC, False),
        }
        msg = [0, version_table]
        cbor_bytes = cbor2.dumps(msg)
        decoded = cbor2.loads(cbor_bytes)

        assert decoded[0] == 0
        table = decoded[1]
        assert isinstance(table, dict)

        for ver_num in [N2C_V16, N2C_V17]:
            magic, query = _decode_n2c_version_data(table[ver_num])
            assert magic == MAINNET_NETWORK_MAGIC
            assert query is False


# ---------------------------------------------------------------------------
# Test 6: N2C version must NOT decode as N2N version (cross-isolation)
# ---------------------------------------------------------------------------


class TestN2CNotN2NVersion:
    """N2C and N2N version data have different structures.

    N2N: [networkMagic, initiatorOnly, peerSharing, query] — 4 elements
    N2C: [networkMagic, query] — 2 elements

    Decoding one as the other must fail. This prevents accidental
    cross-connections between N2N and N2C ports.
    """

    def test_n2c_data_rejected_by_n2n_decoder(self) -> None:
        """N2C version data (2-element list) fails N2N decode."""
        n2c_data = _encode_n2c_version_data(MAINNET_NETWORK_MAGIC, query=False)
        # N2N decoder expects a 4-element list
        with pytest.raises(ValueError, match="4 elements"):
            _decode_version_data(n2c_data)

    def test_n2n_data_rejected_by_n2c_decoder(self) -> None:
        """N2N version data (4-element list) fails N2C decode."""
        n2n_vd = NodeToNodeVersionData(
            network_magic=MAINNET_NETWORK_MAGIC,
            initiator_only_diffusion_mode=False,
            peer_sharing=PeerSharing.DISABLED,
            query=False,
        )
        n2n_data = _encode_version_data(n2n_vd)
        # N2C decoder expects a 2-element list
        with pytest.raises(ValueError, match="2-element list"):
            _decode_n2c_version_data(n2n_data)

    def test_n2c_query_true_rejected_by_n2n(self) -> None:
        """N2C data with query=True still fails N2N decode."""
        n2c_data = _encode_n2c_version_data(MAINNET_NETWORK_MAGIC, query=True)
        with pytest.raises(ValueError, match="4 elements"):
            _decode_version_data(n2c_data)

    def test_n2n_versions_disjoint_from_n2c(self) -> None:
        """N2N version numbers (14, 15) don't overlap with N2C (16+).

        This is a spec-level isolation: the Haskell node uses completely
        different version number ranges for N2N and N2C.
        """
        n2n_versions = {N2N_V14, N2N_V15}
        n2c_versions = {N2C_V16, N2C_V17, N2C_V18, N2C_V19}
        assert n2n_versions.isdisjoint(n2c_versions), (
            f"N2N and N2C version numbers overlap: {n2n_versions & n2c_versions}"
        )

    def test_cbor_roundtrip_preserves_isolation(self) -> None:
        """After CBOR serialization, N2C data still can't be N2N-decoded.

        This ensures CBOR doesn't silently coerce the list structure.
        """
        n2c_data = _encode_n2c_version_data(MAINNET_NETWORK_MAGIC, False)
        cbor_bytes = cbor2.dumps(n2c_data)
        decoded = cbor2.loads(cbor_bytes)
        # Should decode fine as a generic list
        assert isinstance(decoded, list)
        assert len(decoded) == 2
        # But must fail as N2N version data
        with pytest.raises(ValueError, match="4 elements"):
            _decode_version_data(decoded)


# ---------------------------------------------------------------------------
# Test 7: N2C version negotiation with known Cardano N2C versions
# ---------------------------------------------------------------------------


class TestN2CVersionNegotiation:
    """Test N2C version negotiation logic.

    The negotiation follows the same pattern as N2N (from pureHandshake):
    intersect version tables, pick the highest common version, check
    magic agreement. But version data encoding differs.
    """

    @staticmethod
    def _negotiate_n2c(
        client_versions: dict[int, tuple[int, bool]],
        server_versions: dict[int, tuple[int, bool]],
    ) -> tuple[int, int, bool] | None:
        """Pure N2C version negotiation — highest common version.

        Returns (version_number, network_magic, query) or None.
        Mirrors pureHandshake for N2C.
        """
        common = set(client_versions) & set(server_versions)
        if not common:
            return None
        best = max(common)
        c_magic, c_query = client_versions[best]
        s_magic, _ = server_versions[best]
        if c_magic != s_magic:
            return None
        # For N2C, query is from the client (client decides)
        return (best, s_magic, c_query)

    def test_single_common_version(self) -> None:
        """Client and server share exactly one version."""
        client = {N2C_V16: (MAINNET_NETWORK_MAGIC, False)}
        server = {N2C_V16: (MAINNET_NETWORK_MAGIC, False)}
        result = self._negotiate_n2c(client, server)
        assert result is not None
        ver, magic, query = result
        assert ver == N2C_V16
        assert magic == MAINNET_NETWORK_MAGIC
        assert query is False

    def test_multiple_common_picks_highest(self) -> None:
        """When multiple versions are common, pick the highest."""
        client = {
            N2C_V16: (MAINNET_NETWORK_MAGIC, False),
            N2C_V17: (MAINNET_NETWORK_MAGIC, False),
        }
        server = {
            N2C_V16: (MAINNET_NETWORK_MAGIC, False),
            N2C_V17: (MAINNET_NETWORK_MAGIC, False),
            N2C_V18: (MAINNET_NETWORK_MAGIC, False),
        }
        result = self._negotiate_n2c(client, server)
        assert result is not None
        ver, _, _ = result
        assert ver == N2C_V17  # highest in client's table

    def test_no_common_version(self) -> None:
        """No common version returns None."""
        client = {N2C_V16: (MAINNET_NETWORK_MAGIC, False)}
        server = {N2C_V18: (MAINNET_NETWORK_MAGIC, False)}
        result = self._negotiate_n2c(client, server)
        assert result is None

    def test_magic_mismatch_rejected(self) -> None:
        """Different network magic causes negotiation failure."""
        client = {N2C_V16: (MAINNET_NETWORK_MAGIC, False)}
        server = {N2C_V16: (PREPROD_NETWORK_MAGIC, False)}
        result = self._negotiate_n2c(client, server)
        assert result is None

    def test_query_from_client(self) -> None:
        """Query flag comes from the client's version data."""
        client = {N2C_V16: (MAINNET_NETWORK_MAGIC, True)}
        server = {N2C_V16: (MAINNET_NETWORK_MAGIC, False)}
        result = self._negotiate_n2c(client, server)
        assert result is not None
        _, _, query = result
        assert query is True  # Client's query flag

    def test_n2n_versions_rejected_in_n2c_negotiation(self) -> None:
        """N2N version numbers don't match N2C version numbers.

        A client proposing N2N versions (14, 15) to an N2C server
        that only knows N2C versions (16+) finds no intersection.
        """
        client_n2n = {
            N2N_V14: (MAINNET_NETWORK_MAGIC, False),
            N2N_V15: (MAINNET_NETWORK_MAGIC, False),
        }
        server_n2c = {
            N2C_V16: (MAINNET_NETWORK_MAGIC, False),
            N2C_V17: (MAINNET_NETWORK_MAGIC, False),
        }
        result = self._negotiate_n2c(client_n2n, server_n2c)
        assert result is None

    def test_full_n2c_version_range(self) -> None:
        """Negotiate across the full range of known N2C versions."""
        client = {v: (MAINNET_NETWORK_MAGIC, False) for v in [N2C_V16, N2C_V17, N2C_V18, N2C_V19]}
        server = {v: (MAINNET_NETWORK_MAGIC, False) for v in [N2C_V16, N2C_V17, N2C_V18, N2C_V19]}
        result = self._negotiate_n2c(client, server)
        assert result is not None
        ver, _, _ = result
        assert ver == N2C_V19  # highest common
