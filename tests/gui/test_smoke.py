"""Desktop application startup tests."""

import os
from importlib.util import find_spec
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from dafree.api import ScanRequest, TreeView
from dafree.gui.app import _ApplicationState, build_app
from dafree.gui.controllers.scan_controller import ScanController
from dafree.gui.main_window import create_main_window
from dafree.gui.models.tree_model import TreeTableModel
from dafree.gui.widgets.tree_table import TreeTable
from dafree.paths import AppPaths
from dafree.settings import ColumnId, Settings


@pytest.mark.gui
def test_gui_main_window_opens_and_closes(qtbot: QtBot) -> None:
    """The main window can be shown and closed by the Qt test harness."""
    window = create_main_window()
    qtbot.addWidget(window)
    window.show()

    assert window.windowTitle() == "Disk Analyzer Free"

    window.close()


@pytest.mark.gui
def test_gui_bootstrap_and_scan_smoke(qtbot: QtBot, tmp_path: Path) -> None:
    """The light CI tier configures the GUI and completes a real temporary-file scan."""
    profile = tmp_path / "profile"
    paths = AppPaths(
        profile, profile / "data", profile / "data/logs", profile / "data/snapshots", False
    )
    target = tmp_path / "target"
    target.mkdir()
    payload = b"GUI smoke"
    (target / "sample.bin").write_bytes(payload)
    app = build_app([], paths, Settings(locale="en_US"))
    state = app.findChild(_ApplicationState, "dafree.application")
    assert state is not None
    window = create_main_window()
    qtbot.addWidget(window)
    controller = ScanController(window)
    try:
        window.show()
        with qtbot.waitSignal(controller.finished, timeout=5000) as finished:
            controller.start(ScanRequest([target], threads=1))
        assert finished.args is not None
        result = finished.args[0]
        assert result.summary.files == 1
        assert result.summary.bytes == len(payload)
        assert not controller.running
        model = TreeTableModel(TreeView(result.tree), list(ColumnId))
        table = TreeTable(model, Settings(), window)
        window.setCentralWidget(table)
        expected_rows = 2
        assert model.rowCount() == expected_rows
        assert not table.grab().isNull()
        model.toggle(0)
        assert model.rowCount() == 1
        model.toggle(0)
        assert model.rowCount() == expected_rows
    finally:
        window.close()
        state.close()
        state.setParent(None)
        state.deleteLater()
