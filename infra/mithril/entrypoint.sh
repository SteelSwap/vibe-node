#!/bin/sh
set -e

DOWNLOAD_DIR="/data/db/db"

# Skip download if data already exists
if [ -d "$DOWNLOAD_DIR" ] && [ "$(ls -A "$DOWNLOAD_DIR" 2>/dev/null)" ]; then
    echo "=== Mithril: Snapshot already present ==="
    echo "Directory $DOWNLOAD_DIR is not empty, skipping download."
    echo "To force re-download, remove the cardano-node-data volume:"
    echo "  docker volume rm vibe-node_cardano-node-data"
    exit 0
fi

echo "=== Mithril: Downloading snapshot ==="
exec /app/bin/mithril-client cardano-db download \
    --download-dir /data/db \
    --include-ancillary \
    "${SNAPSHOT_DIGEST:-latest}"
