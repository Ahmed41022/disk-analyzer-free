"""Qt startup, local instance forwarding, and application-owned diagnostic logs."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import threading
import traceback
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import NoReturn, cast

from PySide6.QtCore import (
    QCoreApplication,
    QDir,
    QEvent,
    QEventLoop,
    QLibraryInfo,
    QLocale,
    QLockFile,
    QObject,
    Qt,
    QTimer,
    QTranslator,
    Signal,
    Slot,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from dafree import __version__, api
from dafree.gui import _display_text
from dafree.gui.main_window import MainWindow, create_main_window
from dafree.gui.theme.palette import apply_palette
from dafree.gui.views.tree_tab import TreeTab
from dafree.i18n import _, is_rtl, setup
from dafree.paths import AppPaths, detect
from dafree.settings import Settings, load_settings

_STATE_NAME = "dafree.application"
_MAX_MESSAGE = 64 * 1024
_LOG_FILES = 7
_LOG_NAME = re.compile(r"dafree-[0-9]{8}\.log")
_SELF_TEST_TIMEOUT_MS = 60_000


class _SelfTestParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


def _close_app_state(app: QApplication) -> None:
    state = app.findChild(_ApplicationState, _STATE_NAME)
    if state is not None:
        state.close()
        state.setParent(None)
        state.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _self_test_row(target: Path, result: api.ScanResult, page: TreeTab) -> int:
    """Verify the actual first model row and return its unformatted byte size."""
    if page.table is None or not page.table.tree_model.rowCount():
        raise ValueError("Tree model has no first row")
    model = page.table.tree_model
    node = model.node_at(0)
    root_path = result.tree.path(node)
    displayed = model.index(0, 0).data()
    # The existing root-row contract displays the full path. Verify that
    # presentation before comparing its basename against the requested DIR name.
    if root_path != str(target) or displayed != _display_text(root_path):
        raise ValueError("First tree row does not represent the requested directory")
    if Path(root_path).name != target.name:
        raise ValueError("First tree row has an unexpected directory name")
    if result.summary.cancelled or result.summary.issues.total:
        raise ValueError("Self-test scan was cancelled or reported filesystem issues")
    return result.tree.node(node).size


def _run_self_test(target: Path, expected_size: int, paths: AppPaths) -> dict[str, object]:
    """Exercise real scan/controller/model delivery with isolated, disposable preferences."""
    settings = Settings(locale="en_US", theme="light")
    app = build_app([sys.argv[0]], paths, settings)
    window = MainWindow(paths=paths, settings=settings, volume_provider=lambda: [])
    page = cast(TreeTab, window._pages["tree"])
    loop = QEventLoop()
    window.closed.connect(loop.quit)
    report: dict[str, object] = {
        "ok": False,
        "name": target.name,
        "size": None,
        "expected_size": expected_size,
        "error": "Self-test did not complete",
    }
    result: api.ScanResult | None = None
    finished = False
    timer = QTimer(window)
    timer.setSingleShot(True)

    def finish(error: str | None) -> None:
        nonlocal finished
        if finished:
            return
        finished = True
        timer.stop()
        report.update(ok=error is None, error=error)
        window.close()

    def inspect_row() -> None:
        if finished or result is None or page.tree is not result.tree or page.table is None:
            return
        try:
            size = _self_test_row(target, result, page)
            report["size"] = size
            if size != expected_size or result.summary.bytes != expected_size:
                raise ValueError("Tree size does not match the expected byte count")
        except Exception as error:
            finish(str(error))
        else:
            finish(None)

    def scanned(value: api.ScanResult) -> None:
        nonlocal result
        result = value
        inspect_row()

    window.controller.finished.connect(scanned)
    window.controller.failed.connect(finish)
    window.runner.failed.connect(lambda job, message: finish(message))
    page.ready.connect(inspect_row)
    timer.timeout.connect(lambda: finish("Self-test timed out"))
    window.show()
    request = api.ScanRequest(
        [target], mode=api.ScanMode.WALK, threads=2, follow_symlinks=False, cross_filesystems=False
    )
    QTimer.singleShot(0, lambda: window.start_scan(request))
    timer.start(_SELF_TEST_TIMEOUT_MS)
    try:
        loop.exec()
        return report
    finally:
        window.deleteLater()
        _close_app_state(app)


def _self_test(arguments: list[str]) -> int:
    """Emit exactly one machine-readable result without using normal settings or IPC."""
    report: dict[str, object] = {
        "ok": False,
        "name": None,
        "size": None,
        "expected_size": None,
        "error": None,
    }
    try:
        parser = _SelfTestParser(add_help=False)
        parser.add_argument("--self-test", required=True)
        parser.add_argument("--expect-size", required=True)
        options = parser.parse_args(arguments)
        # Normalize lexically; resolve() would follow links before validation.
        target = Path(os.path.abspath(options.self_test))  # noqa: PTH100
        report["name"] = target.name
        expected = int(options.expect_size)
        if not 0 <= expected <= (1 << 64) - 1:
            raise ValueError("Expected size must be an unsigned 64-bit byte count")
        report["expected_size"] = expected
        if target.is_symlink() or target.is_junction() or not target.is_dir():
            raise ValueError("Self-test target must be an existing directory, not a link")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        with TemporaryDirectory(prefix="dafree-self-test-") as directory:
            root = Path(directory)
            paths = AppPaths(root / "config", root / "data", root / "logs", root / "snaps", False)
            report = _run_self_test(target, expected, paths)
    except Exception as error:
        report.update(ok=False, error=str(error))
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["ok"] else 1


def _log_handler(paths: AppPaths) -> logging.FileHandler:
    """Open today's log and retain seven dated, application-owned regular files."""
    if any(path.is_symlink() or path.is_junction() for path in (paths.data, paths.logs)):
        raise OSError("application log directory must not be a link")
    paths.logs.mkdir(parents=True, exist_ok=True)
    destination = paths.logs / f"dafree-{date.today():%Y%m%d}.log"
    if destination.is_symlink() or destination.is_junction():
        raise OSError("application log must not be a link")
    handler = logging.FileHandler(destination, encoding="utf-8", errors="backslashreplace")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    candidates = sorted(
        (
            path
            for path in paths.logs.iterdir()
            if _LOG_NAME.fullmatch(path.name)
            and not path.is_symlink()
            and not path.is_junction()
            and path.is_file()
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    # Retention is confined to generated app diagnostics, never scan targets.
    previous = [path for path in candidates if path != destination]
    for path in previous[_LOG_FILES - 1 :]:
        try:
            path.unlink()
        except OSError:
            logging.getLogger(__name__).warning("Could not rotate application log %s", path)
    return handler


class _ApplicationState(QObject):
    unhandled = Signal(str)

    def __init__(self, app: QApplication, paths: AppPaths) -> None:
        # Attach only after setup succeeds: a failed log open must not leave a
        # half-constructed QObject in the application's child tree.
        super().__init__()
        self.setObjectName(_STATE_NAME)
        self._handler = _log_handler(paths)
        self._logger = logging.getLogger("dafree")
        self._old_level = self._logger.level
        self._logger.setLevel(logging.INFO)
        self._logger.addHandler(self._handler)
        self._old_hook = sys.excepthook
        self._old_thread_hook = threading.excepthook
        self._dialogs: list[QMessageBox] = []
        self._closed = False
        self._translator = QTranslator(self)
        locale = QLocale()
        directory = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if self._translator.load(locale, "qtbase", "_", directory):
            app.installTranslator(self._translator)
        self.unhandled.connect(self._show_exception)
        sys.excepthook = self._exception
        threading.excepthook = self._thread_exception
        app.aboutToQuit.connect(self.close)
        self.setParent(app)

    def _exception(
        self, kind: type[BaseException], error: BaseException, trace: TracebackType | None
    ) -> None:
        self._logger.error("Uncaught exception", exc_info=(kind, error, trace))
        self.unhandled.emit(_display_text("".join(traceback.format_exception(kind, error, trace))))

    def _thread_exception(self, args: threading.ExceptHookArgs) -> None:
        error = args.exc_value or RuntimeError(_("A background thread terminated unexpectedly."))
        self._exception(type(error), error, args.exc_traceback)

    @Slot(str)
    def _show_exception(self, details: str) -> None:
        dialog = QMessageBox(QApplication.activeWindow())
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle(_("Unexpected error"))
        dialog.setText(
            _("An unexpected error occurred. Details were saved to the application log.")
        )
        dialog.setDetailedText(details)
        dialog.setStandardButtons(QMessageBox.StandardButton.Close)
        copy = dialog.addButton(_("Copy details"), QMessageBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(details))
        dialog.finished.connect(lambda _result: self._dialogs.remove(dialog))
        self._dialogs.append(dialog)
        dialog.open()

    @Slot()
    def close(self) -> None:
        """Restore only hooks installed by this bootstrap and close its own log handle."""
        if self._closed:
            return
        self._closed = True
        if sys.excepthook == self._exception:
            sys.excepthook = self._old_hook
        if threading.excepthook == self._thread_exception:
            threading.excepthook = self._old_thread_hook
        for dialog in self._dialogs.copy():
            dialog.close()
        app = QApplication.instance()
        if app is not None:
            app.removeTranslator(self._translator)
        self._logger.removeHandler(self._handler)
        self._handler.close()
        self._logger.setLevel(self._old_level)


class _SingleInstance(QObject):
    """Hold a data-directory lock per privilege level and forward bounded JSON arguments."""

    argumentsReceived = Signal(object)

    def __init__(
        self,
        paths: AppPaths,
        parent: QObject | None = None,
        *,
        elevated: bool | None = None,
    ) -> None:
        super().__init__(parent)
        if paths.data.is_symlink() or paths.data.is_junction():
            raise OSError("application data directory must not be a link")
        paths.data.mkdir(parents=True, exist_ok=True)
        if elevated is None:
            elevated = sys.platform == "win32" and api.platform.is_elevated()
        # An elevated replacement must not hand its roots back to the exiting ordinary process.
        suffix = "-admin" if elevated else ""
        self._lock = QLockFile(str(paths.data / f"instance{suffix}.lock"))
        self._lock.setStaleLockTime(0)  # A running application must not expire by file age.
        identity = os.path.normcase(str(paths.data.absolute())).encode("utf-8", "surrogatepass")
        name = "dafree-" + hashlib.sha256(identity).hexdigest()[:16] + suffix
        # Keep Unix socket names short even when the application data path is long.
        self._name = name if sys.platform == "win32" else str(Path(QDir.tempPath()) / name)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._connected)
        self._buffers: dict[QLocalSocket, bytearray] = {}
        self._owned = False

    def acquire(self) -> bool:
        """Try the lock without waiting; stale locks follow Qt's PID/host checks."""
        if not self._lock.tryLock(0):
            return False
        # Only the lock owner may remove its stale application socket endpoint.
        QLocalServer.removeServer(self._name)
        if not self._server.listen(self._name):
            self._lock.unlock()
            raise OSError(self._server.errorString())
        self._owned = True
        return True

    def forward(self, arguments: list[str]) -> bool:
        """Send one argument list to the first instance, without launching another window."""
        payload = json.dumps(arguments, ensure_ascii=True).encode("ascii") + b"\n"
        if len(payload) > _MAX_MESSAGE:
            return False
        socket = QLocalSocket(self)
        try:
            socket.connectToServer(self._name)
            if not socket.waitForConnected(1000) or socket.write(payload) != len(payload):
                return False
            if socket.bytesToWrite() and not socket.waitForBytesWritten(1000):
                return False
            if not socket.bytesAvailable() and not socket.waitForReadyRead(3000):
                return False
            return socket.readAll().data() == b"ok\n"
        finally:
            socket.disconnectFromServer()
            socket.deleteLater()

    @Slot()
    def _connected(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda socket=socket: self._consume(socket))
            socket.disconnected.connect(lambda socket=socket: self._disconnected(socket))
            self._consume(socket)

    def _disconnected(self, socket: QLocalSocket) -> None:
        self._buffers.pop(socket, None)
        socket.deleteLater()

    def _consume(self, socket: QLocalSocket) -> None:
        data = self._buffers.get(socket)
        if data is None:
            return
        data.extend(socket.readAll().data())
        if len(data) > _MAX_MESSAGE:
            socket.abort()
            return
        if b"\n" not in data:
            return
        try:
            arguments = json.loads(data.partition(b"\n")[0])
            if not isinstance(arguments, list) or not all(
                isinstance(arg, str) for arg in arguments
            ):
                raise ValueError("invalid local argument message")
        except (ValueError, UnicodeError):
            logging.getLogger(__name__).warning("Rejected malformed local argument message")
        else:
            self.argumentsReceived.emit(arguments)
            socket.write(b"ok\n")
        self._buffers.pop(socket, None)
        socket.disconnectFromServer()

    def close(self) -> None:
        """Release only this instance's server and lock."""
        if self._owned:
            self._server.close()
            self._lock.unlock()
            self._owned = False


def build_app(argv: list[str], paths: AppPaths, settings: Settings) -> QApplication:
    """Configure Fusion, initial theme, locale, Qt translators, and diagnostic handling."""
    existing = QApplication.instance()
    if existing is not None and not isinstance(existing, QApplication):
        raise RuntimeError("GUI startup requires a QApplication")
    app = existing if existing is not None else QApplication(argv)
    previous = app.findChild(_ApplicationState, _STATE_NAME)
    if previous is not None:
        previous.close()
        previous.setParent(None)
        previous.deleteLater()
    selected = setup(settings.locale)
    QLocale.setDefault(QLocale(selected))
    app.setApplicationName(_("Disk Analyzer Free"))
    app.setOrganizationName("Ahmed41022")
    app.setOrganizationDomain("io.github.Ahmed41022")
    app.setDesktopFileName("io.github.Ahmed41022.diskanalyzerfree")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setLayoutDirection(
        Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight
    )
    apply_palette(app, settings.theme)
    _ApplicationState(app, paths)
    return app


def main(argv: list[str] | None = None) -> int:
    """Launch one desktop instance; explicit argv contains arguments after the program name."""
    # Validate the optional runtime before reading configuration, including when
    # an embedding process has already cached this bootstrap module.
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    arguments = sys.argv[1:] if argv is None else argv
    if any(arg.split("=", maxsplit=1)[0] in {"--self-test", "--expect-size"} for arg in arguments):
        return _self_test(arguments)
    paths = detect()
    settings = load_settings(paths)
    app = build_app([sys.argv[0], *arguments], paths, settings)
    guard = _SingleInstance(paths, app)
    if not guard.acquire():
        if guard.forward(arguments):
            return 0
        QMessageBox.warning(
            app.activeWindow(),
            _("Disk Analyzer Free"),
            _("Could not pass arguments to the other instance."),
        )
        return 1
    window = create_main_window(paths=paths, settings=settings)
    if settings.window is not None and settings.window.maximized:
        window.showMaximized()

    def activate(arguments: list[str]) -> None:
        window.receive_arguments(arguments)
        window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
        window.show()
        window.raise_()
        window.activateWindow()

    guard.argumentsReceived.connect(activate)
    window.receive_arguments(arguments)
    window.show()
    try:
        return QApplication.exec()
    finally:
        guard.argumentsReceived.disconnect(activate)
        guard.close()
        if not window.close():
            # The main event loop may also have been quit externally. Keep
            # delivering cancellation/results until this window can close.
            shutdown = QEventLoop()
            window.closed.connect(shutdown.quit)
            shutdown.exec()
        window.deleteLater()
        _close_app_state(app)


if __name__ == "__main__":
    raise SystemExit(main())
