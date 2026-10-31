"""Performance tools produce reproducible input and fail measurable regressions."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SMALL_NODES = 1000
REGRESSION = 120
ALLOWED_CHANGE = 114


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
    assert "pending T2.2" in report


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
