#!/usr/bin/env bash
# generate-keys.sh — Generate all cryptographic keys for the 3-node devnet
#
# This script generates fresh keys every time it runs. Keys are written to
# infra/devnet/keys/ and MUST NOT be committed to git.
#
# Prerequisites:
#   - cardano-cli (>= 10.x) on PATH, OR
#   - Docker with ghcr.io/intersectmbo/cardano-node:10.4.1 available
#
# Usage:
#   cd infra/devnet
#   ./scripts/generate-keys.sh
#
# The script will:
#   1. Generate 3 sets of cold keys, KES keys, VRF keys, and opcerts
#   2. Generate stake address keys for each pool
#   3. Generate pool registration certificates
#   4. Generate delegation certificates
#   5. Update shelley-genesis.json with initial staking configuration

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVNET_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
KEYS_DIR="$DEVNET_DIR/keys"
GENESIS_DIR="$DEVNET_DIR/genesis"

# Number of pools
NUM_POOLS=3
# Lovelace per pool (1M tADA = 1,000,000,000,000 lovelace)
POOL_PLEDGE=1000000000000
# KES period
KES_PERIOD=0

# ─── Detect cardano-cli ──────────────────────────────────────────

if command -v cardano-cli &>/dev/null; then
    CLI="cardano-cli"
elif command -v docker &>/dev/null; then
    echo "cardano-cli not found, using Docker..."
    CLI="docker run --rm -v $KEYS_DIR:/keys -v $GENESIS_DIR:/genesis -w /keys ghcr.io/intersectmbo/cardano-node:10.4.1 cardano-cli"
else
    echo "ERROR: Neither cardano-cli nor docker found on PATH"
    exit 1
fi

echo "=== Generating devnet keys ==="
echo "Keys directory: $KEYS_DIR"
echo "Using CLI: $CLI"

# ─── Clean and create directories ────────────────────────────────

rm -rf "$KEYS_DIR"
for i in $(seq 1 $NUM_POOLS); do
    mkdir -p "$KEYS_DIR/pool${i}"
done
mkdir -p "$KEYS_DIR/utxo"

# ─── Generate UTxO keys (for initial funds) ─────────────────────

echo ""
echo "--- Generating UTxO keys ---"
$CLI latest address key-gen \
    --verification-key-file "$KEYS_DIR/utxo/payment.vkey" \
    --signing-key-file "$KEYS_DIR/utxo/payment.skey"

$CLI latest stake-address key-gen \
    --verification-key-file "$KEYS_DIR/utxo/stake.vkey" \
    --signing-key-file "$KEYS_DIR/utxo/stake.skey"

# ─── Per-pool key generation ─────────────────────────────────────

POOL_IDS=()
POOL_VKEYS=()
STAKE_VKEY_HASHES=()

for i in $(seq 1 $NUM_POOLS); do
    POOL_DIR="$KEYS_DIR/pool${i}"
    echo ""
    echo "--- Pool ${i}: Generating keys ---"

    # Cold keys (pool identity)
    $CLI latest node key-gen \
        --cold-verification-key-file "$POOL_DIR/cold.vkey" \
        --cold-signing-key-file "$POOL_DIR/cold.skey" \
        --operational-certificate-issue-counter-file "$POOL_DIR/opcert.counter"

    # VRF keys (slot leader election)
    $CLI latest node key-gen-VRF \
        --verification-key-file "$POOL_DIR/vrf.vkey" \
        --signing-key-file "$POOL_DIR/vrf.skey"

    # KES keys (hot keys, evolved periodically)
    $CLI latest node key-gen-KES \
        --verification-key-file "$POOL_DIR/kes.vkey" \
        --signing-key-file "$POOL_DIR/kes.skey"

    # Operational certificate
    $CLI latest node issue-op-cert \
        --kes-verification-key-file "$POOL_DIR/kes.vkey" \
        --cold-signing-key-file "$POOL_DIR/cold.skey" \
        --operational-certificate-issue-counter "$POOL_DIR/opcert.counter" \
        --kes-period $KES_PERIOD \
        --out-file "$POOL_DIR/opcert.cert"

    # Stake keys (for delegation)
    $CLI latest stake-address key-gen \
        --verification-key-file "$POOL_DIR/stake.vkey" \
        --signing-key-file "$POOL_DIR/stake.skey"

    # Payment keys (for pool rewards)
    $CLI latest address key-gen \
        --verification-key-file "$POOL_DIR/payment.vkey" \
        --signing-key-file "$POOL_DIR/payment.skey"

    # Get pool ID
    POOL_ID=$($CLI latest stake-pool id \
        --cold-verification-key-file "$POOL_DIR/cold.vkey" \
        --output-format hex)
    POOL_IDS+=("$POOL_ID")
    echo "  Pool ID: $POOL_ID"

    # Get stake vkey hash
    STAKE_HASH=$($CLI latest stake-address key-hash \
        --stake-verification-key-file "$POOL_DIR/stake.vkey")
    STAKE_VKEY_HASHES+=("$STAKE_HASH")
    echo "  Stake hash: $STAKE_HASH"
done

# ─── Build genesis staking configuration ─────────────────────────

echo ""
echo "--- Building genesis staking configuration ---"

# Build pools JSON object: { poolId: { publicKey: vrfVkey, cost: 0, margin: 0, ... } }
POOLS_JSON="{}"
STAKE_JSON="{}"

for i in $(seq 1 $NUM_POOLS); do
    idx=$((i - 1))
    POOL_DIR="$KEYS_DIR/pool${i}"
    POOL_ID="${POOL_IDS[$idx]}"
    STAKE_HASH="${STAKE_VKEY_HASHES[$idx]}"

    # Read VRF verification key hash
    VRF_HASH=$($CLI latest node key-hash-VRF \
        --verification-key-file "$POOL_DIR/vrf.vkey" 2>/dev/null || \
        cat "$POOL_DIR/vrf.vkey" | python3 -c "import json,sys; print(json.load(sys.stdin).get('cborHex','')[:64])")

    # Build pool entry
    POOLS_JSON=$(echo "$POOLS_JSON" | jq \
        --arg pid "$POOL_ID" \
        --arg vrf "$VRF_HASH" \
        --arg reward "$STAKE_HASH" \
        --argjson cost 0 \
        --argjson pledge "$POOL_PLEDGE" \
        --argjson margin 0 \
        '. + { ($pid): { "publicKey": $vrf, "cost": $cost, "margin": $margin, "pledge": $pledge, "metadata": null, "owners": [$reward], "relays": [], "rewardAccount": { "network": "Testnet", "credential": { "keyHash": $reward } } } }')

    # Map stake key to pool
    STAKE_JSON=$(echo "$STAKE_JSON" | jq \
        --arg sh "$STAKE_HASH" \
        --arg pid "$POOL_ID" \
        '. + { ($sh): $pid }')
done

# ─── Build initial funds ─────────────────────────────────────────

echo ""
echo "--- Building initial fund addresses ---"

FUNDS_JSON="{}"
for i in $(seq 1 $NUM_POOLS); do
    POOL_DIR="$KEYS_DIR/pool${i}"

    # Build enterprise address for initial funds
    ADDR=$($CLI latest address build \
        --payment-verification-key-file "$POOL_DIR/payment.vkey" \
        --stake-verification-key-file "$POOL_DIR/stake.vkey" \
        --testnet-magic 42)

    FUNDS_JSON=$(echo "$FUNDS_JSON" | jq \
        --arg addr "$ADDR" \
        --argjson amount "$POOL_PLEDGE" \
        '. + { ($addr): $amount }')

    echo "  Pool ${i} address: $ADDR ($POOL_PLEDGE lovelace)"
done

# ─── Patch shelley-genesis.json ──────────────────────────────────

echo ""
echo "--- Patching shelley-genesis.json with staking config ---"

jq \
    --argjson pools "$POOLS_JSON" \
    --argjson stake "$STAKE_JSON" \
    --argjson funds "$FUNDS_JSON" \
    '.staking.pools = $pools | .staking.stake = $stake | .initialFunds = $funds' \
    "$GENESIS_DIR/shelley-genesis.json" > "$GENESIS_DIR/shelley-genesis.json.tmp"

mv "$GENESIS_DIR/shelley-genesis.json.tmp" "$GENESIS_DIR/shelley-genesis.json"

# ─── Summary ─────────────────────────────────────────────────────

echo ""
echo "=== Key generation complete ==="
echo ""
echo "Pool IDs:"
for i in $(seq 1 $NUM_POOLS); do
    echo "  Pool ${i}: ${POOL_IDS[$((i-1))]}"
done
echo ""
echo "Keys written to: $KEYS_DIR"
echo ""
echo "IMPORTANT: Do NOT commit keys/ to git!"
echo "           The .gitignore already excludes them."
echo ""
echo "Next steps:"
echo "  1. docker compose -f docker-compose.devnet.yml up -d"
echo "  2. python scripts/monitor-tips.py"
