# Private Devnet — 3-Node Cluster

A private Cardano devnet for integration testing vibe-node alongside Haskell cardano-nodes.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  haskell-node-1 │◄───►│  haskell-node-2 │◄───►│    vibe-node    │
│  (block producer│     │  (block producer │     │  (passive sync) │
│   pool1 keys)   │     │   pool2 keys)    │     │   pool3 keys)   │
│  port 30001     │     │  port 30002      │     │  port 30003     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        ▲                                                ▲
        └────────────────────────────────────────────────┘
                        full mesh topology
```

## Configuration

| Parameter | Value | Notes |
|-----------|-------|-------|
| Slot length | 0.2s | Fast block production for testing |
| Epoch length | 100 slots | ~20 seconds per epoch |
| Security parameter (k) | 10 | Fast finality (vs 2160 on mainnet) |
| Active slot coefficient (f) | 0.1 | ~1 block every 2 seconds |
| Network magic | 42 | Private devnet |
| Pools | 3 | Equal stake (1M tADA each) |
| Era | Conway | All hard forks at epoch 0 |

## Quick Start

### 1. Generate keys

```bash
cd infra/devnet
./scripts/generate-keys.sh
```

This generates fresh cryptographic keys for all 3 pools. Requires `cardano-cli` >= 10.x
or Docker.

### 2. Start the devnet

```bash
docker compose -f docker-compose.devnet.yml up -d
```

The genesis-init container sets `systemStart` to 30 seconds from launch, giving all
nodes time to start before block production begins.

### 3. Monitor tip agreement

```bash
# From host (polls via docker exec)
python scripts/monitor-tips.py --interval 10 --duration 3600

# Or as a Docker service
docker compose -f docker-compose.devnet.yml --profile monitoring up -d monitor
```

### 4. Check node status

```bash
# Haskell node 1
docker exec devnet-haskell-node-1-1 cardano-cli latest query tip --testnet-magic 42 --socket-path /ipc/node.socket

# Haskell node 2
docker exec devnet-haskell-node-2-1 cardano-cli latest query tip --testnet-magic 42 --socket-path /ipc/node.socket
```

### 5. Tear down

```bash
docker compose -f docker-compose.devnet.yml down -v
```

The `-v` flag removes volumes (chain data). Omit it to preserve state across restarts.

## Directory Structure

```
infra/devnet/
  docker-compose.devnet.yml   # 3-node devnet stack
  Dockerfile.vibe-node         # Vibe-node container image
  config/
    config.json                # cardano-node configuration
  genesis/
    shelley-genesis.json       # Shelley genesis (systemStart patched at runtime)
    byron-genesis.json         # Byron genesis (immediate transition to Shelley)
    alonzo-genesis.json        # Alonzo genesis (Plutus cost models)
    conway-genesis.json        # Conway genesis (governance params)
  topology/
    haskell-node-1.json        # Topology for node 1
    haskell-node-2.json        # Topology for node 2
    vibe-node.json             # Topology for vibe-node
  keys/                        # Generated keys (NOT in git)
    pool1/                     # Haskell node 1 keys
    pool2/                     # Haskell node 2 keys
    pool3/                     # Vibe node keys
  scripts/
    generate-keys.sh           # Key generation script
    monitor-tips.py            # Tip agreement monitor
```

## Troubleshooting

### Nodes not producing blocks
- Check that keys were generated: `ls keys/pool1/opcert.cert`
- Check genesis systemStart hasn't passed: the init container sets it 30s in the future
- Check logs: `docker compose -f docker-compose.devnet.yml logs haskell-node-1`

### Tip divergence
- Normal during startup (nodes need a few epochs to sync)
- If persistent, check network connectivity between containers
- Verify all nodes use the same genesis files (mounted from the shared volume)

### Vibe-node not syncing
- The vibe-node initially runs in passive mode (sync only)
- Check it can reach the Haskell nodes: the topology file points to the correct hostnames
- Check logs: `docker compose -f docker-compose.devnet.yml logs vibe-node`
