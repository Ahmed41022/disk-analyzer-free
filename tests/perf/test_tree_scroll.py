"""Release Qt repaint budget on an exactly ten-million-row native synthetic tree."""

# ruff: noqa: PLR2004 -- the owner-specified row/sample/time budgets must remain literal.

import json
import math
import os
import statistics
from collections.abc import Callable
from importlib.util import find_spec
from pathlib import Path
from time import perf_counter_ns

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QObject
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QAbstractItemView, QApplication

from dafree import api
from dafree.api.testing import TreeBuilder
from dafree.gui.app import _ApplicationState, build_app
from dafree.gui.models.tree_model import TreeTableModel
from dafree.gui.widgets.tree_table import TreeTable
from dafree.paths import AppPaths
from dafree.settings import ColumnId, Settings


class PaintCounter(QObject):
    """Prevent timing an invisible widget or a jump that never actually repaints."""

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.paints = 0

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Paint:
            self.paints += 1
        return False


@pytest.mark.gui
@pytest.mark.slow
def test_scroll_10m_rows_frame_times(
    qtbot: QtBot,
    tmp_path: Path,
    record_property: Callable[[str, object], None],
) -> None:
    """Time all 60 jumps including page fetch, painting, and pending Qt events."""
    profile = tmp_path / "profile"
    paths = AppPaths(profile, profile / "data", profile / "logs", profile / "snapshots", False)
    settings = Settings(locale="en_US")
    app = build_app([], paths, settings)
    state = app.findChild(_ApplicationState, "dafree.application")
    assert state is not None
    tree = TreeBuilder.flat(tmp_path / "synthetic", 10_000_000)
    model = TreeTableModel(api.TreeView(tree), list(ColumnId))
    table = TreeTable(model, settings)
    table.resize(1280, 720)
    counter = PaintCounter(table)
    table.viewport().installEventFilter(counter)
    try:
        table.show()
        qtbot.waitUntil(lambda: counter.paints > 0)
        QApplication.processEvents()
        assert QFontDatabase.families(), "Repaint budgets require real system fonts"
        assert model.rowCount() == 10_000_000
        assert table.verticalScrollBar().maximum() > 9_000_000
        assert table.viewport().isVisible() and table.viewport().updatesEnabled()
        jumps = [0, 9_999_999] + [(i * 1_548_587) % 10_000_000 for i in range(1, 59)]
        assert len(jumps) == len(set(jumps)) == 60
        times: list[float] = []
        paint_counts: list[int] = []
        for row in jumps:
            paints = counter.paints
            start = perf_counter_ns()
            table.scrollTo(model.index(row, 0), QAbstractItemView.ScrollHint.PositionAtTop)
            table.viewport().repaint()
            QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
            times.append((perf_counter_ns() - start) / 1_000_000)
            assert counter.paints > paints
            paint_counts.append(counter.paints - paints)
        median = statistics.median(times)
        p95 = sorted(times)[math.ceil(0.95 * len(times)) - 1]
        metrics = {
            "visible_rows": model.rowCount(),
            "jumps": len(times),
            "median_repaint_ms": median,
            "p95_repaint_ms": p95,
            "all_repaint_ms": json.dumps(times),
            "paint_events_per_jump": json.dumps(paint_counts),
        }
        for key, value in metrics.items():
            record_property(key, value)
        print(json.dumps({"median_repaint_ms": median, "p95_repaint_ms": p95, "jumps": len(times)}))
        assert median <= 16.7, f"median repaint {median:.3f} ms exceeds 16.7 ms"
        assert p95 <= 33, f"p95 repaint {p95:.3f} ms exceeds 33 ms"
    finally:
        table.close()
        table.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        state.close()
        state.setParent(None)
