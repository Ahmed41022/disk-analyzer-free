"""Desktop application startup tests."""

import os
from collections.abc import Iterator
from importlib.util import find_spec
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent

from dafree.api import ScanRequest
from dafree.gui.app import _ApplicationState, build_app
from dafree.gui.main_window import MainWindow, create_main_window
from dafree.gui.views.tree_tab import TreeTab
from dafree.paths import AppPaths
from dafree.settings import Settings


@pytest.fixture(autouse=True)
def dispose_widgets() -> Iterator[None]:
    """Flush pytest-qt's deferred QObject deletions before native binding leak auditing."""
    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def finish_window(window: MainWindow, qtbot: QtBot) -> None:
    """Finish owned callbacks before pytest-qt schedules deletion of native-backed widgets."""
    window.close()
    qtbot.waitUntil(
        lambda: not window.controller.running and not window.runner.busy, timeout=10_000
    )


@pytest.mark.gui
def test_gui_main_window_opens_and_closes(qtbot: QtBot) -> None:
    """The main window can be shown and closed by the Qt test harness."""
    window = create_main_window()
    qtbot.addWidget(window, before_close_func=lambda widget: finish_window(window, qtbot))
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
    window = create_main_window(paths=paths, settings=Settings())
    qtbot.addWidget(window, before_close_func=lambda widget: finish_window(window, qtbot))
    controller = window.controller
    try:
        window.show()
        with qtbot.waitSignal(controller.finished, timeout=5000) as finished:
            window.start_scan(ScanRequest([target], threads=1))
        assert finished.args is not None
        result = finished.args[0]
        assert result.summary.files == 1
        assert result.summary.bytes == len(payload)
        assert not controller.running
        page = window._pages["tree"]
        assert isinstance(page, TreeTab)
        qtbot.waitUntil(lambda: page.table is not None)
        table = page.table
        assert table is not None
        model = table.tree_model
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
