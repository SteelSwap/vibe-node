#!/usr/bin/env bash
# haskell-metrics-loop.sh — Capture Haskell cardano-node sync metrics
#
# Runs inside the metrics-capture sidecar container. Periodically queries
# the Haskell node via cardano-cli and reads /proc for memory stats.
#
# Writes incremental JSON to METRICS_OUTPUT.

set -euo pipefail

INTERVAL="${METRICS_INTERVAL:-30}"
OUTPUT="${METRICS_OUTPUT:-/results/haskell-node-metrics.json}"
NODE_TYPE="haskell-node"
SOCKET="${CARDANO_NODE_SOCKET_PATH:-/ipc/node.socket}"

echo "[metrics] Starting Haskell node metrics capture"
echo "[metrics] Interval: ${INTERVAL}s, Output: ${OUTPUT}"
echo "[metrics] Socket: ${SOCKET}"

# Ensure output directory exists
mkdir -p "$(dirname "$OUTPUT")"

# Initialize JSON structure
START_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
START_EPOCH=$(date +%s)

# Find the cardano-node PID (running in the other container via shared PID or via /proc scan)
find_node_pid() {
    # Try to find cardano-node process
    local pid
    pid=$(pgrep -f "cardano-node.*run" 2>/dev/null | head -1 || true)
    if [ -n "$pid" ]; then
        echo "$pid"
        return
    fi
    # Fallback: scan /proc
    for d in /proc/[0-9]*; do
        if [ -f "$d/cmdline" ] && grep -q "cardano-node" "$d/cmdline" 2>/dev/null; then
            basename "$d"
            return
        fi
    done
}

# Read RSS from /proc
read_rss_kb() {
    local pid=$1
    if [ -f "/proc/$pid/status" ]; then
        grep VmRSS "/proc/$pid/status" 2>/dev/null | awk '{print $2}' || echo "0"
    else
        echo "0"
    fi
}

read_peak_kb() {
    local pid=$1
    if [ -f "/proc/$pid/status" ]; then
        grep VmPeak "/proc/$pid/status" 2>/dev/null | awk '{print $2}' || echo "0"
    else
        echo "0"
    fi
}

# Query chain tip via cardano-cli
query_tip() {
    if [ -S "$SOCKET" ]; then
        cardano-cli latest query tip --socket-path "$SOCKET" --testnet-magic 2 2>/dev/null || echo "{}"
    else
        echo "{}"
    fi
}

PEAK_RSS_KB=0
SAMPLE_COUNT=0

# Initialize output file
cat > "$OUTPUT" <<INITEOF
{
  "node_type": "$NODE_TYPE",
  "start_time": "$START_TIME",
  "last_update": "$START_TIME",
  "total_elapsed_s": 0,
  "peak_rss_mb": 0,
  "sample_count": 0,
  "samples": []
}
INITEOF

echo "[metrics] Waiting for cardano-node socket..."
while [ ! -S "$SOCKET" ]; do
    sleep 2
done
echo "[metrics] Socket ready, beginning capture"

while true; do
    NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    NOW_EPOCH=$(date +%s)
    ELAPSED=$(( NOW_EPOCH - START_EPOCH ))

    # Get chain tip
    TIP_JSON=$(query_tip)
    BLOCK_HEIGHT=$(echo "$TIP_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('block',d.get('blockNo',0)))" 2>/dev/null || echo "0")
    SLOT=$(echo "$TIP_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('slot',d.get('slotNo',0)))" 2>/dev/null || echo "0")
    SYNC_PCT=$(echo "$TIP_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('syncProgress','0'))" 2>/dev/null || echo "0")

    # Get memory (best effort — may not have access to node PID from sidecar)
    NODE_PID=$(find_node_pid)
    RSS_KB=0
    VPEAK_KB=0
    if [ -n "$NODE_PID" ]; then
        RSS_KB=$(read_rss_kb "$NODE_PID")
        VPEAK_KB=$(read_peak_kb "$NODE_PID")
    fi

    if [ "$RSS_KB" -gt "$PEAK_RSS_KB" ]; then
        PEAK_RSS_KB=$RSS_KB
    fi

    RSS_MB=$(( RSS_KB / 1024 ))
    PEAK_MB=$(( PEAK_RSS_KB / 1024 ))
    SAMPLE_COUNT=$(( SAMPLE_COUNT + 1 ))

    echo "[metrics] t=${ELAPSED}s | RSS=${RSS_MB} MiB | peak=${PEAK_MB} MiB | block=${BLOCK_HEIGHT} | slot=${SLOT} | sync=${SYNC_PCT}%"

    # Build new sample as JSON
    SAMPLE=$(cat <<SAMPLEEOF
{
    "timestamp": "$NOW",
    "elapsed_s": $ELAPSED,
    "rss_kb": $RSS_KB,
    "rss_mb": $RSS_MB,
    "peak_rss_kb": $PEAK_RSS_KB,
    "peak_rss_mb": $PEAK_MB,
    "block_height": $BLOCK_HEIGHT,
    "slot": $SLOT,
    "sync_progress": "$SYNC_PCT"
  }
SAMPLEEOF
)

    # Rebuild the output file with all samples
    # (Using python3 for safe JSON manipulation)
    python3 -c "
import json, sys
with open('$OUTPUT') as f:
    data = json.load(f)
sample = json.loads('''$SAMPLE''')
data['samples'].append(sample)
data['last_update'] = '$NOW'
data['total_elapsed_s'] = $ELAPSED
data['peak_rss_mb'] = $PEAK_MB
data['sample_count'] = len(data['samples'])
with open('${OUTPUT}.tmp', 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null && mv "${OUTPUT}.tmp" "$OUTPUT"

    sleep "$INTERVAL"
done
