"""Editable native age reports, timestamp availability, and scoped Find handoff."""

# ruff: noqa: PLR2004 -- fixed clock, bucket counts, and fixture values are assertions.

import os
import threading
from collections.abc import Iterator
from importlib.util import find_spec
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QLabel

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.main_window import MainWindow
from dafree.gui.views import age_tab as age_tab_module
from dafree.gui.views.age_tab import AgeTab, parse_buckets
from dafree.paths import AppPaths
from dafree.settings import Settings

pytestmark = pytest.mark.gui
_DAY = 86_400
_NOW = 2_000_000_000


@pytest.fixture(autouse=True)
def fixed_clock_and_deferred_deletes(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Keep exact age boundaries deterministic and release queued Qt widget deletions."""
    monkeypatch.setattr(age_tab_module, "time", lambda: _NOW)
    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def age_tab(qtbot: QtBot) -> Iterator[tuple[AgeTab, TaskRunner]]:
    runner = TaskRunner()
    tab = AgeTab(Settings(), runner)
    qtbot.addWidget(tab)
    tab.resize(1000, 720)
    tab.show()
    yield tab, runner
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()


def _entries(root: Path) -> list[MockEntry]:
    return [
        MockEntry(root, api.EntryKind.DIR),
        MockEntry(root / "sub", api.EntryKind.DIR),
        MockEntry(
            root / "fresh.txt",
            size=100,
            mtime=_NOW - _DAY,
            btime=_NOW - 5 * _DAY,
            atime=_NOW - 2 * _DAY,
        ),
        MockEntry(root / "boundary.bin", size=200, mtime=_NOW - 30 * _DAY, atime=_NOW - 90 * _DAY),
        MockEntry(root / "sub/old.bin", size=300, mtime=_NOW - 100 * _DAY, btime=_NOW - 400 * _DAY),
        MockEntry(root / "unknown.bin", size=400),
        MockEntry(
            root / "zero.bin",
            size=0,
            mtime=_NOW - 45 * _DAY,
            btime=_NOW - 100 * _DAY,
            atime=_NOW - _DAY,
        ),
    ]


def _scan(root: Path, entries: list[MockEntry] | None = None) -> api.Tree:
    return api.scan(
        api.ScanRequest([root], threads=1),
        backend=make_mock_backend(MockSpec(_entries(root) if entries is None else entries)),
    ).tree


def _set_tree(tab: AgeTab, qtbot: QtBot, tree: api.Tree) -> None:
    tab.buckets.setText("30d,90d")
    tab.apply.click()
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.set_tree(tree)


def _values(chart) -> list[int]:
    return [item.value for item in chart.slices]


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("30d,90d,1y", [30 * _DAY, 90 * _DAY, 365 * _DAY, None]),
        ("1w,2m,1y", [7 * _DAY, 60 * _DAY, 365 * _DAY, None]),
        (" 1D , 2W , 1M ", [_DAY, 14 * _DAY, 30 * _DAY, None]),
    ],
)
def test_custom_buckets_parse(text: str, seconds: list[int | None]) -> None:
    buckets = parse_buckets(text)
    assert isinstance(buckets, tuple)
    assert [bucket.max_age_secs for bucket in buckets] == seconds
    assert all(bucket.label for bucket in buckets)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "0d",
        "-1d",
        "30",
        "1h",
        "1.5d",
        "90d,30d",
        "30d,30d",
        "1y,365d",
        "30d,",
        ",30d",
        "30d,,90d",
        "nonsense",
    ],
)
def test_invalid_custom_buckets_are_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_buckets(text)


def test_bucket_count_and_unsigned_64_bit_limits() -> None:
    assert len(parse_buckets(",".join(f"{index}d" for index in range(1, 15)))) == 15
    with pytest.raises(ValueError):
        parse_buckets(",".join(f"{index}d" for index in range(1, 16)))
    largest_days = ((1 << 64) - 1) // _DAY
    assert parse_buckets(f"{largest_days}d")[0].max_age_secs == largest_days * _DAY
    with pytest.raises(ValueError):
        parse_buckets(f"{largest_days + 1}d")


def test_native_histogram_has_exact_boundaries_counts_sizes_and_unknown(
    qtbot: QtBot, tmp_path: Path, age_tab: tuple[AgeTab, TaskRunner]
) -> None:
    tab, _ = age_tab
    _set_tree(tab, qtbot, _scan(tmp_path / "histogram"))
    assert tab.field.currentData() == api.TimeField.MODIFIED
    assert _values(tab.size_chart) == [100, 200, 300, 400]
    assert _values(tab.count_chart) == [1, 2, 1, 1]
    assert sum(_values(tab.size_chart)) == 1000
    assert sum(_values(tab.count_chart)) == 5


def test_invalid_edit_keeps_last_successful_histogram(
    qtbot: QtBot, tmp_path: Path, age_tab: tuple[AgeTab, TaskRunner]
) -> None:
    tab, runner = age_tab
    _set_tree(tab, qtbot, _scan(tmp_path / "invalid-edit"))
    before_size, before_count = tab.size_chart.slices, tab.count_chart.slices
    ready = QSignalSpy(tab.ready)
    tab.buckets.setText("90d,30d")
    tab.apply.click()
    assert tab.size_chart.slices == before_size
    assert tab.count_chart.slices == before_count
    assert tab.message.isVisible()
    assert ready.count() == 0
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)


def test_created_availability_and_fallback_follow_new_scan(
    qtbot: QtBot, tmp_path: Path, age_tab: tuple[AgeTab, TaskRunner]
) -> None:
    tab, _ = age_tab
    _set_tree(tab, qtbot, _scan(tmp_path / "birth-times"))
    created_index = tab.field.findData(api.TimeField.CREATED)
    model_index = tab.field.model().index(created_index, 0)
    assert tab.field.model().flags(model_index) & Qt.ItemFlag.ItemIsEnabled
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.field.setCurrentIndex(created_index)
    assert _values(tab.size_chart) == [100, 300, 600]
    assert _values(tab.count_chart) == [1, 2, 2]
    root = tmp_path / "no-birth-times"
    new_tree = _scan(
        root,
        [
            MockEntry(root, api.EntryKind.DIR),
            MockEntry(root / "file.bin", size=11, mtime=_NOW - _DAY),
        ],
    )
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.set_tree(new_tree)
    assert tab.field.currentData() == api.TimeField.MODIFIED
    assert not tab.field.model().flags(model_index) & Qt.ItemFlag.ItemIsEnabled
    assert tab.field.itemData(created_index, Qt.ItemDataRole.ToolTipRole)
    assert _values(tab.size_chart) == [11]


def test_accessed_chart_and_access_time_limitation_note(
    qtbot: QtBot, tmp_path: Path, age_tab: tuple[AgeTab, TaskRunner]
) -> None:
    tab, _ = age_tab
    _set_tree(tab, qtbot, _scan(tmp_path / "accessed"))
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.field.setCurrentIndex(tab.field.findData(api.TimeField.ACCESSED))
    assert _values(tab.size_chart) == [100, 200, 700]
    assert _values(tab.count_chart) == [2, 1, 2]
    note = " ".join(label.text() for label in tab.findChildren(QLabel))
    assert "noatime" in note and "relatime" in note and "DisableLastAccess" in note


@pytest.mark.parametrize(
    "field", [api.TimeField.MODIFIED, api.TimeField.CREATED, api.TimeField.ACCESSED]
)
def test_bucket_click_opens_find(qtbot: QtBot, tmp_path: Path, field: api.TimeField) -> None:
    root = tmp_path / "find-handoff"
    window = MainWindow(
        paths=AppPaths(
            tmp_path / "config", tmp_path / "data", tmp_path / "logs", tmp_path / "snapshots", False
        ),
        settings=Settings(),
        scan_backend=make_mock_backend(MockSpec(_entries(root))),
        volume_provider=lambda: [],
    )

    def finish(widget) -> None:
        widget.close()
        qtbot.waitUntil(
            lambda: not window.controller.running and not window.runner.busy, timeout=10_000
        )

    qtbot.addWidget(window, before_close_func=finish)
    window.show()
    with qtbot.waitSignal(window.controller.finished, timeout=5000):
        window.start_scan(api.ScanRequest([root], threads=1))
    assert "age" not in window._pages
    window.show_tab("age")
    tab = window._pages["age"]
    assert isinstance(tab, AgeTab)
    qtbot.waitUntil(lambda: bool(tab.size_chart.slices), timeout=5000)
    tab.buckets.setText("30d,90d")
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.apply.click()
    if field != api.TimeField.MODIFIED:
        with qtbot.waitSignal(tab.ready, timeout=5000):
            tab.field.setCurrentIndex(tab.field.findData(field))
    tree, scope = tab.tree, tab.scope
    assert tree is not None and scope is not None
    point = tab.size_chart.slice_point(0).toPoint()
    qtbot.mouseClick(tab.size_chart, Qt.MouseButton.LeftButton, pos=point)
    assert window._tab_keys[window.tabs.currentIndex()] == "find"
    assert window.find_query.text() == f"type:file {field.name.lower()}<30d"
    assert window.find_tree is tree and window.find_scope == scope


def test_sparse_chart_maps_visible_index_back_to_original_bucket(
    qtbot: QtBot, tmp_path: Path, age_tab: tuple[AgeTab, TaskRunner]
) -> None:
    tab, _ = age_tab
    tree = _scan(tmp_path / "sparse")
    _set_tree(tab, qtbot, tree)
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.field.setCurrentIndex(tab.field.findData(api.TimeField.CREATED))
    assert _values(tab.size_chart) == [100, 300, 600]
    with qtbot.waitSignal(tab.findRequested, timeout=5000) as requested:
        qtbot.mouseClick(
            tab.size_chart, Qt.MouseButton.LeftButton, pos=tab.size_chart.slice_point(1).toPoint()
        )
    assert requested.args == [tree, tree.roots()[0], "type:file created>=90d"]


def test_middle_bucket_query_has_inclusive_lower_and_exclusive_upper_limit(
    qtbot: QtBot, tmp_path: Path, age_tab: tuple[AgeTab, TaskRunner]
) -> None:
    tab, _ = age_tab
    tree = _scan(tmp_path / "middle")
    _set_tree(tab, qtbot, tree)
    with qtbot.waitSignal(tab.findRequested, timeout=5000) as requested:
        qtbot.mouseClick(
            tab.count_chart, Qt.MouseButton.LeftButton, pos=tab.count_chart.slice_point(1).toPoint()
        )
    assert requested.args == [tree, tree.roots()[0], "type:file modified>=30d modified<90d"]


def test_zero_byte_bucket_keeps_independent_size_and_count_chart_mapping(
    qtbot: QtBot, tmp_path: Path, age_tab: tuple[AgeTab, TaskRunner]
) -> None:
    tab, _ = age_tab
    root = tmp_path / "zero-byte-bucket"
    tree = _scan(
        root,
        [
            MockEntry(root, api.EntryKind.DIR),
            MockEntry(root / "recent-empty.bin", size=0, mtime=_NOW - _DAY),
            MockEntry(root / "old.bin", size=4, mtime=_NOW - 100 * _DAY),
        ],
    )
    _set_tree(tab, qtbot, tree)
    assert _values(tab.size_chart) == [4]
    assert _values(tab.count_chart) == [1, 1]
    for chart, query in (
        (tab.size_chart, "type:file modified>=90d"),
        (tab.count_chart, "type:file modified<30d"),
    ):
        with qtbot.waitSignal(tab.findRequested, timeout=5000) as requested:
            qtbot.mouseClick(chart, Qt.MouseButton.LeftButton, pos=chart.slice_point(0).toPoint())
        assert requested.args == [tree, tree.roots()[0], query]


def test_unknown_bucket_cannot_open_find(
    qtbot: QtBot, tmp_path: Path, age_tab: tuple[AgeTab, TaskRunner]
) -> None:
    tab, _ = age_tab
    root = tmp_path / "unknown"
    _set_tree(
        tab,
        qtbot,
        _scan(root, [MockEntry(root, api.EntryKind.DIR), MockEntry(root / "file", size=11)]),
    )
    assert _values(tab.size_chart) == [11]
    assert _values(tab.count_chart) == [1]
    requested = QSignalSpy(tab.findRequested)
    for chart in (tab.size_chart, tab.count_chart):
        qtbot.mouseClick(chart, Qt.MouseButton.LeftButton, pos=chart.slice_point(0).toPoint())
        chart.setFocus()
        qtbot.keyClick(chart, Qt.Key.Key_Return)
    assert requested.count() == 0


def test_file_parent_scope_breadcrumb_and_empty_histogram(
    qtbot: QtBot, tmp_path: Path, age_tab: tuple[AgeTab, TaskRunner]
) -> None:
    tab, _ = age_tab
    root = tmp_path / "scope"
    tree = _scan(root)
    old_file = tree.find_path(root / "sub/old.bin")
    parent = tree.find_path(root / "sub")
    assert old_file is not None and parent is not None
    _set_tree(tab, qtbot, tree)
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.select_node(old_file)
    assert tab.scope == parent
    assert _values(tab.size_chart) == [300]
    assert _values(tab.count_chart) == [1]
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.breadcrumb.up.click()
    assert tab.scope == tree.roots()[0]
    empty_root = tmp_path / "empty"
    empty_tree = _scan(empty_root, [MockEntry(empty_root, api.EntryKind.DIR)])
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.set_tree(empty_tree)
    assert tab.size_chart.slices == () and tab.count_chart.slices == ()


def test_units_reformat_size_chart_without_rebuilding_histogram(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings()
    runner = TaskRunner()
    tab = AgeTab(settings, runner)
    qtbot.addWidget(tab)
    original, calls = age_tab_module._prepare, []

    def count_prepare(tree, scope, field, buckets, now):
        calls.append((tree, scope, field, buckets, now))
        return original(tree, scope, field, buckets, now)

    monkeypatch.setattr(age_tab_module, "_prepare", count_prepare)
    _set_tree(tab, qtbot, _scan(tmp_path / "units"))
    settings.units = api.UnitMode.BYTES
    tab.refresh_settings()
    assert len(calls) == 1
    assert (
        api.format_size(100, settings.units, settings.unit_style)
        in tab.size_chart.slice_labels()[0]
    )
    assert " B" not in tab.count_chart.slice_labels()[0]
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    runner.deleteLater()


def test_new_tree_supersedes_inflight_histogram(
    qtbot: QtBot,
    tmp_path: Path,
    age_tab: tuple[AgeTab, TaskRunner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tab, runner = age_tab
    old_tree = _scan(tmp_path / "old")
    new_root = tmp_path / "new"
    new_tree = _scan(
        new_root,
        [
            MockEntry(new_root, api.EntryKind.DIR),
            MockEntry(new_root / "file.bin", size=42, mtime=_NOW - _DAY),
        ],
    )
    original = age_tab_module._prepare
    started, release = threading.Event(), threading.Event()

    def gated_prepare(tree, scope, field, buckets, now):
        if tree is old_tree:
            started.set()
            if not release.wait(5):
                raise TimeoutError("age preparation gate was not released")
        return original(tree, scope, field, buckets, now)

    monkeypatch.setattr(age_tab_module, "_prepare", gated_prepare)
    ready = QSignalSpy(tab.ready)
    tab.set_tree(old_tree)
    qtbot.waitUntil(started.is_set, timeout=5000)
    try:
        tab.set_tree(new_tree)
        with qtbot.waitSignal(tab.ready, timeout=5000):
            release.set()
        qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    finally:
        release.set()
    assert ready.count() == 1
    assert tab.tree is new_tree and _values(tab.size_chart) == [42]


def test_clear_discards_inflight_histogram(
    qtbot: QtBot,
    tmp_path: Path,
    age_tab: tuple[AgeTab, TaskRunner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tab, runner = age_tab
    tree = _scan(tmp_path / "clear")
    original = age_tab_module._prepare
    started, release = threading.Event(), threading.Event()

    def gated_prepare(tree, scope, field, buckets, now):
        started.set()
        if not release.wait(5):
            raise TimeoutError("age preparation gate was not released")
        return original(tree, scope, field, buckets, now)

    monkeypatch.setattr(age_tab_module, "_prepare", gated_prepare)
    ready = QSignalSpy(tab.ready)
    tab.set_tree(tree)
    qtbot.waitUntil(started.is_set, timeout=5000)
    try:
        tab.clear()
        release.set()
        qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    finally:
        release.set()
    assert ready.count() == 0
    assert tab.tree is None and tab.scope is None
    assert tab.size_chart.slices == () and tab.count_chart.slices == ()


def test_scope_field_and_bucket_changes_coalesce_to_latest_request(
    qtbot: QtBot,
    tmp_path: Path,
    age_tab: tuple[AgeTab, TaskRunner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tab, runner = age_tab
    root = tmp_path / "coalesced"
    tree = _scan(root)
    parent = tree.find_path(root / "sub")
    assert parent is not None
    original = age_tab_module._prepare
    started, release = threading.Event(), threading.Event()
    calls = []

    def gated_prepare(tree, scope, field, buckets, now):
        calls.append((scope, field, tuple(bucket.max_age_secs for bucket in buckets), now))
        if len(calls) == 1:
            started.set()
            if not release.wait(5):
                raise TimeoutError("age preparation gate was not released")
        return original(tree, scope, field, buckets, now)

    monkeypatch.setattr(age_tab_module, "_prepare", gated_prepare)
    ready = QSignalSpy(tab.ready)
    tab.set_tree(tree)
    qtbot.waitUntil(started.is_set, timeout=5000)
    try:
        tab.select_node(parent)
        tab.field.setCurrentIndex(tab.field.findData(api.TimeField.ACCESSED))
        tab.buckets.setText("90d,1y")
        tab.apply.click()
        with qtbot.waitSignal(tab.ready, timeout=5000):
            release.set()
        qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    finally:
        release.set()
    assert len(calls) == 2
    assert calls[-1] == (parent, api.TimeField.ACCESSED, (90 * _DAY, 365 * _DAY, None), _NOW)
    assert ready.count() == 1
    assert tab.scope == parent and _values(tab.size_chart) == [300]


def test_histogram_failure_can_recover_on_next_scope(
    qtbot: QtBot,
    tmp_path: Path,
    age_tab: tuple[AgeTab, TaskRunner],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tab, runner = age_tab
    root = tmp_path / "recovery"
    tree = _scan(root)
    parent = tree.find_path(root / "sub")
    assert parent is not None
    original, calls = age_tab_module._prepare, 0

    def fail_first(tree, scope, field, buckets, now):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("deliberate histogram failure")
        return original(tree, scope, field, buckets, now)

    monkeypatch.setattr(age_tab_module, "_prepare", fail_first)
    tab.set_tree(tree)
    qtbot.waitUntil(lambda: not runner.busy, timeout=5000)
    assert "deliberate histogram failure" in tab.message.text()
    assert tab.size_chart.slices == () and tab.count_chart.slices == ()
    with qtbot.waitSignal(tab.ready, timeout=5000):
        tab.select_node(parent)
    assert _values(tab.size_chart) == [300]
