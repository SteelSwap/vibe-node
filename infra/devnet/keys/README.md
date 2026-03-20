# Devnet Keys

This directory holds cryptographic keys for the private devnet. Keys are generated
by `scripts/generate-keys.sh` and are **never committed to git**.

## Structure (after generation)

```
keys/
  pool1/          # Haskell node 1 (block producer)
    cold.vkey     # Pool cold verification key
    cold.skey     # Pool cold signing key
    kes.vkey      # KES verification key
    kes.skey      # KES signing key
    vrf.vkey      # VRF verification key
    vrf.skey      # VRF signing key
    opcert.cert   # Operational certificate
    opcert.counter
    stake.vkey    # Stake verification key
    stake.skey    # Stake signing key
    payment.vkey  # Payment verification key
    payment.skey  # Payment signing key
  pool2/          # Haskell node 2 (block producer)
    ...           # Same structure as pool1
  pool3/          # Vibe node (initially passive)
    ...           # Same structure as pool1
  utxo/           # UTxO keys for initial funds
    payment.vkey
    payment.skey
    stake.vkey
    stake.skey
```

## Generating Keys

```bash
cd infra/devnet
./scripts/generate-keys.sh
```

Requires `cardano-cli` >= 10.x on PATH, or Docker.
