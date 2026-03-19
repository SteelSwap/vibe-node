"""Typed protocol state machine framework for Ouroboros miniprotocols.

The Ouroboros network layer uses a typed protocol framework where each
miniprotocol is a state machine. At every state, exactly one peer has
"agency" — the right to send the next message. This module defines the
core abstractions:

- **Agency**: Who can send at a given state (Client, Server, or Nobody).
- **PeerRole**: Which side of the connection we are (Initiator or Responder).
- **Message**: A typed transition from one protocol state to another.
- **Protocol**: Abstract definition of a miniprotocol's state machine.

Spec reference: The typed-protocols framework is described in the
ouroboros-network documentation and the Network Design Specification.
The Haskell implementation lives in ouroboros-network/typed-protocols.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

__all__ = [
    "Agency",
    "PeerRole",
    "Message",
    "Protocol",
    "ProtocolError",
]


class Agency(enum.Enum):
    """Who has the right to send the next message at a given protocol state.

    In the Ouroboros typed-protocols framework, at every state exactly one
    peer has agency. ``Nobody`` marks terminal states where no further
    messages are exchanged.
    """

    Client = "client"
    Server = "server"
    Nobody = "nobody"


class PeerRole(enum.Enum):
    """Which side of the protocol connection we represent.

    The Initiator is typically the client that opens the connection.
    The Responder is typically the server that accepts connections.

    The mapping to agency is:
    - When Agency is Client: Initiator has agency (can send).
    - When Agency is Server: Responder has agency (can send).
    - When Agency is Nobody: neither peer has agency (terminal).
    """

    Initiator = "initiator"
    Responder = "responder"


# Type variable for protocol states (typically an Enum).
St = TypeVar("St")


class Message(Generic[St]):
    """A typed protocol message representing a state transition.

    Each message carries the state it transitions from and the state it
    transitions to. Concrete message classes should set these as class
    attributes or pass them to __init__.

    In the Haskell implementation this is modeled with GADTs
    (``Message ps (st :: ps) (st' :: ps)``). We use a simpler approach:
    each Message instance records its from_state and to_state.
    """

    __slots__ = ("from_state", "to_state")

    def __init__(self, from_state: St, to_state: St) -> None:
        self.from_state: St = from_state
        self.to_state: St = to_state

    def __repr__(self) -> str:
        cls = type(self).__name__
        return f"{cls}({self.from_state!r} -> {self.to_state!r})"


class ProtocolError(Exception):
    """Raised when a protocol rule is violated.

    This covers agency violations (wrong peer trying to send), invalid
    state transitions (message not valid for current state), and attempts
    to communicate in a terminal state.
    """


class Protocol(ABC, Generic[St]):
    """Abstract definition of a miniprotocol state machine.

    Subclasses define the set of states and the agency map. The agency
    map determines who can send at each state. Message validity is
    enforced by the Peer class at runtime.

    In the Haskell typed-protocols library, this corresponds to the
    ``Protocol`` type class with associated types for ``State``,
    ``Message``, and ``ServerHasAgency``/``ClientHasAgency``/``NobodyHasAgency``.
    """

    @abstractmethod
    def initial_state(self) -> St:
        """Return the initial state of the protocol."""
        ...

    @abstractmethod
    def agency(self, state: St) -> Agency:
        """Return who has agency at the given state."""
        ...

    @abstractmethod
    def valid_messages(self, state: St) -> frozenset[type[Message[St]]]:
        """Return the set of message types valid at the given state.

        This allows runtime validation that a message type is permitted
        in the current state, independent of agency checks.
        """
        ...
