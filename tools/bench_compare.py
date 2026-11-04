"""Compare Google Benchmark medians and executable scan wall-time/RSS."""

import argparse
import json
import math
import os
import subprocess
import tempfile
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


@dataclass(frozen=True)
class CliComparison:
    """Median scan wall time and peak RSS for base/head executables."""

    base_wall_ms: float | None
    head_wall_ms: float
    wall_change_pct: float | None
    base_rss_bytes: int | None
    head_rss_bytes: int
    rss_change_pct: float | None
    regression: bool


MAX_HEAD_RSS_BYTES = 120 * 1024 * 1024


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
            "Google Benchmark results compare supplied JSON files.",
        ]
    )
    return "\n".join(lines) + "\n"


def _run_scan(executable: Path, fixture: Path, stats_path: Path) -> tuple[float, int]:
    """Run one scan and read its machine-readable timing and peak-RSS sample."""
    command = [
        str(executable.absolute()),
        "--progress",
        "never",
        "--format",
        "json",
        "scan",
        "--mode",
        "walk",
        "--stats-json",
        str(stats_path),
        str(fixture),
    ]
    completed = subprocess.run(  # noqa: S603 -- Executable explicitly selected by the caller.
        command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False
    )
    if completed.returncode:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"scan failed ({completed.returncode}): {stderr}")
    try:
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        wall_ms = float(stats["wall_ms"])
        peak_rss_bytes = stats["peak_rss_bytes"]
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
        raise ValueError(f"invalid scan stats at {stats_path}: {error}") from error
    if (
        not math.isfinite(wall_ms)
        or wall_ms <= 0
        or type(peak_rss_bytes) is not int
        or peak_rss_bytes <= 0
    ):
        raise ValueError(
            "scan wall time must be finite and positive; peak RSS must be a positive integer"
        )
    return wall_ms, peak_rss_bytes


def compare_executables(  # noqa: PLR0913 -- Independent inputs and benchmark limits.
    base: Path | None,
    head: Path,
    fixture: Path,
    runs: int,
    *,
    threshold_pct: float,
    rss_threshold_pct: float,
) -> CliComparison:
    """Warm each executable, then interleave runs; base may be absent for first PRs."""
    with tempfile.TemporaryDirectory(prefix="dafree-bench-") as temporary:
        scratch = Path(temporary)
        if base is None:
            _run_scan(head, fixture, scratch / "head-warmup.json")
            head_samples = [
                _run_scan(head, fixture, scratch / f"head-{index}.json") for index in range(runs)
            ]
            base_wall = base_rss = None
        else:
            _run_scan(base, fixture, scratch / "base-warmup.json")
            _run_scan(head, fixture, scratch / "head-warmup.json")
            base_samples: list[tuple[float, int]] = []
            head_samples = []
            for index in range(runs):
                base_samples.append(_run_scan(base, fixture, scratch / f"base-{index}.json"))
                head_samples.append(_run_scan(head, fixture, scratch / f"head-{index}.json"))
            base_wall = median(sample[0] for sample in base_samples)
            base_rss = int(median(sample[1] for sample in base_samples))
    head_wall = median(sample[0] for sample in head_samples)
    head_rss = int(median(sample[1] for sample in head_samples))
    wall_change = None if base_wall is None else (head_wall - base_wall) * 100 / base_wall
    rss_change = None if base_rss is None else (head_rss - base_rss) * 100 / base_rss
    regression = (
        head_rss > MAX_HEAD_RSS_BYTES
        or (wall_change is not None and wall_change > threshold_pct)
        or (rss_change is not None and rss_change > rss_threshold_pct)
    )
    return CliComparison(
        base_wall, head_wall, wall_change, base_rss, head_rss, rss_change, regression
    )


def render_cli_summary(
    result: CliComparison,
    *,
    has_base: bool,
    threshold_pct: float,
    rss_threshold_pct: float,
) -> str:
    """Render executable metrics while making first-PR baseline absence explicit."""
    if not has_base:
        base_wall, wall_change = "no baseline", "—"
        base_rss, rss_change = "no baseline", "—"
    else:
        base_wall = f"{result.base_wall_ms:.3f} ms"
        wall_change = f"{result.wall_change_pct:+.2f}%"
        base_rss = f"{result.base_rss_bytes} bytes"
        rss_change = f"{result.rss_change_pct:+.2f}%"
    wall_failed = result.wall_change_pct is not None and result.wall_change_pct > threshold_pct
    rss_failed = (
        result.rss_change_pct is not None and result.rss_change_pct > rss_threshold_pct
    ) or result.head_rss_bytes > MAX_HEAD_RSS_BYTES
    return (
        "\n".join(
            [
                "",
                "## CLI executable comparison",
                "",
                "| Metric | Base | Head | Change | Limit | Result |",
                "| --- | ---: | ---: | ---: | ---: | --- |",
                f"| Wall time | {base_wall} | {result.head_wall_ms:.3f} ms | {wall_change} | "
                f"+{threshold_pct:g}% | {'FAIL' if wall_failed else 'PASS'} |",
                f"| Peak RSS | {base_rss} | {result.head_rss_bytes} bytes | {rss_change} | "
                f"+{rss_threshold_pct:g}%, ≤ {MAX_HEAD_RSS_BYTES} bytes head | "
                f"{'FAIL' if rss_failed else 'PASS'} |",
                "",
                "No CLI baseline was supplied; only the head absolute RSS ceiling was checked."
                if not has_base
                else "",
            ]
        ).rstrip()
        + "\n"
    )


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
    parser.add_argument("--base", type=Path, help="base CLI executable (optional for first PR)")
    parser.add_argument("--head", type=Path, help="head CLI executable")
    parser.add_argument("--fixture", type=Path, help="generated scan fixture directory")
    parser.add_argument("--runs", type=int, default=5, help="measured CLI repetitions")
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
    if (args.head is None) != (args.fixture is None) or (
        args.base is not None and args.head is None
    ):
        parser.error("--head and --fixture must be supplied together; --base requires --head")
    try:
        rows = compare(
            benchmark_medians(args.gbench_base),
            benchmark_medians(args.gbench_head),
            args.threshold_pct,
        )
        summary = render_summary(rows)
        cli_result = None
        if args.head is not None:
            cli_result = compare_executables(
                args.base,
                args.head,
                args.fixture,
                args.runs,
                threshold_pct=args.threshold_pct,
                rss_threshold_pct=args.rss_threshold_pct,
            )
            summary += render_cli_summary(
                cli_result,
                has_base=args.base is not None,
                threshold_pct=args.threshold_pct,
                rss_threshold_pct=args.rss_threshold_pct,
            )
        _write_new(args.summary, summary)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"{error}\n")
    print(summary, end="")
    return int(
        any(row.regression for row in rows) or (cli_result is not None and cli_result.regression)
    )


if __name__ == "__main__":
    raise SystemExit(main())
