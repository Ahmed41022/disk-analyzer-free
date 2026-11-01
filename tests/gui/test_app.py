"""Bootstrap, worker delivery, diagnostics, and actual local-instance forwarding."""

# ruff: noqa: PLR2004 -- fixed contract limits and fixture counts are explicit assertions.

import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from datetime import date, timedelta
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QDir, QLocale, Qt, QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from dafree.gui import app as bootstrap
from dafree.gui.app import _ApplicationState, _SingleInstance, build_app
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.main_window import MainWindow
from dafree.i18n import current_locale, setup
from dafree.paths import AppPaths
from dafree.settings import Settings

pytestmark = pytest.mark.gui


def paths_at(root: Path) -> AppPaths:
    """Keep every application-owned file inside this test's temporary root."""
    return AppPaths(root, root / "data", root / "data/logs", root / "data/snapshots", False)


def run_child(qtbot: QtBot, script: str, env: dict[str, str]) -> None:
    """Service the first instance's event loop while its peer waits for an IPC acknowledgment."""
    with subprocess.Popen(  # noqa: S603 -- fixed child scripts and test-owned config/IPC paths.
        [sys.executable, "-c", script], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ) as child:
        try:
            qtbot.waitUntil(lambda: child.poll() is not None, timeout=30_000)
            _stdout, stderr = child.communicate(timeout=5)
            assert child.returncode == 0, stderr.decode("utf-8", errors="backslashreplace")
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


@pytest.fixture(autouse=True)
def restore_application(qapp: QApplication) -> Iterator[None]:
    """Restore global Qt/gettext state and exception hooks after each test."""
    locale, qt_locale = current_locale(), QLocale()
    palette, stylesheet = qapp.palette(), qapp.styleSheet()
    direction = qapp.layoutDirection()
    yield
    state = qapp.findChild(_ApplicationState, "dafree.application")
    if state is not None:
        state.close()
        state.setParent(None)
        state.deleteLater()
    setup(locale)
    QLocale.setDefault(qt_locale)
    qapp.setPalette(palette)
    qapp.setStyleSheet(stylesheet)
    qapp.setLayoutDirection(direction)


def test_app_applies_dark_palette(qapp: QApplication, tmp_path: Path) -> None:
    """The initial dark Fusion palette and packaged stylesheet are applied."""
    app = build_app([], paths_at(tmp_path), Settings(theme="dark", locale="en_US"))
    assert app is qapp
    assert app.palette().color(QPalette.ColorRole.Window).name() == "#23262b"
    assert app.palette().color(QPalette.ColorRole.Text).lightness() > 200
    assert "QAbstractItemView" in app.styleSheet()
    # A stylesheet wraps Fusion in QStyleSheetStyle; unwrap it to inspect the base.
    stylesheet = app.styleSheet()
    app.setStyleSheet("")
    assert app.style().objectName().lower() == "fusion"
    app.setStyleSheet(stylesheet)
    assert app.layoutDirection() == Qt.LayoutDirection.LeftToRight


def test_app_initial_locale_sets_layout_direction(qapp: QApplication, tmp_path: Path) -> None:
    """Bootstrap honors the selected locale without implementing deferred RTL UI work."""
    build_app([], paths_at(tmp_path), Settings(locale="ar"))
    assert current_locale() == "ar"
    assert qapp.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert QLocale().language() == QLocale.Language.Arabic


def test_task_runner_emits_finished(qtbot: QtBot) -> None:
    """Return the same task ID and Python result object across the worker boundary."""
    runner = TaskRunner()
    task_id, result = ["unhashable ID"], {"answer": 42}
    with qtbot.waitSignal(runner.finished, timeout=5000) as completed:
        runner.submit(lambda: result, task_id=task_id)
    assert completed.args is not None
    assert completed.args[0] is task_id
    assert completed.args[1] is result
    assert runner._pending == {}


@pytest.mark.parametrize(
    ("message", "expected"), [("worker-test", "worker-test"), ("bad-\ud800", r"bad-\ud800")]
)
def test_task_runner_emits_failed_on_exception(qtbot: QtBot, message: str, expected: str) -> None:
    """A failing callable is reported and does not kill a worker or the GUI thread."""
    runner = TaskRunner()

    def fail() -> None:
        raise ValueError(message)

    with qtbot.waitSignal(runner.failed, timeout=5000) as failed:
        runner.submit(fail, task_id="bad")
    assert failed.args == ["bad", expected]
    with qtbot.waitSignal(runner.finished, timeout=5000) as completed:
        runner.submit(lambda: "still working", task_id="good")
    assert completed.args == ["good", "still working"]


def test_task_runner_delivers_on_gui_thread_without_blocking(qtbot: QtBot) -> None:
    """A GUI timer fires while a callable waits; completion is delivered on the caller thread."""
    runner = TaskRunner()
    release, heartbeat = threading.Event(), threading.Event()
    gui_id = threading.get_ident()
    deliveries: list[int] = []
    runner.finished.connect(lambda _task, _result: deliveries.append(threading.get_ident()))

    def work() -> int:
        assert release.wait(5)
        return threading.get_ident()

    try:
        with qtbot.waitSignal(runner.finished, timeout=5000) as completed:
            runner.submit(work, task_id="blocked")
            QTimer.singleShot(0, heartbeat.set)
            qtbot.waitUntil(heartbeat.is_set, timeout=2000)
            release.set()
        assert completed.args is not None
        assert completed.args[1] != gui_id
        assert deliveries == [gui_id]
    finally:
        release.set()


def test_task_runner_has_at_most_four_active_jobs(qtbot: QtBot) -> None:
    """Eight queued jobs cannot oversubscribe the planned four-worker limit."""
    runner = TaskRunner()
    lock, release = threading.Lock(), threading.Event()
    active = peak = 0
    finished: list[object] = []
    runner.finished.connect(lambda task, _result: finished.append(task))

    def work() -> None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            assert release.wait(5)
        finally:
            with lock:
                active -= 1

    try:
        for task in range(8):
            runner.submit(work, task_id=task)
        qtbot.waitUntil(lambda: active >= 4, timeout=2000)
        assert active == 4
        release.set()
        qtbot.waitUntil(lambda: len(finished) == 8, timeout=5000)
        assert peak == 4
    finally:
        release.set()


@pytest.mark.parametrize(
    ("message", "expected"),
    [("bootstrap-test", "bootstrap-test"), ("bad-\ud800", r"bad-\ud800")],
)
def test_app_logs_uncaught_exception_and_copies_details(
    qtbot: QtBot, tmp_path: Path, message: str, expected: str
) -> None:
    """Unhandled details reach both the dated log and the dialog's copy action."""
    paths = paths_at(tmp_path)
    app = build_app([], paths, Settings(locale="en_US"))
    try:
        raise ValueError(message)
    except ValueError as error:
        sys.excepthook(type(error), error, error.__traceback__)
    state = app.findChild(_ApplicationState, "dafree.application")
    assert state is not None
    qtbot.waitUntil(lambda: bool(state._dialogs), timeout=2000)
    dialog = state._dialogs[0]
    details = dialog.detailedText()
    assert f"ValueError: {expected}" in details
    button = next(button for button in dialog.buttons() if button.text() == "Copy details")
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert app.clipboard().text() == details
    logs = list(paths.logs.glob("dafree-*.log"))
    assert len(logs) == 1
    assert f"ValueError: {expected}" in logs[0].read_text(encoding="utf-8")


def test_app_retains_seven_logs_and_preserves_links(qapp: QApplication, tmp_path: Path) -> None:
    """Retention touches only dated regular app logs and never follows a link."""
    paths = paths_at(tmp_path)
    paths.logs.mkdir(parents=True)
    for age in range(1, 11):
        day = date.today() - timedelta(days=age)
        (paths.logs / f"dafree-{day:%Y%m%d}.log").write_text("old log", encoding="utf-8")
    future = date.today() + timedelta(days=365)
    (paths.logs / f"dafree-{future:%Y%m%d}.log").write_text("clock was ahead", encoding="utf-8")
    protected = tmp_path / "protected.txt"
    protected.write_text("keep", encoding="utf-8")
    link = paths.logs / "dafree-20000101.log"
    link.symlink_to(protected)
    unrelated = paths.logs / "notes.txt"
    unrelated.write_text("keep too", encoding="utf-8")
    build_app([], paths, Settings(locale="en_US"))
    assert len([path for path in paths.logs.glob("dafree-*.log") if not path.is_symlink()]) == 7
    assert link.is_symlink()
    assert protected.read_text(encoding="utf-8") == "keep"
    assert unrelated.read_text(encoding="utf-8") == "keep too"


def test_app_refuses_a_link_for_current_log(tmp_path: Path) -> None:
    """A diagnostic filename cannot redirect appends into an unrelated file."""
    paths = paths_at(tmp_path)
    paths.logs.mkdir(parents=True)
    target = tmp_path / "target.txt"
    target.write_text("untouched", encoding="utf-8")
    (paths.logs / f"dafree-{date.today():%Y%m%d}.log").symlink_to(target)
    with pytest.raises(OSError, match="must not be a link"):
        build_app([], paths, Settings(locale="en_US"))
    assert target.read_text(encoding="utf-8") == "untouched"


def test_single_instance_lock(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real second process forwards arguments, exits, and cannot unlock the first."""
    with TemporaryDirectory(prefix="da-") as directory:
        monkeypatch.setattr(QDir, "tempPath", lambda: directory)
        paths = paths_at(tmp_path)
        first, second = _SingleInstance(paths), _SingleInstance(paths)
        try:
            assert first.acquire()
            os.utime(paths.data / "instance.lock", (1, 1))
            assert first._lock.staleLockTime() == second._lock.staleLockTime() == 0
            assert not second.acquire()
            arguments = ["folder with space", "العربية", "bad-\ud800"]
            script = """
from PySide6.QtWidgets import QApplication
from dafree.gui.app import _SingleInstance
from dafree.paths import detect
app = QApplication([])
guard = _SingleInstance(detect())
assert not guard.acquire()
assert guard.forward([
    'folder with space', '\u0627\u0644\u0639\u0631\u0628\u064a\u0629', 'bad-\\ud800'])
guard.close()
"""
            env = os.environ | {
                "DAFREE_CONFIG_DIR": str(tmp_path),
                "QT_QPA_PLATFORM": "offscreen",
                "TMPDIR": directory,
                "TMP": directory,
                "TEMP": directory,
            }
            with qtbot.waitSignal(first.argumentsReceived, timeout=10_000) as forwarded:
                run_child(qtbot, script, env)
            assert forwarded.args == [arguments]
            second.close()
            assert not second.acquire()
            first.close()
            assert second.acquire()
        finally:
            second.close()
            first.close()


def test_second_launch_returns_without_another_window(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The public entry point passes arguments and exits before creating another window."""
    with TemporaryDirectory(prefix="da-") as directory:
        monkeypatch.setattr(QDir, "tempPath", lambda: directory)
        paths = paths_at(tmp_path)
        first = _SingleInstance(paths)
        script = """
from dafree.gui import app
def unexpected_window():
    raise AssertionError('second window was created')
app.create_main_window = unexpected_window
raise SystemExit(app.main(['folder']))
"""
        env = os.environ | {
            "DAFREE_CONFIG_DIR": str(tmp_path),
            "QT_QPA_PLATFORM": "offscreen",
            "TMPDIR": directory,
            "TMP": directory,
            "TEMP": directory,
        }
        try:
            assert first.acquire()
            with qtbot.waitSignal(first.argumentsReceived, timeout=5000) as forwarded:
                run_child(qtbot, script, env)
            assert forwarded.args == [["folder"]]
            assert not first.forward(["x" * (64 * 1024)])
        finally:
            first.close()


def test_first_window_retains_lossless_launch_arguments(
    qtbot: QtBot, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both initial and forwarded paths avoid Qt's QVariant string conversion."""
    window = MainWindow()
    qtbot.addWidget(window)
    initial, forwarded = ["initial-\ud800"], ["next-\udcff"]
    with TemporaryDirectory(prefix="da-") as directory:
        monkeypatch.setattr(QDir, "tempPath", lambda: directory)
        monkeypatch.setattr(bootstrap, "detect", lambda: paths_at(tmp_path))
        monkeypatch.setattr(bootstrap, "create_main_window", lambda: window)

        def event_loop() -> int:
            assert window._pending_launch_arguments == initial
            guards = [guard for guard in qapp.findChildren(_SingleInstance) if guard._owned]
            assert len(guards) == 1
            guards[0].argumentsReceived.emit(forwarded)
            assert window._pending_launch_arguments == forwarded
            return 0

        monkeypatch.setattr(QApplication, "exec", event_loop)
        assert bootstrap.main(initial) == 0
