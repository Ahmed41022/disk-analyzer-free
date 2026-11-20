"""Background age reports with editable intervals and scoped Find handoff."""

from __future__ import annotations

import re
from dataclasses import dataclass
from time import time
from typing import cast

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QMouseEvent, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from dafree import api
from dafree.gui import _display_text
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.widgets.bar_chart import BarChart
from dafree.gui.widgets.breadcrumb import Breadcrumb
from dafree.i18n import _
from dafree.settings import Settings

_DAY = 86_400
_UNIT_SECONDS = {"d": _DAY, "w": 7 * _DAY, "m": 30 * _DAY, "y": 365 * _DAY}
_MAX_CUTOFFS = 14
_U64_MAX = (1 << 64) - 1
_MAX_DIGITS = len(str(_U64_MAX))
_DURATION = re.compile(r"([0-9]+)\s*([dwmy])", re.IGNORECASE)
_DEFAULT_BUCKETS = "30d,90d,180d,1y,2y,5y"


def _parse_cutoffs(text: str) -> tuple[tuple[str, int], ...]:
    parts = text.split(",")
    if not 1 <= len(parts) <= _MAX_CUTOFFS:
        raise ValueError(_("Use between one and 14 age cutoffs."))
    cutoffs = []
    previous = 0
    for part in parts:
        match = _DURATION.fullmatch(part.strip())
        if match is None:
            raise ValueError(
                _("Age cutoffs need a positive whole number followed by d, w, m, or y.")
            )
        digits = match[1].lstrip("0") or "0"
        if len(digits) > _MAX_DIGITS:
            raise ValueError(_("Age cutoffs must fit in unsigned 64-bit seconds."))
        number, unit = int(digits), match[2].lower()
        seconds = number * _UNIT_SECONDS[unit]
        if seconds > _U64_MAX:
            raise ValueError(_("Age cutoffs must fit in unsigned 64-bit seconds."))
        if seconds <= previous:
            raise ValueError(_("Age cutoffs must be positive and strictly increasing."))
        cutoffs.append((f"{number}{unit}", seconds))
        previous = seconds
    return tuple(cutoffs)


def _make_buckets(cutoffs: tuple[tuple[str, int], ...]) -> tuple[api.AgeBucket, ...]:
    result = []
    for index, (label, seconds) in enumerate(cutoffs):
        caption = (
            _("<{age}").format(age=label)
            if index == 0
            else _("{lower} to {upper}").format(lower=cutoffs[index - 1][0], upper=label)
        )
        result.append(api.AgeBucket(caption, seconds))
    result.append(api.AgeBucket(_("{age} and older").format(age=cutoffs[-1][0]), None))
    return tuple(result)


def parse_buckets(text: str) -> tuple[api.AgeBucket, ...]:
    """Parse one to fourteen increasing age cutoffs and append an unbounded interval.

    Accept positive whole-number days, weeks, 30-day months, or 365-day years,
    separated by commas. Cutoffs must fit unsigned 64-bit seconds. The fourteen
    cutoff limit leaves room for fifteen known intervals and one Unknown chart row.
    Invalid input raises ``ValueError`` with a localized explanation.
    """
    return _make_buckets(_parse_cutoffs(text))


@dataclass(frozen=True)
class _AgeJob:
    owner: object
    generation: int


@dataclass(frozen=True)
class _AgeReport:
    stats: tuple[api.AgeStat, ...]
    created_available: bool


def _prepare(
    tree: api.Tree,
    scope: int,
    field: api.TimeField,
    buckets: tuple[api.AgeBucket, ...],
    now: int,
) -> _AgeReport:
    stats = tuple(api.age_histogram(tree, scope, field, buckets, now))
    created = (
        stats
        if field == api.TimeField.CREATED
        else api.age_histogram(tree, scope, api.TimeField.CREATED, (api.AgeBucket("", None),), now)
    )
    known_count = len(buckets) if field == api.TimeField.CREATED else 1
    available = any(row.bucket < known_count and row.files > 0 for row in created)
    return _AgeReport(stats, available)


def _unknown_note() -> str:
    return _("Unknown timestamps cannot be opened as a time query.")


class _AgeChart(BarChart):
    """Map rendered positive bars back to their age intervals, independently of node IDs."""

    bucketActivated = Signal(int)

    def __init__(self, settings: Settings, title: str, parent: QWidget) -> None:
        self._bucket_ids: tuple[int, ...] = ()
        self._known_buckets = 0
        super().__init__(settings, parent)
        self._title = title
        self.setAccessibleName(title)

    def set_stats(
        self, stats: tuple[api.AgeStat, ...], *, count_values: bool, known_buckets: int
    ) -> None:
        """Keep original bucket indexes while omitting values too small to render."""
        values = [(row, row.files if count_values else row.size) for row in stats]
        positive = [(row, value) for row, value in values if value > 0]
        self._bucket_ids = tuple(row.bucket for row, _value in positive)
        self._known_buckets = known_buckets
        self.set_data(
            [api.ChartSlice(row.label, value) for row, value in positive],
            count_values=count_values,
        )

    def _select(self, index: int) -> None:
        super()._select(index)
        if self._bucket_ids[index] >= self._known_buckets:
            self.setAccessibleDescription(
                _("{label}: {note}").format(label=self.slice_labels()[index], note=_unknown_note())
            )

    def _activate(self, index: int) -> None:
        self._select(index)
        if self._bucket_ids[index] < self._known_buckets:
            self.bucketActivated.emit(self._bucket_ids[index])
        else:
            self.setToolTip(_unknown_note())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Explain why Unknown bars have no matching Find time predicate."""
        super().mouseMoveEvent(event)
        index = self._hit(event.position())
        if index is not None and self._bucket_ids[index] >= self._known_buckets:
            self.setToolTip(
                _("{label}: {note}").format(label=self.slice_labels()[index], note=_unknown_note())
            )


class AgeTab(QWidget):
    """Prepare immutable age reports with coalesced scan, scope, and option requests."""

    ready = Signal()
    findRequested = Signal(object, object, str)

    def __init__(
        self, settings: Settings, runner: TaskRunner, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._runner = runner
        self._owner, self._generation = object(), 0
        self._building = self._pending = False
        self._cutoffs = _parse_cutoffs(_DEFAULT_BUCKETS)
        self._bucket_spec = _make_buckets(self._cutoffs)
        self._bucket_error: str | None = None
        self._created_available: bool | None = None
        self.tree: api.Tree | None = None
        self.scope: int | None = None
        layout = QVBoxLayout(self)
        self.field = QComboBox(self)
        self.field.setAccessibleName(_("Time field"))
        for caption, field in (
            (_("Modified"), api.TimeField.MODIFIED),
            (_("Created"), api.TimeField.CREATED),
            (_("Accessed"), api.TimeField.ACCESSED),
        ):
            self.field.addItem(caption, field)
        self.buckets = QLineEdit(_DEFAULT_BUCKETS, self)
        self.buckets.setAccessibleName(_("Age buckets"))
        self.buckets.setToolTip(
            _("Separate cutoffs with commas. A month is 30 days; a year is 365 days.")
        )
        self.apply = QPushButton(_("Apply"), self)
        self.apply.setAccessibleName(_("Apply age buckets"))
        controls = QHBoxLayout()
        controls.addWidget(self.buckets, 1)
        controls.addWidget(self.apply)
        form = QFormLayout()
        form.addRow(_("Time field"), self.field)
        form.addRow(_("Age buckets"), controls)
        layout.addLayout(form)
        self.breadcrumb = Breadcrumb(self, allow_synthetic_root=True)
        self.breadcrumb.nodeActivated.connect(self.select_node)
        layout.addWidget(self.breadcrumb)
        self.message = QLabel(_("Choose a target to scan."), self)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.access_note = QLabel(
            _("Access times can be unreliable with noatime/relatime or NTFS DisableLastAccess."),
            self,
        )
        self.access_note.setWordWrap(True)
        self.access_note.setTextFormat(Qt.TextFormat.PlainText)
        self.access_note.hide()
        layout.addWidget(self.access_note)
        self._build_charts(settings, layout)
        self.size_chart.bucketActivated.connect(self._activate_bucket)
        self.count_chart.bucketActivated.connect(self._activate_bucket)
        self.apply.clicked.connect(self._apply_buckets)
        self.buckets.returnPressed.connect(self._apply_buckets)
        self.field.currentIndexChanged.connect(self._field_changed)
        runner.finished.connect(self._finished)
        runner.failed.connect(self._failed)
        self._set_created_available(None)

    def _build_charts(self, settings: Settings, layout: QVBoxLayout) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        size_scroll, count_scroll = QScrollArea(splitter), QScrollArea(splitter)
        for scroll in (size_scroll, count_scroll):
            scroll.setWidgetResizable(True)
            scroll.setMinimumWidth(240)
        self.size_chart = _AgeChart(settings, _("Size by age"), size_scroll)
        self.count_chart = _AgeChart(settings, _("Files by age"), count_scroll)
        size_scroll.setWidget(self.size_chart)
        count_scroll.setWidget(self.count_chart)
        splitter.setSizes([480, 480])
        layout.addWidget(splitter, 1)

    def clear(self) -> None:
        """Release charts and reject work still associated with the previous scan."""
        self._generation += 1
        self._pending = False
        self.tree = None
        self.scope = None
        self.size_chart.set_stats((), count_values=False, known_buckets=0)
        self.count_chart.set_stats((), count_values=True, known_buckets=0)
        self.breadcrumb.clear()
        self._set_created_available(None)
        self.message.setText(_("Choose a target to scan."))
        self.message.show()

    def set_tree(self, tree: api.Tree) -> None:
        """Start a new scan at its single target or combined synthetic root."""
        if tree is self.tree:
            return
        self.clear()
        self.tree = tree
        roots = tree.roots()
        self.select_node(roots[0] if len(roots) == 1 else 0)

    def select_node(self, node: int) -> None:
        """Analyze the selected directory, using a selected file's parent as scope."""
        if self.tree is None:
            return
        info = self.tree.node(node)
        scope = node if info.flags & api.NodeFlags.DIR else (self.tree.parent(node) or 0)
        if scope != self.scope:
            self.scope = scope
            self._set_created_available(None)
            self.breadcrumb.set_node(self.tree, scope)
            self._schedule()

    def refresh_settings(self) -> None:
        """Reformat existing chart values without recalculating the histogram."""
        self.size_chart.refresh_settings()
        self.count_chart.refresh_settings()

    def _set_created_available(self, available: bool | None) -> None:
        self._created_available = available
        index = self.field.findData(api.TimeField.CREATED)
        cast(QStandardItemModel, self.field.model()).item(index).setEnabled(available is True)
        explanation = (
            _("Checking whether creation times are available for this selection.")
            if available is None
            else _("Creation times are unavailable for this selection.")
            if not available
            else ""
        )
        self.field.setItemData(index, explanation, Qt.ItemDataRole.ToolTipRole)

    def _apply_buckets(self) -> None:
        try:
            cutoffs = _parse_cutoffs(self.buckets.text())
        except ValueError as error:
            self._bucket_error = str(error)
            self.message.setText(self._bucket_error)
            self.message.show()
            return
        self._bucket_error = None
        self._cutoffs, self._bucket_spec = cutoffs, _make_buckets(cutoffs)
        self._schedule()

    def _field_changed(self) -> None:
        self.access_note.setVisible(self.field.currentData() == api.TimeField.ACCESSED)
        self._schedule()

    def _schedule(self) -> None:
        self._generation += 1
        self._pending = self.tree is not None
        self.size_chart.set_stats((), count_values=False, known_buckets=0)
        self.count_chart.set_stats((), count_values=True, known_buckets=0)
        if self._pending:
            self.message.setText(_("Preparing age analysis…"))
            self.message.show()
        self._submit_pending()

    def _submit_pending(self) -> None:
        if self._building or not self._pending or self.tree is None or self.scope is None:
            return
        self._pending = False
        self._building = True
        job = _AgeJob(self._owner, self._generation)
        tree, scope, field, buckets, now = (
            self.tree,
            self.scope,
            self.field.currentData(),
            self._bucket_spec,
            int(time()),
        )
        self._runner.submit(lambda: _prepare(tree, scope, field, buckets, now), task_id=job)

    def _finished(self, job: object, result: object) -> None:
        if not isinstance(job, _AgeJob) or job.owner is not self._owner:
            return
        self._building = False
        if job.generation == self._generation and isinstance(result, _AgeReport):
            self._set_created_available(result.created_available)
            if self.field.currentData() == api.TimeField.CREATED and not result.created_available:
                with QSignalBlocker(self.field):
                    self.field.setCurrentIndex(self.field.findData(api.TimeField.MODIFIED))
                self._schedule()
            else:
                self.size_chart.set_stats(
                    result.stats, count_values=False, known_buckets=len(self._bucket_spec)
                )
                self.count_chart.set_stats(
                    result.stats, count_values=True, known_buckets=len(self._bucket_spec)
                )
                self.message.setText(self._bucket_error or _("No data for this selection."))
                self.message.setVisible(
                    self._bucket_error is not None or not any(row.files for row in result.stats)
                )
                self.ready.emit()
        self._submit_pending()

    def _failed(self, job: object, message: str) -> None:
        if isinstance(job, _AgeJob) and job.owner is self._owner:
            self._building = False
            if job.generation == self._generation:
                self.message.setText(
                    _("Could not prepare age analysis: {error}").format(
                        error=_display_text(message)
                    )
                )
                self.message.show()
            self._submit_pending()

    def _activate_bucket(self, bucket: int) -> None:
        if self.tree is None or self.scope is None or not 0 <= bucket < len(self._bucket_spec):
            return
        field = {
            api.TimeField.MODIFIED: "modified",
            api.TimeField.CREATED: "created",
            api.TimeField.ACCESSED: "accessed",
        }[self.field.currentData()]
        terms = ["type:file"]
        if bucket > 0:
            terms.append(f"{field}>={self._cutoffs[bucket - 1][0]}")
        if bucket < len(self._cutoffs):
            terms.append(f"{field}<{self._cutoffs[bucket][0]}")
        self.findRequested.emit(self.tree, self.scope, " ".join(terms))
