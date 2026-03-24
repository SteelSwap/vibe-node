#!/usr/bin/env python3
"""Metrics capture for vibe-node sync benchmarks.

Periodically samples:
- Wall-clock time (seconds since start)
- Peak and current RSS (from /proc/PID/status or psutil)
- Current block height (from node's data directory or chain tip query)

Writes results to a JSON file that grows incrementally.

Environment variables:
    METRICS_TARGET      Process name substring to monitor (default: vibe.cardano.node)
    METRICS_INTERVAL    Sampling interval in seconds (default: 30)
    METRICS_OUTPUT      Output JSON file path (default: ./metrics.json)
    METRICS_NODE_TYPE   Label for the node type (default: vibe-node)
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TARGET_PROCESS = os.environ.get("METRICS_TARGET", "vibe.cardano.node")
INTERVAL = int(os.environ.get("METRICS_INTERVAL", "30"))
OUTPUT_PATH = Path(os.environ.get("METRICS_OUTPUT", "./metrics.json"))
NODE_TYPE = os.environ.get("METRICS_NODE_TYPE", "vibe-node")

# ---------------------------------------------------------------------------
# Process discovery
# ---------------------------------------------------------------------------

def find_target_pid() -> int | None:
    """Find the PID of the target process by scanning /proc."""
    proc = Path("/proc")
    if not proc.exists():
        # Fall back to psutil on non-Linux (macOS dev)
        return _find_pid_psutil()

    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_text()
            if TARGET_PROCESS in cmdline and str(os.getpid()) != entry.name:
                return int(entry.name)
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue
    return None


def _find_pid_psutil() -> int | None:
    """Fallback: find target PID via psutil."""
    try:
        import psutil
    except ImportError:
        return None
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = " ".join(proc.info["cmdline"] or [])
            if TARGET_PROCESS in cmdline and proc.pid != os.getpid():
                return proc.pid
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


# ---------------------------------------------------------------------------
# Memory reading
# ---------------------------------------------------------------------------

def read_memory_kb(pid: int) -> dict[str, int]:
    """Read VmRSS and VmPeak from /proc/PID/status (Linux).

    Returns dict with keys: rss_kb, peak_kb. Values are 0 if unavailable.
    """
    result = {"rss_kb": 0, "peak_kb": 0}
    status_path = Path(f"/proc/{pid}/status")

    if status_path.exists():
        try:
            text = status_path.read_text()
            for line in text.splitlines():
                if line.startswith("VmRSS:"):
                    result["rss_kb"] = int(line.split()[1])
                elif line.startswith("VmPeak:"):
                    result["peak_kb"] = int(line.split()[1])
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            pass
    else:
        # Fallback: psutil
        try:
            import psutil
            proc = psutil.Process(pid)
            mem = proc.memory_info()
            result["rss_kb"] = mem.rss // 1024
            # psutil doesn't track peak on all platforms
            result["peak_kb"] = getattr(mem, "peak_wset", mem.rss) // 1024
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Block height reading
# ---------------------------------------------------------------------------

def read_block_height_from_log() -> int | None:
    """Try to read current block height from node stdout/logs.

    This is a best-effort approach — the node may log block heights
    in various formats. Returns None if not determinable.
    """
    # TODO: Implement chain-tip query via local N2C protocol or REST API
    # For now, return None — the benchmark runner can fill this in
    # from external monitoring.
    return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"[metrics] Starting capture for '{TARGET_PROCESS}'")
    print(f"[metrics] Interval: {INTERVAL}s, Output: {OUTPUT_PATH}")
    print(f"[metrics] Node type: {NODE_TYPE}")

    # Ensure output directory exists
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load existing data if resuming
    samples: list[dict] = []
    if OUTPUT_PATH.exists():
        try:
            with open(OUTPUT_PATH) as f:
                data = json.load(f)
                samples = data.get("samples", [])
            print(f"[metrics] Resuming with {len(samples)} existing samples")
        except (json.JSONDecodeError, KeyError):
            pass

    start_time = time.monotonic()
    start_wall = datetime.now(timezone.utc).isoformat()
    peak_rss_kb = 0
    running = True

    def handle_signal(signum: int, frame: object) -> None:
        nonlocal running
        print(f"[metrics] Received signal {signum}, flushing and exiting")
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Wait for target process to appear
    pid = None
    while running and pid is None:
        pid = find_target_pid()
        if pid is None:
            print("[metrics] Waiting for target process...")
            time.sleep(5)

    if pid is not None:
        print(f"[metrics] Found target PID: {pid}")

    while running:
        elapsed = time.monotonic() - start_time
        now = datetime.now(timezone.utc).isoformat()

        # Check if process still alive
        if pid is not None:
            try:
                os.kill(pid, 0)  # signal 0 = check existence
            except ProcessLookupError:
                print("[metrics] Target process exited, stopping capture")
                break

        # Read memory
        mem = read_memory_kb(pid) if pid else {"rss_kb": 0, "peak_kb": 0}
        if mem["rss_kb"] > peak_rss_kb:
            peak_rss_kb = mem["rss_kb"]

        # Read block height
        block_height = read_block_height_from_log()

        sample = {
            "timestamp": now,
            "elapsed_s": round(elapsed, 1),
            "rss_kb": mem["rss_kb"],
            "rss_mb": round(mem["rss_kb"] / 1024, 1),
            "peak_rss_kb": peak_rss_kb,
            "peak_rss_mb": round(peak_rss_kb / 1024, 1),
            "block_height": block_height,
        }
        samples.append(sample)

        # Write atomically
        output = {
            "node_type": NODE_TYPE,
            "start_time": start_wall,
            "last_update": now,
            "total_elapsed_s": round(elapsed, 1),
            "peak_rss_mb": round(peak_rss_kb / 1024, 1),
            "sample_count": len(samples),
            "samples": samples,
        }
        tmp_path = OUTPUT_PATH.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(output, f, indent=2)
        tmp_path.rename(OUTPUT_PATH)

        rss_str = f"{mem['rss_kb'] // 1024} MiB"
        height_str = str(block_height) if block_height is not None else "N/A"
        print(
            f"[metrics] t={elapsed:.0f}s | RSS={rss_str} | "
            f"peak={peak_rss_kb // 1024} MiB | block={height_str}"
        )

        time.sleep(INTERVAL)

    # Final write
    if samples:
        output = {
            "node_type": NODE_TYPE,
            "start_time": start_wall,
            "last_update": datetime.now(timezone.utc).isoformat(),
            "total_elapsed_s": round(time.monotonic() - start_time, 1),
            "peak_rss_mb": round(peak_rss_kb / 1024, 1),
            "sample_count": len(samples),
            "samples": samples,
        }
        with open(OUTPUT_PATH, "w") as f:
            json.dump(output, f, indent=2)
        print(f"[metrics] Wrote {len(samples)} samples to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
