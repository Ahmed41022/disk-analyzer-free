"""Performance tools produce reproducible input and fail measurable regressions."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SMALL_NODES = 1000
REGRESSION = 120
ALLOWED_CHANGE = 114
_BENCH_SPEC = importlib.util.spec_from_file_location(
    "bench_compare_test", ROOT / "tools" / "bench_compare.py"
)
assert _BENCH_SPEC is not None and _BENCH_SPEC.loader is not None
bench_compare = importlib.util.module_from_spec(_BENCH_SPEC)
sys.modules[_BENCH_SPEC.name] = bench_compare
_BENCH_SPEC.loader.exec_module(bench_compare)


def _run(script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- local tools with explicit arguments and test-owned paths
        [sys.executable, str(ROOT / "tools" / script), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def _manifest_listing(out: Path) -> dict[str, int | str]:
    digest = hashlib.sha256()
    files = dirs = total = 0
    for path in sorted(out.rglob("*"), key=lambda value: value.relative_to(out).as_posix()):
        if path.name == "manifest.json":
            continue
        directory = path.is_dir()
        size = 0 if directory else path.stat().st_size
        dirs += int(directory)
        files += int(not directory)
        total += size
        row = [path.relative_to(out).as_posix(), "dir" if directory else "file", size]
        digest.update((json.dumps(row, separators=(",", ":")) + "\n").encode())
    return {"files": files, "dirs": dirs, "total_size": total, "listing_sha256": digest.hexdigest()}


def test_gen_fixtures_deterministic(tmp_path: Path) -> None:
    """Two fresh outputs have identical manifests and independently verified listings."""
    manifests = []
    for name in ("first", "second"):
        out = tmp_path / name
        result = _run("gen_fixtures.py", "--preset", "small", "--out", str(out))
        assert result.returncode == 0, result.stderr
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        listing = _manifest_listing(out)
        for key, value in listing.items():
            assert manifest[key] == value
        assert manifest["files"] + manifest["dirs"] + 1 == SMALL_NODES
        assert manifest["dirs"] + 1 == SMALL_NODES // 10
        manifests.append(manifest)
    assert manifests[0] == manifests[1]


def test_gen_fixtures_refuses_existing_output(tmp_path: Path) -> None:
    """The generator cannot overwrite even an existing empty output directory."""
    marker = tmp_path / "keep"
    marker.write_bytes(b"preserve")
    result = _run("gen_fixtures.py", "--preset", "small", "--out", str(tmp_path))
    assert result.returncode != 0
    assert list(tmp_path.iterdir()) == [marker]
    assert marker.read_bytes() == b"preserve"


def test_gen_fixtures_refuses_link_ancestors(tmp_path: Path) -> None:
    """An output beneath a symlink cannot create files in its target."""
    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    result = _run("gen_fixtures.py", "--preset", "small", "--out", str(alias / "out"))
    assert result.returncode != 0
    assert not list(actual.iterdir())


def _benchmark(path: Path, values: list[int], *, unit: str = "ms", name: str = "scan") -> None:
    path.write_text(
        json.dumps(
            {
                "benchmarks": [
                    {"name": name, "real_time": value, "time_unit": unit} for value in values
                ]
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("head_time,expected", [(REGRESSION, 1), (ALLOWED_CHANGE, 0)])
def test_bench_compare_detects_regression(tmp_path: Path, head_time: int, expected: int) -> None:
    """Medians resist baseline outliers and the command reports a threshold breach."""
    base, head, summary = (tmp_path / name for name in ("base.json", "head.json", "summary.md"))
    _benchmark(base, [100, 100, 100, 100, 1000])
    _benchmark(head, [head_time * 1000] * 5, unit="us")
    result = _run(
        "bench_compare.py",
        "--gbench-base",
        str(base),
        "--gbench-head",
        str(head),
        "--summary",
        str(summary),
    )
    assert result.returncode == expected, result.stderr
    report = summary.read_text(encoding="utf-8")
    assert ("FAIL" if expected else "PASS") in report
    assert "100.000000" in report
    assert "Google Benchmark results compare supplied JSON files" in report


def test_bench_compare_missing_head_fails(tmp_path: Path) -> None:
    """A removed benchmark cannot silently disappear from regression coverage."""
    base, head, summary = (tmp_path / name for name in ("base.json", "head.json", "summary.md"))
    _benchmark(base, [100])
    _benchmark(head, [100], name="different")
    result = _run(
        "bench_compare.py",
        "--gbench-base",
        str(base),
        "--gbench-head",
        str(head),
        "--summary",
        str(summary),
    )
    assert result.returncode == 1
    assert "missing" in summary.read_text(encoding="utf-8")


def test_bench_compare_aggregate_median_and_output_safety(tmp_path: Path) -> None:
    """Aggregate-only reports work, while existing summaries remain untouched."""
    source = tmp_path / "bench.json"
    source.write_text(
        json.dumps(
            {
                "benchmarks": [
                    {
                        "name": "scan_median",
                        "run_type": "aggregate",
                        "aggregate_name": "median",
                        "real_time": 100,
                        "time_unit": "ms",
                    },
                    {
                        "name": "scan_mean",
                        "run_type": "aggregate",
                        "aggregate_name": "mean",
                        "real_time": 1000,
                        "time_unit": "ms",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    summary = tmp_path / "summary.md"
    arguments = (
        "--gbench-base",
        str(source),
        "--gbench-head",
        str(source),
        "--summary",
        str(summary),
    )
    assert _run("bench_compare.py", *arguments).returncode == 0
    original = summary.read_bytes()
    assert _run("bench_compare.py", *arguments).returncode != 0
    assert summary.read_bytes() == original


def test_executable_comparison_warmups_and_alternates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Both binaries get a warmup, followed by five alternating measured runs."""
    calls: list[str] = []
    base_wall, head_wall = 100.0, 110.0

    def sample(executable: Path, fixture: Path, stats_path: Path) -> tuple[float, int]:
        calls.append(executable.name)
        return (base_wall if executable.name == "base" else head_wall, 80_000_000)

    monkeypatch.setattr(bench_compare, "_run_scan", sample)
    result = bench_compare.compare_executables(
        tmp_path / "base", tmp_path / "head", tmp_path, 5, threshold_pct=15, rss_threshold_pct=10
    )
    assert calls == [
        "base",
        "head",
        *(name for _ in range(5) for name in ("base", "head")),
    ]
    assert result.base_wall_ms == base_wall
    assert result.head_wall_ms == head_wall
    assert result.wall_change_pct == pytest.approx(10)
    assert result.rss_change_pct == 0
    assert not result.regression


def test_executable_comparison_without_base_checks_head_rss(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """First-PR mode runs one warmup plus five head scans and enforces the RSS ceiling."""
    calls = 0

    def sample(executable: Path, fixture: Path, stats_path: Path) -> tuple[float, int]:
        nonlocal calls
        calls += 1
        return (10.0, 120 * 1024 * 1024 + 1)

    monkeypatch.setattr(bench_compare, "_run_scan", sample)
    result = bench_compare.compare_executables(
        None, tmp_path / "head", tmp_path, 5, threshold_pct=15, rss_threshold_pct=10
    )
    expected_calls = 6
    assert calls == expected_calls
    assert result.base_wall_ms is result.base_rss_bytes is None
    assert result.regression
    report = bench_compare.render_cli_summary(
        result, has_base=False, threshold_pct=15, rss_threshold_pct=10
    )
    assert "no baseline" in report
    assert "FAIL" in report


def test_run_scan_uses_walk_without_progress_and_validates_stats(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The measured CLI workload stays stable and rejects malformed RSS samples."""
    observed: dict[str, object] = {}

    class Completed:
        returncode = 0
        stderr = b""

    def run(command: list[str], **kwargs: object) -> Completed:
        observed["command"] = command
        observed.update(kwargs)
        stats_path = Path(command[command.index("--stats-json") + 1])
        stats_path.write_text(
            json.dumps({"wall_ms": 12.5, "peak_rss_bytes": 4096}), encoding="utf-8"
        )
        return Completed()

    monkeypatch.setattr(bench_compare.subprocess, "run", run)
    assert bench_compare._run_scan(tmp_path / "dafree", tmp_path, tmp_path / "stats.json") == (
        12.5,
        4096,
    )
    command = observed["command"]
    assert isinstance(command, list)
    assert command[:5] == [str(tmp_path / "dafree"), "--progress", "never", "--format", "json"]
    assert command[command.index("--mode") + 1] == "walk"
    assert observed["stdout"] == bench_compare.subprocess.DEVNULL

    def malformed(command: list[str], **kwargs: object) -> Completed:
        stats_path = Path(command[command.index("--stats-json") + 1])
        stats_path.write_text('{"wall_ms": 12.5, "peak_rss_bytes": 4096.5}', encoding="utf-8")
        return Completed()

    monkeypatch.setattr(bench_compare.subprocess, "run", malformed)
    with pytest.raises(ValueError, match="positive integer"):
        bench_compare._run_scan(tmp_path / "dafree", tmp_path, tmp_path / "stats.json")


def test_bench_compare_first_pr_mode_reports_no_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The CLI accepts head plus fixture without base and writes a reviewable summary."""
    gbench = tmp_path / "bench.json"
    _benchmark(gbench, [100])
    summary = tmp_path / "summary.md"
    expected = bench_compare.CliComparison(None, 10.0, None, None, 80_000_000, None, False)
    observed: list[tuple[Path | None, Path, Path, int]] = []

    def compare_executables(  # noqa: PLR0913 -- Match the real function signature.
        base: Path | None,
        head: Path,
        fixture: Path,
        runs: int,
        *,
        threshold_pct: float,
        rss_threshold_pct: float,
    ) -> bench_compare.CliComparison:
        observed.append((base, head, fixture, runs))
        return expected

    monkeypatch.setattr(bench_compare, "compare_executables", compare_executables)
    assert (
        bench_compare.main(
            [
                "--head",
                str(tmp_path / "head"),
                "--fixture",
                str(tmp_path / "fixture"),
                "--gbench-base",
                str(gbench),
                "--gbench-head",
                str(gbench),
                "--summary",
                str(summary),
            ]
        )
        == 0
    )
    assert observed == [(None, tmp_path / "head", tmp_path / "fixture", 5)]
    report = summary.read_text(encoding="utf-8")
    assert "no baseline" in report
    assert "125829120 bytes" in report


@pytest.mark.parametrize(
    ("wall_ms", "rss_bytes", "regression"),
    [(115.0, 88_000_000, False), (115.001, 88_000_000, True), (115.0, 88_000_001, True)],
)
def test_executable_comparison_enforces_relative_limits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    wall_ms: float,
    rss_bytes: int,
    regression: bool,
) -> None:
    def sample(executable: Path, fixture: Path, stats_path: Path) -> tuple[float, int]:
        return (100.0, 80_000_000) if executable.name == "base" else (wall_ms, rss_bytes)

    monkeypatch.setattr(bench_compare, "_run_scan", sample)
    result = bench_compare.compare_executables(
        tmp_path / "base",
        tmp_path / "head",
        tmp_path,
        1,
        threshold_pct=15,
        rss_threshold_pct=10,
    )
    assert result.regression is regression
