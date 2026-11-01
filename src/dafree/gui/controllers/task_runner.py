"""Bounded background work with results delivered on the runner's Qt thread."""

from collections.abc import Callable
from typing import TypeVar

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from dafree.gui import _display_text

_T = TypeVar("_T")


class _Signals(QObject):
    finished = Signal(int, object, object)
    failed = Signal(int, object, str)


class _Task(QRunnable):
    def __init__(
        self, token: int, task_id: object, fn: Callable[[], object], signals: _Signals
    ) -> None:
        super().__init__()
        self._token, self._task_id, self._fn, self._signals = token, task_id, fn, signals

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as error:
            self._signals.failed.emit(self._token, self._task_id, _display_text(str(error)))
        else:
            self._signals.finished.emit(self._token, self._task_id, result)


class TaskRunner(QObject):
    """Run up to four callables concurrently and emit results on the owning thread."""

    finished = Signal(object, object)
    failed = Signal(object, str)

    def __init__(self, parent: QObject | None = None) -> None:
        """Create a pool whose lifetime belongs to this controller."""
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(4)
        self._next_token = 0
        self._pending: dict[int, _Signals] = {}

    @property
    def busy(self) -> bool:
        """Whether queued/running work still needs delivery on the owning GUI thread."""
        return bool(self._pending)

    def submit(self, fn: Callable[[], _T], *, task_id: object) -> None:
        """Queue a callable; task IDs are returned unchanged and need not be hashable."""
        token = self._next_token
        self._next_token += 1
        signals = _Signals(self)
        signals.finished.connect(self._finished)
        signals.failed.connect(self._failed)
        self._pending[token] = signals
        self._pool.start(_Task(token, task_id, fn, signals))

    @Slot(int, object, object)
    def _finished(self, token: int, task_id: object, result: object) -> None:
        self._pending.pop(token).deleteLater()
        self.finished.emit(task_id, result)

    @Slot(int, object, str)
    def _failed(self, token: int, task_id: object, message: str) -> None:
        self._pending.pop(token).deleteLater()
        self.failed.emit(task_id, message)
