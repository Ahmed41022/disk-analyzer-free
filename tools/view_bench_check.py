"""Enforce T4.1's absolute release-build latency budgets from Google Benchmark JSON."""

import argparse
from pathlib import Path

from tools.bench_compare import benchmark_medians

LIMITS_MS = {"BM_Expand100kChildren": 150.0, "BM_RowsWindow10M": 2.0}


def check(path: Path) -> bool:
    """Print each measured median and fail missing results or unmet strict budgets."""
    measured = benchmark_medians(path)
    passed = True
    for name, limit in LIMITS_MS.items():
        samples = [duration for key, duration in measured.items() if key.split("/")[0] == name]
        valid = bool(samples) and all(duration < limit for duration in samples)
        value = ", ".join(f"{duration:.6f} ms" for duration in samples) or "missing"
        print(f"{name}: {value}; required < {limit:g} ms: {'PASS' if valid else 'FAIL'}")
        passed = passed and valid
    return passed


def main() -> int:
    """Return nonzero for an invalid report or a failed acceptance budget."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        return int(not check(args.report))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
