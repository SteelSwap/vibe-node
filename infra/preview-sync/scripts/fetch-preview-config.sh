#!/usr/bin/env bash
# fetch-preview-config.sh — Download official Cardano preview network config files
#
# Downloads the configuration files needed by the Haskell cardano-node
# to connect to the preview testnet.
#
# Usage:
#   ./scripts/fetch-preview-config.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/config/preview"

BASE_URL="https://book.play.dev.cardano.org/environments/preview"

FILES=(
    "config.json"
    "topology.json"
    "byron-genesis.json"
    "shelley-genesis.json"
    "alonzo-genesis.json"
    "conway-genesis.json"
)

echo "[fetch] Downloading preview network configuration files..."
echo "[fetch] Target: $CONFIG_DIR"

mkdir -p "$CONFIG_DIR"

for file in "${FILES[@]}"; do
    echo "[fetch] Downloading $file..."
    curl -sL "${BASE_URL}/${file}" -o "${CONFIG_DIR}/${file}"
done

echo "[fetch] Done. Files:"
ls -la "$CONFIG_DIR"
echo ""
echo "[fetch] Preview config ready at: $CONFIG_DIR"
