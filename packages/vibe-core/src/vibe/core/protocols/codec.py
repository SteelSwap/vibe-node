"""Codec — encode/decode typed protocol messages to/from CBOR bytes.

Each Ouroboros miniprotocol defines its own CBOR wire format. The Codec
abstraction lets the ProtocolRunner remain protocol-agnostic: it delegates
serialization to a concrete codec provided by each miniprotocol
(handshake, chain-sync, block-fetch, etc.).

Haskell reference:
    Network.TypedProtocol.Codec (Codec, CodecFailure)
    The Haskell Codec is parameterized by protocol, peer-role, and monad.
    Our version is simpler: a pair of encode/decode callables, with the
    concrete type determined by the miniprotocol that supplies the codec.

Spec reference:
    CDDL schemas define the wire format for each miniprotocol's messages.
    The codec bridges between our typed Message objects and CBOR bytes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from vibe.core.protocols.agency import Message

__all__ = ["Codec", "CodecError"]


class CodecError(Exception):
    """Raised when encoding or decoding a protocol message fails.

    Covers malformed CBOR, unexpected message tags, missing fields,
    and any other serialization/deserialization error.
    """


@runtime_checkable
class Codec(Protocol):
    """Protocol (structural type) for miniprotocol message codecs.

    Each miniprotocol supplies a concrete implementation that knows how
    to serialize its message types to CBOR bytes and deserialize them
    back. The ProtocolRunner calls these methods without knowing the
    specific miniprotocol.

    The encode method receives a typed Message and returns raw bytes.
    The decode method receives raw bytes and returns a typed Message.

    Implementations should raise CodecError on failure rather than
    letting lower-level exceptions propagate.
    """

    def encode(self, message: Message) -> bytes:
        """Encode a typed protocol message to CBOR bytes.

        Args:
            message: The message to serialize.

        Returns:
            The CBOR-encoded bytes.

        Raises:
            CodecError: If encoding fails.
        """
        ...

    def decode(self, data: bytes) -> Message:
        """Decode CBOR bytes into a typed protocol message.

        Args:
            data: The CBOR-encoded bytes to deserialize.

        Returns:
            The decoded Message with correct from_state and to_state.

        Raises:
            CodecError: If decoding fails (malformed data, unknown tag, etc.).
        """
        ...
