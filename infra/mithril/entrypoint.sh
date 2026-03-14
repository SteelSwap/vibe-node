#!/bin/sh
set -e

NETWORK="${CARDANO_NETWORK:-preprod}"
SNAPSHOT_DIGEST="${SNAPSHOT_DIGEST:-latest}"

case "$NETWORK" in
  preprod)
    export AGGREGATOR_ENDPOINT="https://aggregator.release-preprod.api.mithril.network/aggregator"
    export GENESIS_VERIFICATION_KEY="5b3132372c37332c3132342c3136312c362c3133372c3133312c3231332c3230372c3131372c3133352c3233322c3133342c3231322c3230362c3233312c3230312c3231302c3231352c3233312c3230372c3131342c3232342c3233342c3232332c3230342c3233312c3231322c3233372c3132332c3233312c3131342c3131342c3233322c3131382c3232312c3132302c3131352c3132342c3232312c31"
    ;;
  mainnet)
    export AGGREGATOR_ENDPOINT="https://aggregator.release-mainnet.api.mithril.network/aggregator"
    export GENESIS_VERIFICATION_KEY="5b3132372c37332c3132342c3136312c362c3133372c3133312c3231332c3230372c3131372c3133352c3233322c3133342c3231322c3230362c3233312c3230312c3231302c3231352c3233312c3230372c3131342c3232342c3233342c3232332c3230342c3233312c3231322c3233372c3132332c3233312c3131342c3131342c3233322c3131382c3231322c3132302c3131352c3134312c3233372c31"
    ;;
  *)
    echo "ERROR: Unsupported network: $NETWORK"
    echo "Supported networks: preprod, mainnet"
    exit 1
    ;;
esac

echo "=== Mithril Snapshot Download ==="
echo "Network:   $NETWORK"
echo "Digest:    $SNAPSHOT_DIGEST"
echo "Endpoint:  $AGGREGATOR_ENDPOINT"
echo ""

# Download the cardano-db snapshot
mithril-client cardano-db download \
  --download-dir /data/db \
  "$SNAPSHOT_DIGEST"

echo ""
echo "=== Snapshot download complete ==="
echo "Data available at /data/db"
