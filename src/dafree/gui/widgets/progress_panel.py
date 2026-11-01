"""Scan metrics, smoothed throughput, shared actions, and accessible lifecycle status."""

from __future__ import annotations

from PySide6.QtCore import QLocale, Qt, QTime
from PySide6.QtGui import QAccessible, QAccessibleEvent, QAction
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QToolButton, QVBoxLayout, QWidget

from dafree import api
from dafree.gui import _display_text
from dafree.gui.controllers.scan_controller import ScanController
from dafree.gui.widgets.breadcrumb import ElidedPathLabel
from dafree.i18n import _
from dafree.settings import Settings

_ALPHA = 0.3
_BAR_MAX = 1000


def elapsed_text(milliseconds: int) -> str:
    """Format monotonic scan duration using locale digits, retaining complete days."""
    days, seconds = divmod(milliseconds // 1000, 24 * 60 * 60)
    time = QLocale().toString(QTime(0, 0).addSecs(seconds), "HH:mm:ss")
    return _("{days}d {time}").format(days=QLocale().toString(days), time=time) if days else time


class ProgressPanel(QWidget):
    """Show copied progress and control one existing scanner without another timer."""

    def __init__(
        self,
        controller: ScanController,
        settings: Settings,
        parent: QWidget | None = None,
        *,
        pause_action: QAction | None = None,
        cancel_action: QAction | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller, self._settings = controller, settings
        self._rate: float | None = None
        self._last_files = self._last_ms = 0
        self._cancelled = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        metrics = QHBoxLayout()
        self.files = QLabel(self)
        self.dirs = QLabel(self)
        self.bytes = QLabel(self)
        self.rate_label = QLabel(self)
        self.elapsed = QLabel(self)
        for label in (self.files, self.dirs, self.bytes, self.rate_label, self.elapsed):
            label.setTextFormat(Qt.TextFormat.PlainText)
            metrics.addWidget(label)
        layout.addLayout(metrics)
        self.current_path = ElidedPathLabel(self)
        layout.addWidget(self.current_path)
        controls = QHBoxLayout()
        self.status = QLabel(_("Ready"), self)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        controls.addWidget(self.status)
        self.partial_badge = QLabel(_("Partial results"), self)
        self.partial_badge.setAccessibleName(_("Partial results"))
        controls.addWidget(self.partial_badge)
        self.bar = QProgressBar(self)
        self.bar.setAccessibleName(_("Scan progress"))
        controls.addWidget(self.bar, 1)
        self.pause_action = pause_action if pause_action is not None else QAction(_("Pause"), self)
        self.pause_action.setCheckable(True)
        self.cancel_action = (
            cancel_action if cancel_action is not None else QAction(_("Cancel"), self)
        )
        self.pause_button, self.cancel_button = QToolButton(self), QToolButton(self)
        for button, action in (
            (self.pause_button, self.pause_action),
            (self.cancel_button, self.cancel_action),
        ):
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setAccessibleName(action.text())
            controls.addWidget(button)
        layout.addLayout(controls)
        self.pause_action.triggered.connect(self._pause)
        self.cancel_action.triggered.connect(self._cancel)
        controller.started.connect(self._started)
        controller.progressChanged.connect(self._progress)
        controller.finished.connect(self._finished)
        controller.failed.connect(self._failed)
        self._set_totals(0, 0, 0, 0)
        self.rate_label.setText(_("Rate: —"))
        self.partial_badge.hide()
        self.pause_action.setEnabled(False)
        self.cancel_action.setEnabled(False)
        self.hide()

    @property
    def rate(self) -> float | None:
        """Current files/second EMA, absent until the first positive-duration sample."""
        return self._rate

    def _set_totals(self, files: int, dirs: int, size: int, elapsed: int) -> None:
        locale = QLocale()
        self.files.setText(_("Files: {count}").format(count=locale.toString(files)))
        self.dirs.setText(_("Folders: {count}").format(count=locale.toString(dirs)))
        self.bytes.setText(
            _("Total: {size}").format(
                size=api.format_size(size, self._settings.units, self._settings.unit_style)
            )
        )
        self.elapsed.setText(_("Elapsed: {time}").format(time=elapsed_text(elapsed)))

    def _set_status(self, message: str) -> None:
        self.status.setText(message)
        self.status.setAccessibleName(message)

    def _announce(self, message: str) -> None:
        self._set_status(message)
        QAccessible.updateAccessibility(QAccessibleEvent(self.status, QAccessible.Event.Alert))

    def _started(self, request: api.ScanRequest) -> None:
        self._rate = None
        self._last_files = self._last_ms = 0
        self._cancelled = False
        self._set_totals(0, 0, 0, 0)
        self.rate_label.setText(_("Rate: —"))
        self.current_path.set_path("")
        self.partial_badge.hide()
        self.bar.setRange(0, 0)
        self.pause_action.setChecked(False)
        self._pause_text()
        self.pause_action.setEnabled(True)
        self.cancel_action.setEnabled(True)
        self.status.setToolTip("")
        self.show()
        self._announce(_("Scan started."))

    def _progress(self, progress: api.ScanProgress) -> None:
        self._set_totals(progress.files, progress.dirs, progress.bytes, progress.elapsed_ms)
        self.current_path.set_path(progress.current)
        if progress.elapsed_ms < self._last_ms or progress.files < self._last_files:
            self._rate = None
            self._last_files, self._last_ms = progress.files, progress.elapsed_ms
        elif progress.elapsed_ms > self._last_ms:
            instantaneous = (
                (progress.files - self._last_files) * 1000 / (progress.elapsed_ms - self._last_ms)
            )
            self._rate = (
                instantaneous
                if self._rate is None
                else _ALPHA * instantaneous + (1 - _ALPHA) * self._rate
            )
            self._last_files, self._last_ms = progress.files, progress.elapsed_ms
        self.rate_label.setText(
            _("Rate: —")
            if self._rate is None
            else _("{rate} files/s").format(rate=QLocale().toString(self._rate, "f", 1))
        )
        if progress.est_total is None:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, _BAR_MAX)
            processed = progress.files + progress.dirs
            self.bar.setValue(
                min(_BAR_MAX, processed * _BAR_MAX // progress.est_total)
                if progress.est_total
                else 0
            )
        if progress.state == api.ScanState.PAUSED and not self._cancelled:
            self.pause_action.setChecked(True)
            self._pause_text()
            self._set_status(_("Paused"))
        elif progress.state == api.ScanState.RUNNING and not self._cancelled:
            self._set_status(_("Paused") if self.pause_action.isChecked() else _("Scanning…"))
        elif progress.state == api.ScanState.FINALIZING:
            self.pause_action.setEnabled(False)
            self.cancel_action.setEnabled(False)
            self._set_status(_("Finishing scan…"))

    def _pause_text(self) -> None:
        caption = _("Resume") if self.pause_action.isChecked() else _("Pause")
        self.pause_action.setText(caption)
        self.pause_button.setAccessibleName(caption)

    def _pause(self, checked: bool) -> None:
        self._controller.pause() if checked else self._controller.resume()
        self._pause_text()
        self._set_status(_("Paused") if checked else _("Scanning…"))

    def _cancel(self) -> None:
        self._cancelled = True
        self._controller.cancel()
        self.partial_badge.show()
        self.pause_action.setEnabled(False)
        self.cancel_action.setEnabled(False)
        self._set_status(_("Cancellation requested…"))

    def _stop_actions(self) -> None:
        self.pause_action.setEnabled(False)
        self.cancel_action.setEnabled(False)
        self.pause_action.setChecked(False)
        self._pause_text()

    def _finished(self, result: api.ScanResult) -> None:
        summary = result.summary
        self._set_totals(summary.files, summary.dirs, summary.bytes, summary.elapsed_ms)
        self._cancelled = summary.cancelled
        self.partial_badge.setVisible(summary.cancelled)
        self._stop_actions()
        previous = self.bar.value()
        self.bar.setRange(0, _BAR_MAX)
        self.bar.setValue(max(0, previous) if summary.cancelled else _BAR_MAX)
        self._announce(
            _("Scan cancelled. Partial results are available.")
            if summary.cancelled
            else _("Scan complete.")
        )

    def _failed(self, message: str) -> None:
        self._stop_actions()
        self.partial_badge.hide()
        self.bar.setRange(0, _BAR_MAX)
        self.bar.setValue(0)
        self.status.setToolTip(_display_text(message))
        self._announce(_("Scan failed."))
