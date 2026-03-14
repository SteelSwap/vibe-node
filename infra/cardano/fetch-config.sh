#!/bin/sh
set -e

NETWORK="${CARDANO_NETWORK:-preprod}"
CONFIG_DIR="/shared"

# Skip if config already exists
if [ -f "$CONFIG_DIR/config.json" ]; then
    echo "=== Cardano config already present, skipping fetch ==="
    exit 0
fi

BASE_URL="https://book.play.dev.cardano.org/environments/${NETWORK}"

echo "=== Fetching Cardano $NETWORK configuration ==="

for FILE in config.json topology.json byron-genesis.json shelley-genesis.json alonzo-genesis.json conway-genesis.json; do
    echo "Downloading $FILE..."
    wget -q -O "$CONFIG_DIR/$FILE" "$BASE_URL/$FILE"
done

echo "=== Configuration files ready ==="
ls -la "$CONFIG_DIR/"
