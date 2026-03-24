#!/usr/bin/env python3
"""Analyze and compare sync benchmark results between vibe-node and Haskell node.

Reads JSON metrics files produced by capture-metrics.py and haskell-metrics-loop.sh,
then generates:
  1. A human-readable Markdown comparison table
  2. A machine-readable JSON summary

Usage:
    python scripts/analyze-sync-results.py \\
        --vibe infra/preview-sync/results/vibe-node-metrics.json \\
        --haskell infra/preview-sync/results/haskell-node-metrics.json \\
        --output benchmarks/preview-sync/

    # Or with just one file:
    python scripts/analyze-sync-results.py \\
        --vibe infra/preview-sync/results/vibe-node-metrics.json \\
        --output benchmarks/preview-sync/
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path


def load_metrics(path: Path) -> dict:
    """Load a metrics JSON file."""
    with open(path) as f:
        return json.load(f)


def compute_throughput(samples: list[dict]) -> dict:
    """Compute block throughput statistics from samples.

    Returns dict with keys: mean, median, p50, p95, p99, max
    All values in blocks/second.
    """
    rates: list[float] = []

    for i in range(1, len(samples)):
        prev = samples[i - 1]
        curr = samples[i]

        dt = curr["elapsed_s"] - prev["elapsed_s"]
        if dt <= 0:
            continue

        prev_height = prev.get("block_height") or 0
        curr_height = curr.get("block_height") or 0

        if curr_height > prev_height:
            rate = (curr_height - prev_height) / dt
            rates.append(rate)

    if not rates:
        return {"mean": 0, "median": 0, "p50": 0, "p95": 0, "p99": 0, "max": 0}

    rates_sorted = sorted(rates)
    n = len(rates_sorted)

    def percentile(p: float) -> float:
        idx = int(p / 100 * (n - 1))
        return rates_sorted[min(idx, n - 1)]

    return {
        "mean": round(statistics.mean(rates), 2),
        "median": round(statistics.median(rates), 2),
        "p50": round(percentile(50), 2),
        "p95": round(percentile(95), 2),
        "p99": round(percentile(99), 2),
        "max": round(max(rates), 2),
    }


def compute_memory_stats(samples: list[dict]) -> dict:
    """Compute memory statistics from samples.

    Returns dict with peak_rss_mb, mean_rss_mb, p95_rss_mb.
    """
    rss_values = [s.get("rss_mb", 0) for s in samples if s.get("rss_mb", 0) > 0]

    if not rss_values:
        return {"peak_rss_mb": 0, "mean_rss_mb": 0, "p95_rss_mb": 0}

    rss_sorted = sorted(rss_values)
    n = len(rss_sorted)
    p95_idx = min(int(0.95 * (n - 1)), n - 1)

    return {
        "peak_rss_mb": round(max(rss_values), 1),
        "mean_rss_mb": round(statistics.mean(rss_values), 1),
        "p95_rss_mb": round(rss_sorted[p95_idx], 1),
    }


def analyze_node(data: dict) -> dict:
    """Produce a summary for a single node's metrics."""
    samples = data.get("samples", [])
    if not samples:
        return {"error": "No samples found"}

    throughput = compute_throughput(samples)
    memory = compute_memory_stats(samples)

    # Final block height
    heights = [s.get("block_height") or 0 for s in samples]
    final_height = max(heights) if heights else 0

    # Total elapsed time
    total_elapsed = data.get("total_elapsed_s", 0)

    # Overall throughput
    overall_throughput = round(final_height / total_elapsed, 2) if total_elapsed > 0 else 0

    return {
        "node_type": data.get("node_type", "unknown"),
        "start_time": data.get("start_time", ""),
        "total_elapsed_s": total_elapsed,
        "total_elapsed_human": format_duration(total_elapsed),
        "final_block_height": final_height,
        "overall_throughput_bps": overall_throughput,
        "interval_throughput": throughput,
        "memory": memory,
        "sample_count": len(samples),
    }


def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    h = s // 3600
    m = (s % 3600) // 60
    return f"{h}h {m}m"


def generate_markdown(
    vibe_summary: dict | None,
    haskell_summary: dict | None,
    hardware_info: dict | None,
) -> str:
    """Generate a Markdown comparison report."""
    lines: list[str] = []
    lines.append("# Preview Sync Benchmark Results\n")
    lines.append(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

    # Hardware info
    if hardware_info:
        lines.append("## Hardware\n")
        lines.append(f"| Spec | Value |")
        lines.append(f"|------|-------|")
        lines.append(f"| Hostname | {hardware_info.get('hostname', 'N/A')} |")
        lines.append(f"| OS | {hardware_info.get('os', 'N/A')} |")
        lines.append(f"| CPU | {hardware_info.get('cpu_model', 'N/A')} |")
        lines.append(f"| Cores | {hardware_info.get('cpu_cores', 'N/A')} |")
        lines.append(f"| RAM | {hardware_info.get('total_ram_mb', 'N/A')} MiB |")
        lines.append(f"| Docker | {hardware_info.get('docker_version', 'N/A')} |")
        lines.append("")

    # Comparison table
    lines.append("## Sync Performance Comparison\n")
    lines.append("| Metric | vibe-node | Haskell node | Delta |")
    lines.append("|--------|-----------|--------------|-------|")

    def row(label: str, vibe_val: str, haskell_val: str, delta: str = "") -> str:
        return f"| {label} | {vibe_val} | {haskell_val} | {delta} |"

    v = vibe_summary or {}
    h = haskell_summary or {}

    # Wall-clock time
    v_time = v.get("total_elapsed_human", "N/A")
    h_time = h.get("total_elapsed_human", "N/A")
    time_delta = ""
    if v.get("total_elapsed_s") and h.get("total_elapsed_s"):
        ratio = v["total_elapsed_s"] / h["total_elapsed_s"]
        time_delta = f"{ratio:.2f}x"
    lines.append(row("Wall-clock time", v_time, h_time, time_delta))

    # Final block height
    v_height = str(v.get("final_block_height", "N/A"))
    h_height = str(h.get("final_block_height", "N/A"))
    lines.append(row("Final block height", v_height, h_height))

    # Overall throughput
    v_tp = f"{v.get('overall_throughput_bps', 'N/A')} blocks/s" if v.get("overall_throughput_bps") else "N/A"
    h_tp = f"{h.get('overall_throughput_bps', 'N/A')} blocks/s" if h.get("overall_throughput_bps") else "N/A"
    lines.append(row("Overall throughput", v_tp, h_tp))

    # Interval throughput P50
    v_p50 = f"{v.get('interval_throughput', {}).get('p50', 'N/A')} blocks/s" if v.get("interval_throughput") else "N/A"
    h_p50 = f"{h.get('interval_throughput', {}).get('p50', 'N/A')} blocks/s" if h.get("interval_throughput") else "N/A"
    lines.append(row("Throughput (P50)", v_p50, h_p50))

    # Interval throughput P95
    v_p95t = f"{v.get('interval_throughput', {}).get('p95', 'N/A')} blocks/s" if v.get("interval_throughput") else "N/A"
    h_p95t = f"{h.get('interval_throughput', {}).get('p95', 'N/A')} blocks/s" if h.get("interval_throughput") else "N/A"
    lines.append(row("Throughput (P95)", v_p95t, h_p95t))

    # Interval throughput P99
    v_p99t = f"{v.get('interval_throughput', {}).get('p99', 'N/A')} blocks/s" if v.get("interval_throughput") else "N/A"
    h_p99t = f"{h.get('interval_throughput', {}).get('p99', 'N/A')} blocks/s" if h.get("interval_throughput") else "N/A"
    lines.append(row("Throughput (P99)", v_p99t, h_p99t))

    # Peak RSS
    v_peak = f"{v.get('memory', {}).get('peak_rss_mb', 'N/A')} MiB" if v.get("memory") else "N/A"
    h_peak = f"{h.get('memory', {}).get('peak_rss_mb', 'N/A')} MiB" if h.get("memory") else "N/A"
    mem_delta = ""
    if v.get("memory", {}).get("peak_rss_mb") and h.get("memory", {}).get("peak_rss_mb"):
        ratio = v["memory"]["peak_rss_mb"] / h["memory"]["peak_rss_mb"]
        mem_delta = f"{ratio:.2f}x"
    lines.append(row("Peak RSS", v_peak, h_peak, mem_delta))

    # Mean RSS
    v_mean = f"{v.get('memory', {}).get('mean_rss_mb', 'N/A')} MiB" if v.get("memory") else "N/A"
    h_mean = f"{h.get('memory', {}).get('mean_rss_mb', 'N/A')} MiB" if h.get("memory") else "N/A"
    lines.append(row("Mean RSS", v_mean, h_mean))

    # P95 RSS
    v_p95m = f"{v.get('memory', {}).get('p95_rss_mb', 'N/A')} MiB" if v.get("memory") else "N/A"
    h_p95m = f"{h.get('memory', {}).get('p95_rss_mb', 'N/A')} MiB" if h.get("memory") else "N/A"
    lines.append(row("P95 RSS", v_p95m, h_p95m))

    # Sample count
    v_samples = str(v.get("sample_count", "N/A"))
    h_samples = str(h.get("sample_count", "N/A"))
    lines.append(row("Samples collected", v_samples, h_samples))

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze and compare sync benchmark results"
    )
    parser.add_argument(
        "--vibe",
        type=Path,
        help="Path to vibe-node metrics JSON",
    )
    parser.add_argument(
        "--haskell",
        type=Path,
        help="Path to Haskell node metrics JSON",
    )
    parser.add_argument(
        "--hardware",
        type=Path,
        help="Path to hardware-info.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/preview-sync"),
        help="Output directory for results (default: benchmarks/preview-sync/)",
    )
    args = parser.parse_args()

    if not args.vibe and not args.haskell:
        print("Error: Provide at least one of --vibe or --haskell", file=sys.stderr)
        sys.exit(1)

    # Load data
    vibe_data = load_metrics(args.vibe) if args.vibe else None
    haskell_data = load_metrics(args.haskell) if args.haskell else None
    hardware_info = None
    if args.hardware and args.hardware.exists():
        with open(args.hardware) as f:
            hardware_info = json.load(f)

    # Analyze
    vibe_summary = analyze_node(vibe_data) if vibe_data else None
    haskell_summary = analyze_node(haskell_data) if haskell_data else None

    # Output directory
    args.output.mkdir(parents=True, exist_ok=True)

    # Generate Markdown report
    md = generate_markdown(vibe_summary, haskell_summary, hardware_info)
    md_path = args.output / "comparison-report.md"
    md_path.write_text(md)
    print(f"[analyze] Markdown report: {md_path}")

    # Generate JSON summary
    summary = {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hardware": hardware_info,
        "vibe_node": vibe_summary,
        "haskell_node": haskell_summary,
    }
    json_path = args.output / "comparison-summary.json"
    with open(json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[analyze] JSON summary:    {json_path}")

    # Print to stdout
    print("\n" + md)


if __name__ == "__main__":
    main()
