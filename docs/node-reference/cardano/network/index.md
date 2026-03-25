# Network

Ouroboros miniprotocol implementations — both node-to-node (N2N) and node-to-client (N2C).

## Protocols

### Handshake

Version negotiation on new connections. Establishes protocol version and network magic.

::: vibe.cardano.network.handshake
    options:
      show_source: false
      members_order: source

### Chain-Sync

Header-based chain synchronization — roll forward/backward with intersection finding.

::: vibe.cardano.network.chainsync
    options:
      show_source: false
      members_order: source

### Block-Fetch

Range-based block body fetching — request ranges of blocks by point, receive streaming responses.

::: vibe.cardano.network.blockfetch
    options:
      show_source: false
      members_order: source

### Tx-Submission

Pull-based transaction submission — server requests tx IDs and bodies from the client.

::: vibe.cardano.network.txsubmission
    options:
      show_source: false
      members_order: source

### Keep-Alive

Periodic ping/pong to detect dead connections.

::: vibe.cardano.network.keepalive
    options:
      show_source: false
      members_order: source
