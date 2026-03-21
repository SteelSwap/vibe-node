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
#   1. Generate 3 genesis key pairs (for genDelegs)
#   2. Generate 3 sets of cold keys, KES keys, VRF keys, and opcerts
#   3. Generate stake address keys and payment keys for each pool
#   4. Convert addresses to hex (required by cardano-node 10.x)
#   5. Update shelley-genesis.json with genDelegs, staking config, and hex addresses

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVNET_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
KEYS_DIR="$DEVNET_DIR/keys"
GENESIS_DIR="$DEVNET_DIR/genesis"

# Number of pools / genesis delegates
NUM_POOLS=3
# Lovelace per pool (1M tADA = 1,000,000,000,000 lovelace)
POOL_PLEDGE=1000000000000
# KES period
KES_PERIOD=0

# ─── Detect cardano-cli ──────────────────────────────────────────

if command -v cardano-cli &>/dev/null; then
    CLI="cardano-cli"
    CLI_KEYS_DIR="$KEYS_DIR"
    CLI_GENESIS_DIR="$GENESIS_DIR"
elif command -v docker &>/dev/null; then
    echo "cardano-cli not found, using Docker..."
    CLI="docker run --rm --platform linux/amd64 -v $KEYS_DIR:/keys -v $GENESIS_DIR:/genesis -w /keys --entrypoint cardano-cli ghcr.io/intersectmbo/cardano-node:10.4.1"
    CLI_KEYS_DIR="/keys"
    CLI_GENESIS_DIR="/genesis"
else
    echo "ERROR: Neither cardano-cli nor docker found on PATH"
    exit 1
fi

echo "=== Generating devnet keys ==="
echo "Keys directory: $KEYS_DIR"
echo "Using CLI: $CLI"

# ─── Helper: extract key hash from vkey file ──────────────────────
# Reads the cborHex from a verification key JSON file, strips the
# CBOR wrapper (first 4 bytes = 8 hex chars), and blake2b-224 hashes it.
# This is equivalent to what cardano-cli does internally.
extract_key_hash() {
    local vkey_file="$1"
    # The cborHex in vkey files is CBOR-wrapped: 5820<32-byte-key>
    # We need the blake2b-224 (28 bytes = 56 hex chars) of the raw key bytes
    local cbor_hex
    cbor_hex=$(python3 -c "
import json, hashlib, sys
with open('$vkey_file') as f:
    data = json.load(f)
cbor_hex = data['cborHex']
# Strip CBOR tag: first 4 hex chars (2 bytes) are the CBOR wrapper (5820)
raw_key = bytes.fromhex(cbor_hex[4:])
h = hashlib.blake2b(raw_key, digest_size=28)
print(h.hexdigest())
")
    echo "$cbor_hex"
}

# ─── Clean and create directories ────────────────────────────────

rm -rf "$KEYS_DIR"
for i in $(seq 1 $NUM_POOLS); do
    mkdir -p "$KEYS_DIR/pool${i}"
    mkdir -p "$KEYS_DIR/genesis${i}"
done
mkdir -p "$KEYS_DIR/utxo"

# ─── Generate UTxO keys (for initial funds) ─────────────────────

echo ""
echo "--- Generating UTxO keys ---"
$CLI latest address key-gen \
    --verification-key-file "$CLI_KEYS_DIR/utxo/payment.vkey" \
    --signing-key-file "$CLI_KEYS_DIR/utxo/payment.skey"

$CLI latest stake-address key-gen \
    --verification-key-file "$CLI_KEYS_DIR/utxo/stake.vkey" \
    --signing-key-file "$CLI_KEYS_DIR/utxo/stake.skey"

# ─── Generate Genesis Keys ──────────────────────────────────────
# Genesis keys are the identity keys for genesis delegates.
# Each genesis key delegates block production authority to a pool's cold key.
# genDelegs: { genesis_key_hash: { delegate: cold_key_hash, vrf: vrf_key_hash } }

echo ""
echo "--- Generating genesis keys ---"

GENESIS_VKEY_HASHES=()

for i in $(seq 1 $NUM_POOLS); do
    GEN_DIR="$CLI_KEYS_DIR/genesis${i}"
    echo ""
    echo "--- Genesis key ${i} ---"

    # Genesis key pair
    $CLI latest genesis key-gen-genesis \
        --verification-key-file "$GEN_DIR/genesis.vkey" \
        --signing-key-file "$GEN_DIR/genesis.skey"

    # Extract genesis verification key hash
    GENESIS_HASH=$(extract_key_hash "$KEYS_DIR/genesis${i}/genesis.vkey")
    GENESIS_VKEY_HASHES+=("$GENESIS_HASH")
    echo "  Genesis key hash: $GENESIS_HASH"
done

# ─── Per-pool key generation ─────────────────────────────────────

POOL_IDS=()
POOL_COLD_HASHES=()
POOL_VRF_HASHES=()
STAKE_VKEY_HASHES=()

for i in $(seq 1 $NUM_POOLS); do
    POOL_DIR="$CLI_KEYS_DIR/pool${i}"
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

    # Get pool ID (hex) — this is the cold key hash
    POOL_ID=$($CLI latest stake-pool id \
        --cold-verification-key-file "$POOL_DIR/cold.vkey" \
        --output-format hex)
    POOL_IDS+=("$POOL_ID")
    POOL_COLD_HASHES+=("$POOL_ID")
    echo "  Pool ID (cold key hash): $POOL_ID"

    # Get VRF key hash
    VRF_HASH=$(extract_key_hash "$KEYS_DIR/pool${i}/vrf.vkey")
    POOL_VRF_HASHES+=("$VRF_HASH")
    echo "  VRF key hash: $VRF_HASH"

    # Get stake vkey hash
    STAKE_HASH=$($CLI latest stake-address key-hash \
        --stake-verification-key-file "$POOL_DIR/stake.vkey")
    STAKE_VKEY_HASHES+=("$STAKE_HASH")
    echo "  Stake hash: $STAKE_HASH"
done

# ─── Build genDelegs ─────────────────────────────────────────────
# Maps genesis key hashes to the pool's cold key hash and VRF key hash.
# This delegates block production authority from the genesis keys to the pools.

echo ""
echo "--- Building genDelegs ---"

GENDELEGS_JSON="{}"
for i in $(seq 1 $NUM_POOLS); do
    idx=$((i - 1))
    GENDELEGS_JSON=$(echo "$GENDELEGS_JSON" | jq \
        --arg gk "${GENESIS_VKEY_HASHES[$idx]}" \
        --arg dk "${POOL_COLD_HASHES[$idx]}" \
        --arg vrf "${POOL_VRF_HASHES[$idx]}" \
        '. + { ($gk): { "delegate": $dk, "vrf": $vrf } }')
    echo "  Genesis ${i}: ${GENESIS_VKEY_HASHES[$idx]} -> delegate=${POOL_COLD_HASHES[$idx]}"
done

# ─── Build genesis staking configuration ─────────────────────────

echo ""
echo "--- Building genesis staking configuration ---"

POOLS_JSON="{}"
STAKE_JSON="{}"

for i in $(seq 1 $NUM_POOLS); do
    idx=$((i - 1))
    POOL_ID="${POOL_IDS[$idx]}"
    STAKE_HASH="${STAKE_VKEY_HASHES[$idx]}"
    VRF_HASH="${POOL_VRF_HASHES[$idx]}"

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

# ─── Build initial funds (hex addresses) ──────────────────────────
# cardano-node 10.x requires hex-encoded addresses in shelley-genesis.json,
# NOT bech32 (addr_test1...). We build the bech32 address then convert to hex.

echo ""
echo "--- Building initial fund addresses (hex) ---"

FUNDS_JSON="{}"
for i in $(seq 1 $NUM_POOLS); do
    POOL_DIR="$CLI_KEYS_DIR/pool${i}"

    # Build bech32 address
    ADDR_BECH32=$($CLI latest address build \
        --payment-verification-key-file "$POOL_DIR/payment.vkey" \
        --stake-verification-key-file "$POOL_DIR/stake.vkey" \
        --testnet-magic 42)

    # Convert bech32 to hex.
    # Method 1: cardano-cli address info (preferred)
    # Method 2: python bech32 decode (fallback)
    ADDR_HEX=""
    if ADDR_INFO=$($CLI latest address info --address "$ADDR_BECH32" 2>/dev/null); then
        ADDR_HEX=$(echo "$ADDR_INFO" | jq -r '.base16 // empty')
    fi

    # Fallback: decode bech32 manually via python
    if [ -z "$ADDR_HEX" ]; then
        ADDR_HEX=$(python3 -c "
import sys

CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'

def bech32_decode(bech):
    pos = bech.rfind('1')
    hrp = bech[:pos]
    data_part = bech[pos+1:]
    data = [CHARSET.find(c) for c in data_part]
    # Remove checksum (last 6 chars)
    data = data[:-6]
    # Convert from 5-bit to 8-bit
    acc = 0
    bits = 0
    result = []
    for d in data:
        acc = (acc << 5) | d
        bits += 5
        while bits >= 8:
            bits -= 8
            result.append((acc >> bits) & 0xff)
    return bytes(result)

addr_bytes = bech32_decode('$ADDR_BECH32')
print(addr_bytes.hex())
")
    fi

    FUNDS_JSON=$(echo "$FUNDS_JSON" | jq \
        --arg addr "$ADDR_HEX" \
        --argjson amount "$POOL_PLEDGE" \
        '. + { ($addr): $amount }')

    echo "  Pool ${i} bech32: $ADDR_BECH32"
    echo "  Pool ${i} hex:    $ADDR_HEX"
done

# ─── Patch shelley-genesis.json ──────────────────────────────────

echo ""
echo "--- Patching shelley-genesis.json ---"

jq \
    --argjson gendelegs "$GENDELEGS_JSON" \
    --argjson pools "$POOLS_JSON" \
    --argjson stake "$STAKE_JSON" \
    --argjson funds "$FUNDS_JSON" \
    '.genDelegs = $gendelegs | .staking.pools = $pools | .staking.stake = $stake | .initialFunds = $funds' \
    "$GENESIS_DIR/shelley-genesis.json" > "$GENESIS_DIR/shelley-genesis.json.tmp"

mv "$GENESIS_DIR/shelley-genesis.json.tmp" "$GENESIS_DIR/shelley-genesis.json"

echo "  genDelegs: $(echo "$GENDELEGS_JSON" | jq 'length') entries"
echo "  pools: $(echo "$POOLS_JSON" | jq 'length') entries"
echo "  initialFunds: $(echo "$FUNDS_JSON" | jq 'length') entries (hex format)"

# ─── Validate output ─────────────────────────────────────────────

echo ""
echo "--- Validating shelley-genesis.json ---"

# Check no bech32 addresses leaked through
if grep -q "addr_test1" "$GENESIS_DIR/shelley-genesis.json"; then
    echo "ERROR: Found bech32 address in shelley-genesis.json! Must be hex."
    exit 1
fi

# Check genDelegs is populated
GENDELEGS_COUNT=$(jq '.genDelegs | length' "$GENESIS_DIR/shelley-genesis.json")
if [ "$GENDELEGS_COUNT" -ne "$NUM_POOLS" ]; then
    echo "ERROR: Expected $NUM_POOLS genDelegs entries, found $GENDELEGS_COUNT"
    exit 1
fi

# Check initialFunds is populated
FUNDS_COUNT=$(jq '.initialFunds | length' "$GENESIS_DIR/shelley-genesis.json")
if [ "$FUNDS_COUNT" -ne "$NUM_POOLS" ]; then
    echo "ERROR: Expected $NUM_POOLS initialFunds entries, found $FUNDS_COUNT"
    exit 1
fi

echo "  All validations passed"

# ─── Summary ─────────────────────────────────────────────────────

echo ""
echo "=== Key generation complete ==="
echo ""
echo "Genesis delegates:"
for i in $(seq 1 $NUM_POOLS); do
    echo "  Delegate ${i}: genesis=${GENESIS_VKEY_HASHES[$((i-1))]}"
    echo "              -> pool=${POOL_COLD_HASHES[$((i-1))]}"
done
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
