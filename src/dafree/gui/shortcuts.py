"""Stable action identifiers, platform defaults, and conflict-safe shortcut binding."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QWidget

from dafree.i18n import _


@dataclass(frozen=True)
class ShortcutSpec:
    """A persistent action identifier with its translated caption and platform default."""

    id: str
    label: str
    default: QKeySequence


def shortcut_specs() -> tuple[ShortcutSpec, ...]:
    """Build platform-aware defaults after QApplication and gettext initialization."""
    # Qt PortableText's Ctrl maps to Command on Apple platforms, including custom keys.
    # https://doc.qt.io/qt-6/qkeysequence.html
    preferences = QKeySequence(QKeySequence.StandardKey.Preferences)
    return (
        ShortcutSpec("new_scan", _("New scan"), QKeySequence(QKeySequence.StandardKey.New)),
        ShortcutSpec("refresh_selection", _("Refresh selection"), QKeySequence("F5")),
        ShortcutSpec("focus_query", _("Focus query"), QKeySequence(QKeySequence.StandardKey.Find)),
        ShortcutSpec("copy_path", _("Copy path"), QKeySequence(QKeySequence.StandardKey.Copy)),
        ShortcutSpec("delete_trash", _("Delete to Trash"), QKeySequence("Del")),
        ShortcutSpec("delete_permanently", _("Delete permanently"), QKeySequence("Shift+Del")),
        ShortcutSpec(
            "save_snapshot", _("Save snapshot"), QKeySequence(QKeySequence.StandardKey.Save)
        ),
        ShortcutSpec(
            "open_snapshot", _("Open snapshot"), QKeySequence(QKeySequence.StandardKey.Open)
        ),
        ShortcutSpec("export", _("Export"), QKeySequence("Ctrl+E")),
        *(
            ShortcutSpec(
                f"switch_tab_{i}",
                _("Switch to tab {number}").format(number=i),
                QKeySequence(f"Ctrl+{i}"),
            )
            for i in range(1, 10)
        ),
        ShortcutSpec(
            "settings",
            _("Settings"),
            preferences if not preferences.isEmpty() else QKeySequence("Ctrl+,"),
        ),
        ShortcutSpec("cancel_scan", _("Cancel scan"), QKeySequence("Esc")),
        ShortcutSpec("help", _("Help"), QKeySequence("F1")),
    )


def effective_shortcuts(overrides: Mapping[str, str]) -> dict[str, QKeySequence]:
    """Resolve known actions; an explicit empty override disables a shortcut."""
    return {
        spec.id: QKeySequence.fromString(
            overrides[spec.id], QKeySequence.SequenceFormat.PortableText
        )
        if spec.id in overrides
        else spec.default
        for spec in shortcut_specs()
    }


def shortcut_conflicts(sequences: Mapping[str, QKeySequence]) -> list[tuple[str, str]]:
    """Find exact and multi-chord prefix collisions, ignoring unassigned shortcuts."""
    assigned = [(key, value) for key, value in sequences.items() if not value.isEmpty()]
    return [
        (left, right)
        for i, (left, a) in enumerate(assigned)
        for right, b in assigned[i + 1 :]
        if a.matches(b) != QKeySequence.SequenceMatch.NoMatch
        or b.matches(a) != QKeySequence.SequenceMatch.NoMatch
    ]


class ShortcutRegistry(QObject):
    """Own window actions while suppressing every ambiguous stored binding."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.actions: dict[str, QAction] = {}

    def register(
        self,
        action_id: str,
        owner: QWidget,
        handler: Callable[[], object] | None = None,
        *,
        action: QAction | None = None,
        scoped: bool = False,
    ) -> QAction:
        """Bind an existing action or create one; unimplemented handlers remain disabled."""
        if action_id in self.actions:
            raise ValueError(f"Duplicate shortcut action: {action_id}")
        spec = next(spec for spec in shortcut_specs() if spec.id == action_id)
        existing = action is not None
        action = action if action is not None else QAction(spec.label, owner)
        action.setShortcutContext(
            Qt.ShortcutContext.WidgetWithChildrenShortcut
            if scoped
            else Qt.ShortcutContext.WindowShortcut
        )
        owner.addAction(action)
        if handler is not None:
            action.triggered.connect(lambda checked=False: handler())
        elif not existing:
            action.setEnabled(False)
        self.actions[action_id] = action
        return action

    def apply(self, overrides: Mapping[str, str]) -> None:
        """Apply committed settings and leave conflicting shortcuts unbound until repaired."""
        sequences = effective_shortcuts(overrides)
        conflicts = {key for pair in shortcut_conflicts(sequences) for key in pair}
        for key, action in self.actions.items():
            action.setShortcut(QKeySequence() if key in conflicts else sequences[key])
