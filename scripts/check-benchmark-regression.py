#!/usr/bin/env python3
"""Compare new benchmark results against stored baselines.

Detects performance regressions by comparing a new benchmark JSON file
against the baseline. Reports any test whose mean time exceeds the
baseline mean by more than a configurable threshold (default: 20%).

Usage:
    # Run benchmarks and save new results:
    uv run pytest tests/benchmark/ -o "addopts=" -p benchmark \\
        --benchmark-only --benchmark-json=/tmp/bench-new.json

    # Compare against baselines:
    python scripts/check-benchmark-regression.py /tmp/bench-new.json

    # Custom threshold (e.g., 10% regression limit):
    python scripts/check-benchmark-regression.py /tmp/bench-new.json --threshold 0.10

    # Custom baseline file:
    python scripts/check-benchmark-regression.py /tmp/bench-new.json \\
        --baseline benchmarks/baselines.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_benchmarks(path: Path) -> dict[str, dict]:
    """Load pytest-benchmark JSON and index by test name.

    Returns a dict mapping test name -> benchmark stats dict.
    """
    with open(path) as f:
        data = json.load(f)

    results = {}
    for bench in data.get("benchmarks", []):
        name = bench.get("name", bench.get("fullname", "unknown"))
        results[name] = bench.get("stats", {})
    return results


def compare(
    baseline: dict[str, dict],
    current: dict[str, dict],
    threshold: float,
) -> list[dict]:
    """Compare current results against baseline.

    Returns a list of regression dicts with test name, baseline mean,
    current mean, and percentage change.
    """
    regressions = []
    improvements = []
    unchanged = []

    for name, current_stats in sorted(current.items()):
        if name not in baseline:
            continue

        baseline_mean = baseline[name].get("mean", 0)
        current_mean = current_stats.get("mean", 0)

        if baseline_mean <= 0:
            continue

        pct_change = (current_mean - baseline_mean) / baseline_mean

        entry = {
            "name": name,
            "baseline_mean_us": baseline_mean * 1e6,
            "current_mean_us": current_mean * 1e6,
            "pct_change": pct_change,
        }

        if pct_change > threshold:
            regressions.append(entry)
        elif pct_change < -threshold:
            improvements.append(entry)
        else:
            unchanged.append(entry)

    return regressions, improvements, unchanged


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check for benchmark regressions against baselines."
    )
    parser.add_argument(
        "new_results",
        type=Path,
        help="Path to the new benchmark JSON file.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("benchmarks/baselines.json"),
        help="Path to the baseline JSON file (default: benchmarks/baselines.json).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.20,
        help="Regression threshold as a fraction (default: 0.20 = 20%%).",
    )
    args = parser.parse_args()

    if not args.baseline.exists():
        print(f"ERROR: Baseline file not found: {args.baseline}", file=sys.stderr)
        print("Run benchmarks first to create baselines:", file=sys.stderr)
        print(
            '  uv run pytest tests/benchmark/ -o "addopts=" -p benchmark '
            "--benchmark-only --benchmark-json=benchmarks/baselines.json",
            file=sys.stderr,
        )
        return 1

    if not args.new_results.exists():
        print(f"ERROR: New results file not found: {args.new_results}", file=sys.stderr)
        return 1

    baseline = load_benchmarks(args.baseline)
    current = load_benchmarks(args.new_results)

    if not baseline:
        print("ERROR: No benchmarks found in baseline file.", file=sys.stderr)
        return 1

    if not current:
        print("ERROR: No benchmarks found in new results file.", file=sys.stderr)
        return 1

    regressions, improvements, unchanged = compare(baseline, current, args.threshold)

    # Print report
    print(f"\n{'='*72}")
    print(f"  Benchmark Regression Report")
    print(f"  Threshold: {args.threshold:.0%}")
    print(f"  Baseline:  {args.baseline}")
    print(f"  Current:   {args.new_results}")
    print(f"{'='*72}\n")

    # Summary counts
    matched = len(regressions) + len(improvements) + len(unchanged)
    new_tests = len(current) - matched
    missing_tests = len(baseline) - matched

    if regressions:
        print(f"  REGRESSIONS ({len(regressions)}):")
        print(f"  {'Test':<50} {'Baseline':>10} {'Current':>10} {'Change':>8}")
        print(f"  {'-'*50} {'-'*10} {'-'*10} {'-'*8}")
        for r in sorted(regressions, key=lambda x: -x["pct_change"]):
            print(
                f"  {r['name']:<50} "
                f"{r['baseline_mean_us']:>9.1f}us "
                f"{r['current_mean_us']:>9.1f}us "
                f"{r['pct_change']:>+7.1%}"
            )
        print()

    if improvements:
        print(f"  IMPROVEMENTS ({len(improvements)}):")
        print(f"  {'Test':<50} {'Baseline':>10} {'Current':>10} {'Change':>8}")
        print(f"  {'-'*50} {'-'*10} {'-'*10} {'-'*8}")
        for r in sorted(improvements, key=lambda x: x["pct_change"]):
            print(
                f"  {r['name']:<50} "
                f"{r['baseline_mean_us']:>9.1f}us "
                f"{r['current_mean_us']:>9.1f}us "
                f"{r['pct_change']:>+7.1%}"
            )
        print()

    print(f"  SUMMARY:")
    print(f"    Matched tests:  {matched}")
    print(f"    Regressions:    {len(regressions)}")
    print(f"    Improvements:   {len(improvements)}")
    print(f"    Unchanged:      {len(unchanged)}")
    if new_tests > 0:
        print(f"    New tests:      {new_tests} (not in baseline)")
    if missing_tests > 0:
        print(f"    Missing tests:  {missing_tests} (in baseline, not in current)")
    print()

    if regressions:
        print(f"  RESULT: FAIL — {len(regressions)} regression(s) detected.\n")
        return 1
    else:
        print(f"  RESULT: PASS — no regressions detected.\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())
