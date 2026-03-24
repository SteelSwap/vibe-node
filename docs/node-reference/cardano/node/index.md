# Node

Node orchestration — the 3-thread model, forge loop, peer management, and the NodeKernel consensus state.

## Architecture

The node runs as 3 OS threads coordinated via STM (Software Transactional Memory):

- **Thread 1 (main):** Forge loop — slot-by-slot leadership check and block production
- **Thread 2 (daemon):** Receive — peer connections, chain-sync/block-fetch clients
- **Thread 3 (daemon):** Serve — inbound connections, chain-sync/block-fetch servers

Shared state (tip, nonce, stake distribution, chain fragment) is accessed via STM TVars. The forge loop uses `atomically()` to read consistent snapshots and detect conflicts.

## Modules

### Forge Loop

Slot-by-slot leader check and block forging. Runs as a sync OS thread, wakes on slot boundaries or block arrival.

::: vibe.cardano.node.forge_loop
    options:
      show_source: false
      members_order: source

### Node Kernel

Praos chain-dependent state — epoch nonces, delegation, stake distribution, protocol parameters. Nonce checkpoints for fork switch rollback.

::: vibe.cardano.node.kernel
    options:
      show_source: false
      members_order: source

### Peer Manager

Outbound N2N peer connections with automatic reconnect and exponential backoff.

::: vibe.cardano.node.peer_manager
    options:
      show_source: false
      members_order: source

### Configuration

Node configuration — network magic, peers, pool keys, genesis parameters.

::: vibe.cardano.node.config
    options:
      show_source: false
      members_order: source
