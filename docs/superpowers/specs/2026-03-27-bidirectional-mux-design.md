# Bidirectional Mux + Full-Duplex Connections

## Problem

Haskell's inbound governor expects bidirectional miniprotocol traffic on every `InitiatorAndResponder` connection. Vibe-node's mux only supports one channel per protocol ID (not per direction), so it can only run responder-side miniprotocols on inbound connections. Haskell demotes vibe-node connections with `ExceededTimeLimit` after seeing zero initiator-direction traffic, causing 32+ disconnects per 5-minute run and limiting forge share to 24%.

## Goal

Match Haskell's connection model: each TCP connection runs the full miniprotocol bundle in BOTH directions (initiator + responder), keyed by `(protocol_id, direction)`. This eliminates `DemotedToColdRemote`, `ExceededTimeLimit`, and enables 33% forge share.

## Haskell Reference

- `Network.Mux.Ingress.demuxer` — flips direction bit when routing: remote's initiator → local's responder channel
- `Network.Mux.Types.MiniProtocolInfo` — `InitiatorAndResponderProtocol` registers two entries per protocol number
- `Ouroboros.Network.ConnectionManager` — `protocolIdleTimeout = 5s` demotes connections with no responder activity
- `Ouroboros.Network.Protocol.Limits` — `shortWait = 10s` for chain-sync `canAwaitTimeout`

## Design

### Component 1: Mux dual-channel routing

**File**: `packages/vibe-core/src/vibe/core/multiplexer/mux.py`

Change `_channels` from `dict[int, MiniProtocolChannel]` to `dict[tuple[int, bool], MiniProtocolChannel]` where the tuple is `(protocol_id, is_initiator_dir)`.

New API:

```python
def add_protocol_pair(self, protocol_id: int) -> tuple[MiniProtocolChannel, MiniProtocolChannel]:
    """Register both initiator and responder channels for a protocol.

    Returns (initiator_channel, responder_channel).
    """
```

Keep `add_protocol(protocol_id)` as a convenience that registers a single direction based on `self._is_initiator` (backward compatibility for simple cases).

**Receiver loop change**: When a segment arrives, flip the direction to find the local channel:

```python
# Remote's initiator → our responder, and vice versa
local_dir = not segment.is_initiator
channel = self._channels.get((segment.protocol_id, local_dir))
```

**Sender loop change**: The round-robin iterates over all channels (both directions). Each channel's `is_initiator` flag determines the direction bit in the outbound segment header.

### Component 2: MiniProtocolChannel direction awareness

**File**: `packages/vibe-core/src/vibe/core/multiplexer/channel.py` (or wherever it's defined)

Add `is_initiator_dir: bool` to `MiniProtocolChannel`. The sender uses this to set the correct mode bit on outbound segments.

### Component 3: Inbound server runs full duplex

**File**: `packages/vibe-cardano/src/vibe/cardano/node/inbound_server.py`

When an inbound connection arrives and negotiates `InitiatorAndResponder`:

1. Call `mux.add_protocol_pair(proto_id)` for each N2N protocol — gets `(init_ch, resp_ch)` per protocol
2. Start **responder** miniprotocols on `resp_ch` (already done): chain-sync server, block-fetch server, keep-alive server, tx-sub server
3. Start **initiator** miniprotocols on `init_ch` (new): chain-sync client, block-fetch client, keep-alive client, tx-sub client

The initiator side reuses the same protocol runner code from `peer_manager.py`. Extract the chain-sync client setup, block-fetch setup, and keep-alive client setup into shared functions callable from both `peer_manager` and `inbound_server`.

### Component 4: Outbound connections also run responders

**File**: `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py`

When connecting outbound with `InitiatorAndResponder`:

1. Call `mux.add_protocol_pair(proto_id)` for each N2N protocol
2. Start **initiator** miniprotocols on `init_ch` (already done): chain-sync client, block-fetch client, keep-alive client, tx-sub client
3. Start **responder** miniprotocols on `resp_ch` (new): chain-sync server, block-fetch server, keep-alive server, tx-sub server

### Component 5: Revert handshake to InitiatorAndResponder

**File**: `packages/vibe-cardano/src/vibe/cardano/network/handshake_protocol.py`

Remove `initiator_only=True`. Both client and server advertise `InitiatorAndResponder` since we now support it.

### Component 6: Shared miniprotocol launcher

**File**: `packages/vibe-cardano/src/vibe/cardano/node/miniprotocol_bundle.py` (new)

Extract the miniprotocol launch logic into shared functions:

```python
async def launch_initiator_bundle(
    channels: dict[int, MiniProtocolChannel],
    chain_db, node_kernel, mempool, config, stop_event,
    block_received_event=None,
) -> list[asyncio.Task]:
    """Start chain-sync client, block-fetch client, keep-alive client, tx-sub client."""

async def launch_responder_bundle(
    channels: dict[int, MiniProtocolChannel],
    chain_db, node_kernel, mempool, stop_event,
) -> list[asyncio.Task]:
    """Start chain-sync server, block-fetch server, keep-alive server, tx-sub server."""
```

Both `peer_manager` and `inbound_server` call these functions. This eliminates the duplicated miniprotocol setup code.

## Data Flow

```
Inbound TCP connection (Haskell → vibe-node):

  Haskell sends initiator-dir segments ──► vibe-node responder channels
    chain-sync RequestNext (M=0)      ──► chain-sync server (resp_ch)
    keep-alive KeepAlive (M=0)        ──► keep-alive server (resp_ch)

  Vibe-node sends initiator-dir segments ──► Haskell responder channels
    chain-sync RequestNext (M=0)      ──► Haskell chain-sync server
    keep-alive KeepAlive (M=0)        ──► Haskell keep-alive server

  Both directions: mux round-robin over all channels (init + resp)
```

## What This Fixes

- `DemotedToColdRemote` → 0 (Haskell sees initiator traffic from vibe-node)
- `ExceededTimeLimit` → 0 (connection stays warm, chain-sync not disrupted)
- Forge share → ~33% (blocks propagate reliably between all 3 nodes)

## Testing

- Unit test: mux routes segments to correct `(protocol_id, direction)` channel
- Unit test: `add_protocol_pair` returns two independent channels
- Unit test: sender sets correct direction bit per channel
- Integration: devnet 5-min run with 0 VRFKeyBadProof, 0 ExceededTimeLimit, ~33% vibe share

## Out of Scope

- `RestrictedVRFTiebreaker` for Conway (slot distance check) — separate task
- Peer sharing — disabled, not needed for devnet
- Real mempool integration for tx-submission — stub replies are fine
