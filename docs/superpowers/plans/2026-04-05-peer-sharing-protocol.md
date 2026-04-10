# Peer Sharing Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the N2N peer sharing miniprotocol (protocol 10) so Haskell nodes discover our address via peer sharing, connect inbound, and pull our forged blocks — fixing the block propagation gap that causes all forged blocks to be orphaned on preview.

**Architecture:** Peer sharing is a simple request-response protocol (StIdle → StBusy → StIdle loop). The client asks peers for known addresses; the server responds with a deterministic salt-rotated subset of connected peers. We follow the existing miniprotocol pattern: types/codec file + protocol runner file, wired into the miniprotocol bundle and mux channel registration. The handshake flag switches from DISABLED to ENABLED.

**Tech Stack:** Python 3.14, cbor2, asyncio, pytest. Follows existing vibe-core Protocol/ProtocolRunner framework.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `packages/vibe-cardano/src/vibe/cardano/network/peersharing.py` | Create | Types, CBOR codec, protocol ID constant, peer address encoding |
| `packages/vibe-cardano/src/vibe/cardano/network/peersharing_protocol.py` | Create | State machine, typed messages, client/server runners |
| `packages/vibe-cardano/src/vibe/cardano/node/peer_registry.py` | Create | Tracks known peers for sharing (salt-rotated selection) |
| `packages/vibe-cardano/tests/network/test_peersharing.py` | Create | Codec parity tests, client-server round-trip tests |
| `packages/vibe-cardano/src/vibe/cardano/network/handshake.py` | Modify | Change default peer_sharing to ENABLED |
| `packages/vibe-cardano/src/vibe/cardano/node/miniprotocol_bundle.py` | Modify | Add peer sharing client+server to bundles |
| `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py` | Modify | Register protocol 10 in mux, wire peer registry |
| `packages/vibe-cardano/src/vibe/cardano/node/inbound_server.py` | Modify | Register protocol 10 for inbound connections |

## Parallelization

Tasks 1-3 are independent and can be implemented in parallel:
- **Task 1:** Types/codec (peersharing.py)
- **Task 2:** Protocol state machine + runners (peersharing_protocol.py)
- **Task 3:** Peer registry (peer_registry.py)

Tasks 4-5 depend on Tasks 1-3:
- **Task 4:** Integration (bundle, mux, handshake) — depends on all of 1-3
- **Task 5:** End-to-end tests — depends on Task 4

```
Task 1 (types/codec) ──────┐
Task 2 (protocol runners) ──┼──→ Task 4 (integration) ──→ Task 5 (e2e tests)
Task 3 (peer registry) ────┘
```

---

### Task 1: Types and CBOR Codec (`peersharing.py`)

**Files:**
- Create: `packages/vibe-cardano/src/vibe/cardano/network/peersharing.py`
- Create: `packages/vibe-cardano/tests/network/test_peersharing.py` (codec tests only)

**Haskell reference:**
- `Ouroboros/Network/Protocol/PeerSharing/Type.hs`
- `Ouroboros/Network/Protocol/PeerSharing/Codec.hs`
- `Ouroboros/Network/PeerSelection/PeerSharing/Codec.hs` (address encoding)
- CDDL: `cardano-diffusion/protocols/cddl/specs/peer-sharing-v14.cddl`

**Wire format (CDDL v14):**
```
msgShareRequest = [0, word8]           -- request N peers
msgSharePeers   = [1, [* peerAddress]] -- response with peer list
msgDone         = [2]                  -- terminate

peerAddress = [0, word32, word16]                              -- IPv4 + port
            / [1, word32, word32, word32, word32, word16]      -- IPv6 + port
```

- [ ] **Step 1: Write codec tests**

Create `packages/vibe-cardano/tests/network/test_peersharing.py` with tests for:
- Encode/decode MsgShareRequest with various amounts (0, 1, 10, 255)
- Encode/decode MsgSharePeers with empty list, IPv4 addresses, IPv6 addresses, mixed
- Encode/decode MsgDone
- Encode/decode PeerAddress for IPv4 and IPv6
- Round-trip property: decode(encode(msg)) == msg
- Reject invalid: amount > 255, malformed addresses, wrong tag numbers

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/vibe-cardano/tests/network/test_peersharing.py -v`
Expected: ImportError — module doesn't exist yet

- [ ] **Step 3: Implement peersharing.py**

Create `packages/vibe-cardano/src/vibe/cardano/network/peersharing.py` with:
- `PEER_SHARING_PROTOCOL_ID = 10`
- `PeerAddress` dataclass (ip: str, port: int, is_ipv6: bool)
- `MsgShareRequest(amount: int)` — msg_id = 0
- `MsgSharePeers(peers: list[PeerAddress])` — msg_id = 1
- `MsgDone()` — msg_id = 2
- `encode_peer_address(addr) -> list` — [0, word32, word16] for IPv4, [1, w1,w2,w3,w4, word16] for IPv6
- `decode_peer_address(term) -> PeerAddress`
- `encode_share_request(amount) -> bytes`
- `encode_share_peers(peers) -> bytes`
- `encode_done() -> bytes`
- `decode_message(data: bytes) -> MsgShareRequest | MsgSharePeers | MsgDone`

IPv4 address encoding: pack IP octets as big-endian uint32. IPv6: pack as four big-endian uint32s. Port as uint16.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/vibe-cardano/tests/network/test_peersharing.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```
feat: add peer sharing types and CBOR codec (miniprotocol 10)
```

---

### Task 2: Protocol State Machine and Runners (`peersharing_protocol.py`)

**Files:**
- Create: `packages/vibe-cardano/src/vibe/cardano/network/peersharing_protocol.py`
- Modify: `packages/vibe-cardano/tests/network/test_peersharing.py` (add protocol tests)

**Depends on:** Task 1 (types/codec)

**Haskell reference:**
- `Ouroboros/Network/Protocol/PeerSharing/Client.hs`
- `Ouroboros/Network/Protocol/PeerSharing/Server.hs`

**Protocol FSM:**
```
StIdle  --[MsgShareRequest]--> StBusy    (client has agency in StIdle)
StBusy  --[MsgSharePeers]---> StIdle     (server has agency in StBusy)
StIdle  --[MsgDone]---------> StDone     (client has agency in StIdle)
StDone  = terminal (nobody has agency)
```

- [ ] **Step 1: Write protocol round-trip tests**

Add to `test_peersharing.py`:
- Test client sends MsgShareRequest, server receives it, sends MsgSharePeers, client receives
- Test client sends MsgDone, protocol reaches StDone
- Test multiple request-response cycles in sequence
- Test server validates amount (doesn't return more than requested)
- Use MockChannel pattern from existing tests (see test_network_parity.py)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/vibe-cardano/tests/network/test_peersharing.py -v -k protocol`
Expected: ImportError

- [ ] **Step 3: Implement peersharing_protocol.py**

Create with:
- `PeerSharingState` enum: StIdle, StBusy, StDone
- Typed messages: `PsMsgShareRequest`, `PsMsgSharePeers`, `PsMsgDone` (wrapping inner types)
- `PeerSharingProtocol` class with agency map (StIdle=Client, StBusy=Server, StDone=Nobody)
- `PeerSharingCodec` class (encode/decode using peersharing.py functions)
- `run_peer_sharing_client(channel, on_peers_received, request_interval, max_peers_per_request, stop_event)`:
  - Periodic loop: every `request_interval` seconds, send MsgShareRequest(amount)
  - Receive MsgSharePeers, validate len(peers) <= amount, call on_peers_received callback
  - On stop_event: send MsgDone
- `run_peer_sharing_server(channel, peer_provider, stop_event)`:
  - Wait for MsgShareRequest
  - Call `peer_provider(amount)` to get peers to share
  - Send MsgSharePeers(peers)
  - Loop until MsgDone received

Client parameters:
- `request_interval: float = 60.0` — how often to ask for peers (conservative default)
- `max_peers_per_request: int = 10` — matches Haskell ps_POLICY_PEER_SHARE_MAX_PEERS
- `on_peers_received: Callable[[list[PeerAddress]], Awaitable[None]]` — callback with discovered peers

Server parameters:
- `peer_provider: Callable[[int], Awaitable[list[PeerAddress]]]` — given requested amount, return peers to share

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/vibe-cardano/tests/network/test_peersharing.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```
feat: add peer sharing protocol state machine, client and server runners
```

---

### Task 3: Peer Registry (`peer_registry.py`)

**Files:**
- Create: `packages/vibe-cardano/src/vibe/cardano/node/peer_registry.py`
- Create: `packages/vibe-cardano/tests/node/test_peer_registry.py`

**Independent of Tasks 1-2.** No protocol knowledge needed — pure data structure.

**Haskell reference:**
- `Ouroboros/Network/PeerSharing.hs` — `computePeerSharingPeers`
- Salt rotation: `ps_POLICY_PEER_SHARE_STICKY_TIME = 823` seconds
- Max peers: `ps_POLICY_PEER_SHARE_MAX_PEERS = 10`

The peer registry tracks connected peer addresses and provides a deterministic salt-rotated selection when asked for peers to share.

- [ ] **Step 1: Write peer registry tests**

Create `packages/vibe-cardano/tests/node/test_peer_registry.py`:
- `test_add_remove_peers` — add peers, remove peers, verify state
- `test_get_peers_respects_max` — requesting 5 from 20 peers returns exactly 5
- `test_get_peers_capped_at_policy_max` — requesting 255 returns at most 10 (policy max)
- `test_get_peers_deterministic_with_same_salt` — same salt, same peers selected
- `test_get_peers_changes_after_salt_rotation` — after 823s, different selection
- `test_get_peers_empty_registry` — returns empty list
- `test_excludes_requesting_peer` — don't share a peer's own address back to them

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest packages/vibe-cardano/tests/node/test_peer_registry.py -v`
Expected: ImportError

- [ ] **Step 3: Implement peer_registry.py**

Create `packages/vibe-cardano/src/vibe/cardano/node/peer_registry.py`:

```python
class PeerRegistry:
    """Tracks connected peers and provides salt-rotated selection for peer sharing.
    
    Haskell reference: computePeerSharingPeers in PeerSharing.hs
    """
    
    POLICY_MAX_PEERS: int = 10
    POLICY_STICKY_TIME: float = 823.0  # seconds
    
    def __init__(self) -> None:
        self._peers: dict[str, PeerAddress] = {}  # addr_key -> PeerAddress
        self._salt: int = random.randint(0, 2**32 - 1)
        self._salt_expires: float = time.monotonic() + self.POLICY_STICKY_TIME
    
    def add_peer(self, addr: PeerAddress) -> None: ...
    def remove_peer(self, addr: PeerAddress) -> None: ...
    
    def get_peers(self, amount: int, exclude: PeerAddress | None = None) -> list[PeerAddress]:
        """Return up to `amount` peers (capped at POLICY_MAX_PEERS).
        
        Uses deterministic salt-based selection that rotates every
        POLICY_STICKY_TIME seconds, matching Haskell's sticky peer list.
        """
        self._maybe_rotate_salt()
        candidates = [p for p in self._peers.values() if p != exclude]
        n = min(amount, self.POLICY_MAX_PEERS, len(candidates))
        if n == 0:
            return []
        # Sort by hash(salt, peer) for deterministic selection
        candidates.sort(key=lambda p: hash((self._salt, p.ip, p.port)))
        return candidates[:n]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/vibe-cardano/tests/node/test_peer_registry.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```
feat: add peer registry with salt-rotated selection for peer sharing
```

---

### Task 4: Integration (Mux, Bundle, Handshake)

**Files:**
- Modify: `packages/vibe-cardano/src/vibe/cardano/network/handshake.py` (line ~264)
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/miniprotocol_bundle.py`
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/peer_manager.py` (line ~327)
- Modify: `packages/vibe-cardano/src/vibe/cardano/node/inbound_server.py`

**Depends on:** Tasks 1, 2, 3

Four independent changes that wire peer sharing into the node. Each is a small, testable modification.

- [ ] **Step 1: Enable peer sharing in handshake**

In `handshake.py`, change `build_version_table` default:
```python
# Before:
peer_sharing: PeerSharing = PeerSharing.DISABLED
# After:
peer_sharing: PeerSharing = PeerSharing.ENABLED
```

- [ ] **Step 2: Register protocol 10 in outbound mux (peer_manager.py)**

In `peer_manager.py` around line 327, add `PEER_SHARING_PROTOCOL_ID` to the protocol list:
```python
from vibe.cardano.network.peersharing import PEER_SHARING_PROTOCOL_ID

for proto_id in [CHAIN_SYNC_N2N_ID, BLOCK_FETCH_N2N_ID, TX_SUBMISSION_N2N_ID, 
                 KEEP_ALIVE_PROTOCOL_ID, PEER_SHARING_PROTOCOL_ID]:
    init_ch, resp_ch = mux.add_protocol_pair(proto_id)
    init_channels[proto_id] = init_ch
    resp_channels[proto_id] = resp_ch
```

Also wire the PeerRegistry:
- Add `peer_registry: PeerRegistry` to PeerManager.__init__
- On peer connect: `self._peer_registry.add_peer(PeerAddress(ip, port))`
- On peer disconnect: `self._peer_registry.remove_peer(PeerAddress(ip, port))`

- [ ] **Step 3: Register protocol 10 in inbound server**

In `inbound_server.py`, add protocol 10 to the mux channel registration for inbound connections, following the same pattern as outbound.

- [ ] **Step 4: Add peer sharing to miniprotocol bundles**

In `miniprotocol_bundle.py`, add to `launch_responder_bundle`:
```python
from vibe.cardano.network.peersharing import PEER_SHARING_PROTOCOL_ID
from vibe.cardano.network.peersharing_protocol import run_peer_sharing_server

if PEER_SHARING_PROTOCOL_ID in channels and peer_registry is not None:
    async def _peer_provider(amount: int) -> list[PeerAddress]:
        return peer_registry.get_peers(amount, exclude=<requesting_peer>)
    
    tasks.append(asyncio.create_task(
        _safe(run_peer_sharing_server(
            channels[PEER_SHARING_PROTOCOL_ID],
            peer_provider=_peer_provider,
            stop_event=stop_event,
        ), "peer-sharing"),
        name=f"ps-server-{peer_info}",
    ))
```

Add to `launch_initiator_bundle`:
```python
from vibe.cardano.network.peersharing import PEER_SHARING_PROTOCOL_ID
from vibe.cardano.network.peersharing_protocol import run_peer_sharing_client

if PEER_SHARING_PROTOCOL_ID in channels:
    async def _on_peers(peers: list[PeerAddress]) -> None:
        for peer in peers:
            logger.info("PeerSharing: discovered peer %s:%d", peer.ip, peer.port)
            # Future: add to peer manager's candidate set
    
    tasks.append(asyncio.create_task(
        _safe(run_peer_sharing_client(
            channels[PEER_SHARING_PROTOCOL_ID],
            on_peers_received=_on_peers,
            stop_event=stop_event,
        ), "peer-sharing"),
        name=f"ps-client-{peer_info}",
    ))
```

Update function signatures to accept `peer_registry` parameter.

- [ ] **Step 5: Update existing handshake tests**

The test `test_negotiate_uses_server_peer_sharing` in `test_network_parity.py` may need updating since the default changed from DISABLED to ENABLED.

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest packages/vibe-cardano/tests/ -v --tb=short`
Expected: All PASS (including updated handshake tests)

- [ ] **Step 7: Commit**

```
feat: wire peer sharing protocol into mux, bundles, and handshake
```

---

### Task 5: End-to-End and Integration Tests

**Files:**
- Modify: `packages/vibe-cardano/tests/network/test_peersharing.py` (add e2e tests)

**Depends on:** Task 4

- [ ] **Step 1: Write integration test — full client-server round trip through mux**

Test that a peer sharing client and server can exchange peers through MockChannel:
- Client requests 5 peers
- Server has a PeerRegistry with 20 peers
- Client receives <= 5 peers
- Client sends MsgDone
- Both sides reach StDone cleanly

- [ ] **Step 2: Write integration test — peer sharing with real mux**

Test using actual Multiplexer + Bearer (loopback) that protocol 10 traffic routes correctly alongside other protocols. Verify no interference with chain-sync or keep-alive on the same connection.

- [ ] **Step 3: Write integration test — handshake advertises peer sharing**

Connect to a Haskell node on preview and verify the negotiated version data includes `peer_sharing=ENABLED`. This confirms the Haskell node sees us as a peer-sharing-capable node.

- [ ] **Step 4: Run all tests**

Run: `uv run pytest packages/vibe-cardano/tests/ -v --tb=short`
Expected: All PASS

- [ ] **Step 5: Commit**

```
test: add peer sharing integration and e2e tests
```

---

## Verification

After all tasks complete, rebuild and deploy the preview-sync vibe-node:

```bash
docker compose -f infra/preview-sync/docker-compose.preview-sync.yml build vibe-node
docker compose -f infra/preview-sync/docker-compose.preview-sync.yml up -d vibe-node
```

Monitor logs for:
1. `PeerSharing` in handshake negotiation logs
2. Peer sharing server receiving MsgShareRequest from Haskell peers
3. Peer sharing client discovering new peers
4. Inbound connections from discovered peers
5. Chain-sync server activity (Haskell peers pulling our chain)
6. Forged blocks appearing on the canonical chain (Koios verification)
