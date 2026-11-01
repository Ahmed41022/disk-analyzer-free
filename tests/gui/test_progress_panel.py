"""Progress math, shared scan controls, native cancellation, and accessible announcements."""

# ruff: noqa: PLR2004 -- rate/estimate samples and exact EMA arithmetic are assertions.

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

from PySide6.QtCore import QCoreApplication, QEvent, QLocale
from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, TreeBuilder, make_mock_backend
from dafree.gui.controllers.scan_controller import ScanController
from dafree.gui.main_window import MainWindow
from dafree.gui.widgets.progress_panel import ProgressPanel, elapsed_text
from dafree.i18n import current_locale, setup
from dafree.settings import Settings

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def finish_qt_deletion(qapp: QApplication) -> Iterator[None]:
    """Deliver pytest-qt's deferred widget disposal before auditing native owners."""
    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def panel(qtbot: QtBot, tmp_path: Path) -> Iterator[ProgressPanel]:
    previous, language = QLocale(), current_locale()
    QLocale.setDefault(QLocale("en_US"))
    setup("en_US")
    controller = ScanController()
    widget = ProgressPanel(controller, Settings())
    qtbot.addWidget(widget)
    controller.started.emit(api.ScanRequest([tmp_path]))
    yield widget
    controller.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QLocale.setDefault(previous)
    setup(language)


def sample(files: int, milliseconds: int, **kwargs) -> api.ScanProgress:
    """Construct a copied progress message without any filesystem backend."""
    return api.ScanProgress(
        files,
        5,
        min(files * 10, (1 << 64) - 1),
        min(files * 16, (1 << 64) - 1),
        0,
        kwargs.pop("current", ""),
        milliseconds,
        kwargs.pop("state", api.ScanState.RUNNING),
        kwargs.pop("estimate", None),
        api.ScanModeUsed.WALK,
    )


def result(root: Path, cancelled: bool = False) -> api.ScanResult:
    """A native synthetic tree supports lifecycle presentation without reading user files."""
    tree = TreeBuilder.flat(root, 1)
    return api.ScanResult(tree, api.ScanSummary(0, 1, 0, 0, 1000, tree.meta().issues, cancelled))


def test_rate_smoothing(panel: ProgressPanel) -> None:
    """First positive-duration sample initializes the EMA; subsequent rates use alpha 0.3."""
    controller = panel._controller
    controller.progressChanged.emit(sample(0, 0))
    assert panel.rate is None
    controller.progressChanged.emit(sample(100, 1000))
    assert panel.rate == 100
    controller.progressChanged.emit(sample(300, 2000))
    assert panel.rate == pytest.approx(130)
    controller.progressChanged.emit(sample(600, 3000))
    assert panel.rate == pytest.approx(181)
    assert panel.rate_label.text() == "181.0 files/s"
    controller.progressChanged.emit(sample(600, 3000))
    assert panel.rate == pytest.approx(181)


def test_pause_button_toggles_and_calls_controller(panel: ProgressPanel, monkeypatch) -> None:
    """The same action state drives accessible Pause/Resume labels and controller commands."""
    calls = []
    monkeypatch.setattr(panel._controller, "pause", lambda: calls.append("pause"))
    monkeypatch.setattr(panel._controller, "resume", lambda: calls.append("resume"))
    panel.pause_button.click()
    assert panel.pause_action.isChecked() and panel.pause_action.text() == "Resume"
    assert panel.pause_button.accessibleName() == "Resume"
    panel.pause_button.click()
    assert not panel.pause_action.isChecked() and panel.pause_action.text() == "Pause"
    assert calls == ["pause", "resume"]


def test_cancel_shows_partial_badge(panel: ProgressPanel, tmp_path: Path, monkeypatch) -> None:
    """Cancellation calls the controller immediately and retains its partial-result badge."""
    calls = []
    monkeypatch.setattr(panel._controller, "cancel", lambda: calls.append(True))
    panel.cancel_button.click()
    assert calls == [True] and panel.partial_badge.isVisible()
    assert not panel.pause_action.isEnabled() and not panel.cancel_action.isEnabled()
    panel._controller.finished.emit(result(tmp_path, cancelled=True))
    assert panel.partial_badge.isVisible()
    assert panel.status.text() == "Scan cancelled. Partial results are available."
    assert panel.bar.maximum() == 1000


def test_estimates_and_busy_indicator(panel: ProgressPanel) -> None:
    """The bounded Qt range handles both unknown totals and uint64-sized native estimates."""
    panel._controller.progressChanged.emit(sample(25, 1000))
    assert panel.bar.maximum() == panel.bar.minimum() == 0
    panel._controller.progressChanged.emit(sample(25, 2000, estimate=100))
    assert panel.bar.maximum() == 1000 and panel.bar.value() == 300
    panel._controller.progressChanged.emit(sample(25, 3000, estimate=0))
    assert panel.bar.maximum() == 1000 and panel.bar.value() == 0
    huge = (1 << 64) - 1
    panel._controller.progressChanged.emit(sample(huge // 2, 4000, estimate=huge))
    assert panel.bar.maximum() == 1000 and 499 <= panel.bar.value() <= 501
    panel._controller.progressChanged.emit(sample(101, 5000, estimate=100))
    assert panel.bar.value() == 1000


def test_current_path_is_elided_but_accessible(
    panel: ProgressPanel, qtbot: QtBot, tmp_path: Path
) -> None:
    """Only display text is escaped; the complete path remains accessible and in the tooltip."""
    path = str(tmp_path / ("nested-" * 30) / "bad-\ud800")
    panel.resize(400, 150)
    panel._controller.progressChanged.emit(sample(10, 1000, current=path))
    qtbot.waitUntil(lambda: panel.current_path.width() > 0)
    assert panel.current_path.toolTip().endswith(r"bad-\ud800")
    assert panel.current_path.accessibleName() == panel.current_path.toolTip()
    assert (
        panel.current_path.fontMetrics().horizontalAdvance(panel.current_path.text())
        <= panel.current_path.width()
    )
    assert panel.current_path.text() != panel.current_path.toolTip()


def test_accessibility_announces_start_and_finish(
    panel: ProgressPanel, tmp_path: Path, monkeypatch
) -> None:
    """Lifecycle alerts carry the visible accessible status instead of per-tick announcements."""
    alerts = []
    monkeypatch.setattr(
        QAccessible,
        "updateAccessibility",
        lambda event: alerts.append((event.type(), event.object().accessibleName())),
    )
    panel._controller.started.emit(api.ScanRequest([tmp_path]))
    panel._controller.progressChanged.emit(sample(10, 1000))
    panel._controller.finished.emit(result(tmp_path))
    assert alerts == [
        (QAccessible.Event.Alert, "Scan started."),
        (QAccessible.Event.Alert, "Scan complete."),
    ]
    assert panel.bar.value() == 1000 and panel.partial_badge.isHidden()
    assert not panel.pause_action.isEnabled()


def test_restart_resets_metrics_and_failure(panel: ProgressPanel, tmp_path: Path) -> None:
    """A new scan clears errors, rate history, the partial badge and terminal controls."""
    panel._controller.progressChanged.emit(sample(100, 1000))
    panel._controller._fail("unavailable-\ud800")
    assert panel.status.toolTip() == r"unavailable-\ud800"
    assert panel.status.text() == "Scan failed." and panel.bar.value() == 0
    panel._controller.started.emit(api.ScanRequest([tmp_path]))
    assert panel.rate is None and panel.rate_label.text() == "Rate: —"
    assert panel.status.toolTip() == "" and panel.pause_action.isEnabled()
    assert panel.partial_badge.isHidden() and panel.bar.maximum() == 0


def test_counts_units_duration_and_rate_reset(panel: ProgressPanel) -> None:
    """Display values use shared units/locale, and a reset sample cannot create a negative rate."""
    panel._settings.units = api.UnitMode.BYTES
    panel._controller.progressChanged.emit(sample(100, 1000))
    assert panel.files.text() == "Files: 100" and panel.dirs.text() == "Folders: 5"
    assert panel.bytes.text() == "Total: " + api.format_size(1000, api.UnitMode.BYTES)
    assert panel.elapsed.text() == "Elapsed: 00:00:01"
    assert elapsed_text(90_061_000) == "1d 01:01:01"
    panel._controller.progressChanged.emit(sample(50, 500))
    assert panel.rate is None
    panel._controller.progressChanged.emit(sample(100, 1000))
    assert panel.rate == 100


def test_toolbar_and_panel_share_native_controls(qtbot: QtBot, tmp_path: Path) -> None:
    """Toolbar Pause and panel Resume control one native scan; Cancel returns its partial tree."""
    entries = [MockEntry(tmp_path, api.EntryKind.DIR)]
    for index in range(20):
        folder = tmp_path / str(index)
        entries.extend([MockEntry(folder, api.EntryKind.DIR), MockEntry(folder / "file", size=1)])
    window = MainWindow(
        volume_provider=lambda: [], scan_backend=make_mock_backend(MockSpec(entries, delay_ms=80))
    )

    def finish(widget):
        window.close()
        qtbot.waitUntil(
            lambda: not window.controller.running and not window.runner.busy, timeout=5000
        )

    qtbot.addWidget(window, before_close_func=finish)
    window.show()
    window.start_scan(api.ScanRequest([tmp_path], threads=1))
    panel = window.progress_panel
    assert panel.pause_action is window.pause and panel.cancel_action is window.cancel
    window.pause.trigger()
    assert panel.pause_action.isChecked() and panel.pause_action.text() == "Resume"
    panel.pause_button.click()
    assert not window.pause.isChecked() and window.pause.text() == "Pause"
    with qtbot.waitSignal(window.controller.finished, timeout=5000) as finished:
        panel.cancel_button.click()
    assert finished.args[0].summary.cancelled
    assert panel.partial_badge.isVisible() and not window.cancel.isEnabled()
    qtbot.waitUntil(lambda: not window.runner.busy)
    window.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
