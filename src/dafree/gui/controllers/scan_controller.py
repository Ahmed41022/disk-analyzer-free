"""Poll public native scan handles while startup and result collection run off the GUI thread."""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from time import monotonic
from typing import Literal, cast

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from dafree.api import Backend, ScanHandle, ScanRequest, ScanResult, start_scan
from dafree.gui import _display_text
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.i18n import _

_POLL_MS = 250
_PARTIAL_TICKS = 4
_PARTIAL_SECONDS = 1.0


@dataclass(frozen=True)
class _Job:
    owner: object
    generation: int
    stage: Literal["start", "result"]


class ScanController(QObject):
    """Own one scan, emitting copied progress and shared trees on the Qt thread."""

    started = Signal(object)
    progressChanged = Signal(object)
    issuesAdded = Signal(list)
    noticeReceived = Signal(object)
    partialTreeReady = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        runner: TaskRunner | None = None,
        backend: Backend | None = None,
    ) -> None:
        """Use an owned runner by default; inject shared runners or native test backends."""
        super().__init__(parent)
        self._runner = runner if runner is not None else TaskRunner(self)
        self._backend = backend
        self._runner.finished.connect(self._job_finished)
        self._runner.failed.connect(self._job_failed)
        self._owner = object()
        self._generation = 0
        self._handle: ScanHandle | None = None
        self._running = False
        self._paused = False
        self._cancel_requested = False
        self._finishing = False
        self._polling = False
        self._error: str | None = None
        self._ticks = 0
        self._last_partial = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._poll)

    @property
    def running(self) -> bool:
        """True from startup submission through final result delivery or failure cleanup."""
        return self._running

    def start(self, req: ScanRequest) -> None:
        """Snapshot a request and start asynchronously; concurrent starts are rejected."""
        if self._running:
            raise RuntimeError(_("A scan is already running."))
        request = deepcopy(req)
        self._generation += 1
        self._running = True
        self._paused = self._cancel_requested = self._finishing = False
        self._error = None
        self._ticks = 0
        self._last_partial = monotonic()
        job = _Job(self._owner, self._generation, "start")
        self.started.emit(req)
        # Native startup validates roots/volumes and can block on network filesystems.
        self._runner.submit(lambda: start_scan(request, backend=self._backend), task_id=job)

    def pause(self) -> None:
        """Pause between native reads, including a pause requested during startup."""
        if self._running and not self._cancel_requested and not self._finishing:
            self._paused = True
            if self._handle is not None:
                self._handle.pause()

    def resume(self) -> None:
        """Resume dispatch or clear a pause that was requested before the handle arrived."""
        if self._running and not self._cancel_requested and not self._finishing:
            self._paused = False
            if self._handle is not None:
                self._handle.resume()

    def cancel(self) -> None:
        """Request a partial result without blocking the GUI or stopping completion polling."""
        if self._running:
            self._cancel_requested = True
            if self._handle is not None:
                self._handle.cancel()

    def _owns(self, job: object) -> bool:
        return (
            isinstance(job, _Job)
            and job.owner is self._owner
            and job.generation == self._generation
        )

    def _drain(self, handle: ScanHandle) -> None:
        issues = handle.drain_issues(1000)
        if issues:
            self.issuesAdded.emit(issues)
        for notice in handle.drain_notices():
            self.noticeReceived.emit(notice)

    @Slot()
    def _poll(self) -> None:
        handle = self._handle
        if handle is None or self._finishing or self._polling:
            return
        self._polling = True
        try:
            self.progressChanged.emit(handle.progress())
            self._drain(handle)
            self._ticks += 1
            now = monotonic()
            if self._ticks % _PARTIAL_TICKS == 0 and now - self._last_partial >= _PARTIAL_SECONDS:
                self._last_partial = now
                tree = handle.partial_tree()
                if tree is not None:
                    self.partialTreeReady.emit(tree)
            if handle.wait(0):
                self._collect(handle)
        except Exception as error:
            # Cancel and consume in a worker before releasing an active handle:
            # its native destructor joins threads and must not run on the GUI path.
            self._error = _display_text(str(error))
            handle.cancel()
            self._collect(handle)
        finally:
            self._polling = False

    def _collect(self, handle: ScanHandle) -> None:
        if self._finishing:
            return
        self._finishing = True
        self._timer.stop()

        def result() -> ScanResult:
            while not handle.wait(_POLL_MS):
                pass
            return handle.take_result()

        self._runner.submit(result, task_id=_Job(self._owner, self._generation, "result"))

    @Slot(object, object)
    def _job_finished(self, task_id: object, value: object) -> None:
        if not self._owns(task_id):
            return
        job = cast(_Job, task_id)
        if job.stage == "start":
            handle = cast(ScanHandle, value)
            self._handle = handle
            if self._cancel_requested:
                handle.cancel()
            elif self._paused:
                handle.pause()
            self._timer.start()
            return
        active = self._handle
        if self._error is not None:
            self._fail(self._error)
            return
        if active is not None:
            try:
                self.progressChanged.emit(active.progress())
                self._drain(active)
            except Exception as error:
                self._fail(_display_text(str(error)))
                return
        self._handle = None
        self._running = False
        self.finished.emit(cast(ScanResult, value))

    @Slot(object, str)
    def _job_failed(self, task_id: object, message: str) -> None:
        if self._owns(task_id):
            self._fail(self._error if self._error is not None else message)

    def _fail(self, message: str) -> None:
        self._timer.stop()
        self._handle = None
        self._running = False
        logging.getLogger(__name__).error("Scan failed: %s", message)
        self.failed.emit(_display_text(message))
