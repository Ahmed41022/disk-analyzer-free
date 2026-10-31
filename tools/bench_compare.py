"""Compare Google Benchmark medians; CLI wall-time/RSS comparison starts in M2."""

import argparse
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median


@dataclass(frozen=True)
class Comparison:
    """Median benchmark durations in milliseconds and their percentage change."""

    name: str
    base_ms: float
    head_ms: float | None
    change_pct: float | None
    regression: bool


def benchmark_medians(path: Path) -> dict[str, float]:
    """Read repeated iteration samples, falling back to explicit median aggregates."""
    document = json.loads(path.read_text(encoding="utf-8"))
    samples: dict[str, list[float]] = defaultdict(list)
    aggregates: dict[str, float] = {}
    factors = {"ns": 0.000001, "us": 0.001, "ms": 1, "s": 1000}
    for row in document["benchmarks"]:
        if row.get("error_occurred"):
            raise ValueError(f"benchmark failed: {row['name']}")
        if row.get("run_type") == "aggregate" and row.get("aggregate_name") != "median":
            continue
        value = float(row["real_time"]) * factors[row["time_unit"]]
        if not math.isfinite(value) or value <= 0:
            raise ValueError("benchmark durations must be finite and positive")
        name = row.get("run_name", row["name"])
        if row.get("run_type") == "aggregate":
            aggregates[name.removesuffix("_median")] = value
        else:
            samples[name].append(value)
    result = {name: median(values) for name, values in samples.items()}
    for name, value in aggregates.items():
        result.setdefault(name, value)
    if not result:
        raise ValueError("benchmark JSON has no timing samples")
    return result


def compare(
    base: dict[str, float], head: dict[str, float], threshold_pct: float
) -> list[Comparison]:
    """Fail missing head benchmarks and changes strictly above the allowed threshold."""
    result = []
    for name, before in sorted(base.items()):
        after = head.get(name)
        change = None if after is None else (after / before - 1) * 100
        result.append(
            Comparison(name, before, after, change, change is None or change > threshold_pct)
        )
    return result


def render_summary(rows: list[Comparison]) -> str:
    """Return a Markdown comparison with explicit missing-benchmark failures."""
    lines = [
        "| Benchmark | Base median (ms) | Head median (ms) | Change | Result |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        name = " ".join(row.name.replace("|", "\\|").split())
        after = "missing" if row.head_ms is None else f"{row.head_ms:.6f}"
        change = "—" if row.change_pct is None else f"{row.change_pct:+.2f}%"
        status = "FAIL" if row.regression else "PASS"
        lines.append(f"| {name} | {row.base_ms:.6f} | {after} | {change} | {status} |")
    lines.extend(
        [
            "",
            "M1 compares supplied Google Benchmark JSON. CLI wall-time and peak-RSS "
            "comparison is pending T2.2; no CLI binaries are executed.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_new(path: Path, text: str) -> None:
    path = Path(os.path.abspath(path))  # noqa: PTH100 -- do not resolve link ancestors
    for component in (path, *path.parents):
        if component.is_symlink() or component.is_junction():
            raise ValueError(f"summary must not traverse a link: {component}")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def main(argv: list[str] | None = None) -> int:
    """Compare supplied benchmark files, write a new summary, and return 1 on regression."""
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("base", "head", "fixture"):
        parser.add_argument(f"--{option}", type=Path, help="reserved for CLI comparison in T2.2")
    parser.add_argument(
        "--runs", type=int, default=5, help="CLI repetition count reserved for T2.2"
    )
    parser.add_argument("--threshold-pct", type=float, default=15)
    parser.add_argument("--rss-threshold-pct", type=float, default=10)
    parser.add_argument("--gbench-base", type=Path, required=True)
    parser.add_argument("--gbench-head", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.runs < 1 or any(
        not math.isfinite(v) or v < 0 for v in (args.threshold_pct, args.rss_threshold_pct)
    ):
        parser.error("runs must be positive and thresholds must be finite and non-negative")
    try:
        rows = compare(
            benchmark_medians(args.gbench_base),
            benchmark_medians(args.gbench_head),
            args.threshold_pct,
        )
        summary = render_summary(rows)
        _write_new(args.summary, summary)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"{error}\n")
    print(summary, end="")
    return int(any(row.regression for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
