"""Qt startup, local instance forwarding, and application-owned diagnostic logs."""

from __future__ import annotations

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
from types import TracebackType

from PySide6.QtCore import (
    QDir,
    QLibraryInfo,
    QLocale,
    QLockFile,
    QObject,
    Qt,
    QTranslator,
    Signal,
    Slot,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from dafree import __version__
from dafree.gui import _display_text
from dafree.gui.main_window import create_main_window
from dafree.gui.theme.palette import apply_palette
from dafree.i18n import _, is_rtl, setup
from dafree.paths import AppPaths, detect
from dafree.settings import Settings, load_settings

_STATE_NAME = "dafree.application"
_MAX_MESSAGE = 64 * 1024
_LOG_FILES = 7
_LOG_NAME = re.compile(r"dafree-[0-9]{8}\.log")


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
    """Hold the data-directory lock and forward bounded JSON arguments over local IPC."""

    argumentsReceived = Signal(object)

    def __init__(self, paths: AppPaths, parent: QObject | None = None) -> None:
        super().__init__(parent)
        if paths.data.is_symlink() or paths.data.is_junction():
            raise OSError("application data directory must not be a link")
        paths.data.mkdir(parents=True, exist_ok=True)
        self._lock = QLockFile(str(paths.data / "instance.lock"))
        self._lock.setStaleLockTime(0)  # A running application must not expire by file age.
        identity = os.path.normcase(str(paths.data.absolute())).encode("utf-8", "surrogatepass")
        name = "dafree-" + hashlib.sha256(identity).hexdigest()[:16]
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
    window = create_main_window()

    def activate(arguments: list[str]) -> None:
        window._pending_launch_arguments = arguments.copy()
        window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
        window.show()
        window.raise_()
        window.activateWindow()

    guard.argumentsReceived.connect(activate)
    window._pending_launch_arguments = arguments.copy()
    window.show()
    try:
        return QApplication.exec()
    finally:
        guard.close()
