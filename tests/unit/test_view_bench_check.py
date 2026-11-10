"""Performance gate rejects missing, failed, and threshold-equal benchmark results."""

import json
from pathlib import Path

import pytest

from tools.view_bench_check import check


@pytest.mark.parametrize(
    ("expand", "rows", "expected"),
    [(149.9, 1.9, True), (150, 1.9, False), (149.9, 2, False), (1, None, False)],
)
def test_view_benchmark_limits_are_strict(
    tmp_path: Path, expand: float, rows: float | None, expected: bool
) -> None:
    """Neither a missing result nor equality with a limit is accepted."""
    results = [{"name": "BM_Expand100kChildren/real_time", "real_time": expand, "time_unit": "ms"}]
    if rows is not None:
        results.append({"name": "BM_RowsWindow10M/real_time", "real_time": rows, "time_unit": "ms"})
    results.extend(
        {"name": name, "real_time": duration, "time_unit": "ms"}
        for name, duration in (("BM_Layout50k", 10), ("BM_Render1920x1080Cushion", 20))
    )
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"benchmarks": results}), encoding="utf-8")
    assert check(report) is expected


@pytest.mark.parametrize(
    ("layout", "render", "expected"),
    [(99.9, 59.9, True), (100, 1, False), (1, 60, False), (None, 1, False), (1, None, False)],
)
def test_treemap_benchmark_limits_are_strict(
    tmp_path: Path, layout: float | None, render: float | None, expected: bool
) -> None:
    """Both new acceptance benchmarks must exist and remain strictly below their caps."""
    results = [
        {"name": "BM_Expand100kChildren", "real_time": 1, "time_unit": "ms"},
        {"name": "BM_RowsWindow10M", "real_time": 1, "time_unit": "ms"},
    ]
    for name, duration in (("BM_Layout50k", layout), ("BM_Render1920x1080Cushion", render)):
        if duration is not None:
            results.append({"name": name, "real_time": duration, "time_unit": "ms"})
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"benchmarks": results}), encoding="utf-8")
    assert check(report) is expected
