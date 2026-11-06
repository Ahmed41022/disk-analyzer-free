"""Transactional shared preferences; future analysis services remain inactive."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal, cast

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from dafree import api
from dafree.gui import _display_text
from dafree.gui.theme.palette import ThemeController
from dafree.i18n import _
from dafree.paths import AppPaths
from dafree.settings import Settings, save_settings, validate_settings

_WINDOWS = sys.platform == "win32"
_U32_MAX = (1 << 32) - 1


@dataclass(frozen=True)
class _LanguageValue:
    """Keep an unknown stored language out of QString's lossy conversion path."""

    value: str


def _combo(parent: QWidget, choices: Sequence[tuple[str, object]], selected: object) -> QComboBox:
    combo = QComboBox(parent)
    for label, value in choices:
        combo.addItem(label, value)
    combo.setCurrentIndex(max(0, combo.findData(selected)))
    return combo


def _number(parent: QWidget, value: int, *, minimum: int = 0) -> QDoubleSpinBox:
    spin = QDoubleSpinBox(parent)
    spin.setDecimals(0)
    spin.setRange(minimum, _U32_MAX)
    if minimum == 0:
        spin.setSpecialValueText(_("Auto"))
    spin.setValue(value)
    return spin


class SettingsDialog(QDialog):
    """Save a validated candidate before applying preferences to the running session."""

    def __init__(
        self,
        settings: Settings,
        parent: QWidget | None = None,
        *,
        paths: AppPaths | None = None,
        theme_controller: ThemeController | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Settings"))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(820, 660)
        self._settings, self._initial, self._paths = settings, deepcopy(settings), paths
        self._initial_rule_text: dict[QPlainTextEdit, str] = {}
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("Settings require a QApplication")
        self._theme_controller = theme_controller or ThemeController(app, settings.theme, self)
        layout = QVBoxLayout(self)
        self.pages = QTabWidget(self)
        self.pages.setAccessibleName(_("Settings pages"))
        layout.addWidget(self.pages, 1)
        self._general()
        self._scanning()
        self._duplicates()
        self._placeholder(
            _("Shortcuts"), _("Keyboard shortcut customization is not available yet.")
        )
        self._placeholder(_("Scheduled scans"), _("Scan scheduling is not available yet."))
        self._advanced()
        self.error = QLabel("", self)
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _page(self, title: str) -> QFormLayout:
        body = QWidget(self.pages)
        form = QFormLayout(body)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        scroll = QScrollArea(self.pages)
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.pages.addTab(scroll, title)
        return form

    @staticmethod
    def _row(form: QFormLayout, caption: str, widget: QWidget) -> None:
        widget.setAccessibleName(caption)
        form.addRow(caption, widget)

    def _general(self) -> None:
        form = self._page(_("General"))
        choices: list[tuple[str, object]] = [
            (_("System language"), None),
            (_("English"), "en_US"),
            (_("Arabic"), "ar"),
            (_("German"), "de"),
        ]
        known_language = self._initial.locale in {None, "en_US", "ar", "de"}
        self.language = _combo(self, choices, self._initial.locale if known_language else None)
        if not known_language and self._initial.locale is not None:
            self.language.addItem(
                _("Current language: {locale}").format(locale=_display_text(self._initial.locale)),
                _LanguageValue(self._initial.locale),
            )
            self.language.setCurrentIndex(self.language.count() - 1)
        self._row(form, _("Language"), self.language)
        notice = QLabel(_("Language changes take effect after restarting the application."), self)
        notice.setWordWrap(True)
        form.addRow(notice)
        self.theme = _combo(
            self,
            [(_("System"), "system"), (_("Light"), "light"), (_("Dark"), "dark")],
            self._initial.theme,
        )
        self._row(form, _("Theme"), self.theme)
        self.units = _combo(
            self,
            list(
                zip(
                    (
                        _("Automatic"),
                        _("Bytes"),
                        _("Kilobytes"),
                        _("Megabytes"),
                        _("Gigabytes"),
                        _("Terabytes"),
                        _("Petabytes"),
                        _("Exabytes"),
                    ),
                    api.UnitMode,
                    strict=True,
                )
            ),
            self._initial.units,
        )
        self._row(form, _("Units"), self.units)
        self.unit_system = _combo(
            self,
            [
                (_("Binary (KB, MB)"), api.UnitSystem.TRADITIONAL),
                (_("IEC (KiB, MiB)"), api.UnitSystem.IEC),
                (_("SI (kB, MB)"), api.UnitSystem.SI),
            ],
            self._initial.unit_style.system,
        )
        self._row(form, _("Unit labels"), self.unit_system)
        self.density = _combo(
            self,
            [(_("Compact"), "compact"), (_("Comfortable"), "comfortable")],
            self._initial.row_density,
        )
        self._row(form, _("Row density"), self.density)

    def _scanning(self) -> None:
        form = self._page(_("Scanning defaults"))
        previous = self._initial.default_scan
        choices = [(_("Auto"), api.ScanMode.AUTO), (_("Walk"), api.ScanMode.WALK)]
        if _WINDOWS or previous.mode == api.ScanMode.MFT:
            choices.append((_("MFT (Windows only)"), api.ScanMode.MFT))
        self.mode = _combo(self, choices, previous.mode)
        self._row(form, _("Mode"), self.mode)
        self.follow_symlinks = QCheckBox(_("Follow symbolic links"), self)
        self.cross_filesystems = QCheckBox(_("Cross filesystems"), self)
        self.hidden = QCheckBox(_("Exclude hidden entries"), self)
        self.system = QCheckBox(_("Exclude system entries"), self)
        self.include_ads = QCheckBox(_("Include alternate data streams (Windows only)"), self)
        for widget, value in (
            (self.follow_symlinks, previous.follow_symlinks),
            (self.cross_filesystems, previous.cross_filesystems),
            (self.hidden, previous.exclude.hidden),
            (self.system, previous.exclude.system),
            (self.include_ads, previous.include_ads),
        ):
            widget.setChecked(value)
            form.addRow(widget)
        self.include_ads.setEnabled(_WINDOWS)
        self.owner = _combo(
            self,
            [
                (_("Off"), api.OwnerMode.OFF),
                (_("Lazy"), api.OwnerMode.LAZY),
                (_("Eager"), api.OwnerMode.EAGER),
            ],
            previous.owner,
        )
        self._row(form, _("Owner lookup"), self.owner)
        self.hardlinks = _combo(
            self,
            [
                (_("Count once"), api.HardlinkMode.DEDUP),
                (_("Count every link"), api.HardlinkMode.COUNT_ALL),
            ],
            previous.hardlinks,
        )
        self._row(form, _("Hard links"), self.hardlinks)
        self.globs, self.exclude_paths = QPlainTextEdit(self), QPlainTextEdit(self)
        for editor, values, caption in (
            (self.globs, previous.exclude.globs, _("Excluded globs, one per line")),
            (self.exclude_paths, previous.exclude.paths, _("Excluded paths, one per line")),
        ):
            editor.setPlainText(_display_text("\n".join(values)))
            self._initial_rule_text[editor] = editor.toPlainText()
            editor.setMaximumHeight(100)
            self._row(form, caption, editor)

    def _duplicates(self) -> None:
        form = self._page(_("Duplicates defaults"))
        notice = QLabel(
            _("These defaults will be used when duplicate analysis is available."), self
        )
        notice.setWordWrap(True)
        form.addRow(notice)
        previous = self._initial.dupes
        self.min_size = QLineEdit(str(previous.min_size), self)
        self.max_size = QLineEdit("" if previous.max_size is None else str(previous.max_size), self)
        self._row(form, _("Minimum size (bytes or size with unit)"), self.min_size)
        self._row(form, _("Maximum size (blank for no limit)"), self.max_size)
        self.algorithm = _combo(
            self,
            [(_("BLAKE3"), "blake3"), (_("XXH3 128"), "xxh3_128"), (_("SHA-256"), "sha256")],
            previous.algo,
        )
        self._row(form, _("Hash algorithm"), self.algorithm)
        self.partial_bytes = _number(self, previous.partial_bytes, minimum=1)
        self._row(form, _("Prefix bytes"), self.partial_bytes)
        self.dupe_hidden = QCheckBox(_("Include hidden files"), self)
        self.same_volume = QCheckBox(_("Keep duplicate groups on the same volume"), self)
        self.verify_bytes = QCheckBox(_("Verify matching bytes"), self)
        for widget, value in (
            (self.dupe_hidden, previous.include_hidden),
            (self.same_volume, previous.same_volume_only),
            (self.verify_bytes, previous.verify_bytes),
        ):
            widget.setChecked(value)
            form.addRow(widget)
        self.io_threads = _number(self, previous.io_threads)
        self._row(form, _("Duplicate I/O threads"), self.io_threads)
        self.dupe_filter = QLineEdit(_display_text(previous.filter or ""), self)
        self._initial_filter_text = self.dupe_filter.text()
        self._row(form, _("Duplicate filter"), self.dupe_filter)

    def _placeholder(self, title: str, message: str) -> None:
        form = self._page(title)
        label = QLabel(message, self)
        label.setWordWrap(True)
        form.addRow(label)

    def _advanced(self) -> None:
        form = self._page(_("Advanced"))
        self.metafiles = QCheckBox(_("Show NTFS metafiles (Windows only)"), self)
        self.metafiles.setChecked(self._initial.show_ntfs_metafiles)
        self.metafiles.setEnabled(_WINDOWS)
        form.addRow(self.metafiles)
        self.threads = _number(self, self._initial.default_scan.threads)
        self._row(form, _("Scan threads"), self.threads)
        self.log_folder = QPushButton(_("Open log folder"), self)
        self.log_folder.setAutoDefault(False)
        self.log_folder.setEnabled(self._paths is not None)
        self.log_folder.clicked.connect(self._open_logs)
        form.addRow(self.log_folder)

    def _open_logs(self) -> None:
        if self._paths is None:
            return
        if not self._paths.logs.is_dir() or not QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self._paths.logs))
        ):
            self.error.setText(_("Could not open the log folder."))
        else:
            self.error.clear()

    def _lines(self, editor: QPlainTextEdit, previous: list[str]) -> list[str]:
        text = editor.toPlainText()
        if text == self._initial_rule_text[editor]:
            return previous.copy()
        return [line for line in text.splitlines() if line]

    def _candidate(self) -> Settings:
        # Preserve unrelated preferences changed by workers while the dialog was open.
        candidate = deepcopy(self._settings)
        candidate.theme = cast(Literal["system", "light", "dark"], self.theme.currentData())
        language = self.language.currentData()
        candidate.locale = language.value if isinstance(language, _LanguageValue) else language
        candidate.units = api.UnitMode(self.units.currentData())
        candidate.unit_style = api.UnitStyle(
            api.UnitSystem(self.unit_system.currentData()),
            self._settings.unit_style.decimal_separator,
        )
        candidate.row_density = cast(Literal["compact", "comfortable"], self.density.currentData())
        scan = candidate.default_scan
        scan.mode = api.ScanMode(self.mode.currentData())
        scan.threads = int(self.threads.value())
        scan.follow_symlinks, scan.cross_filesystems = (
            self.follow_symlinks.isChecked(),
            self.cross_filesystems.isChecked(),
        )
        scan.owner = api.OwnerMode(self.owner.currentData())
        scan.hardlinks = api.HardlinkMode(self.hardlinks.currentData())
        scan.exclude.hidden, scan.exclude.system = self.hidden.isChecked(), self.system.isChecked()
        scan.exclude.globs = self._lines(self.globs, self._initial.default_scan.exclude.globs)
        scan.exclude.paths = self._lines(
            self.exclude_paths, self._initial.default_scan.exclude.paths
        )
        if _WINDOWS:
            scan.include_ads = self.include_ads.isChecked()
            candidate.show_ntfs_metafiles = scan.show_ntfs_metafiles = self.metafiles.isChecked()
        dupes = candidate.dupes
        dupes.min_size = api.parse_size(self.min_size.text(), candidate.unit_style)
        dupes.max_size = (
            api.parse_size(self.max_size.text(), candidate.unit_style)
            if self.max_size.text().strip()
            else None
        )
        dupes.algo = cast(Literal["blake3", "xxh3_128", "sha256"], self.algorithm.currentData())
        dupes.partial_bytes, dupes.io_threads = (
            int(self.partial_bytes.value()),
            int(self.io_threads.value()),
        )
        dupes.include_hidden, dupes.same_volume_only = (
            self.dupe_hidden.isChecked(),
            self.same_volume.isChecked(),
        )
        dupes.verify_bytes = self.verify_bytes.isChecked()
        text = self.dupe_filter.text()
        dupes.filter = (
            self._initial.dupes.filter if text == self._initial_filter_text else text or None
        )
        return validate_settings(candidate)

    def accept(self) -> None:
        """Persist before changing live state; failures leave the original preferences intact."""
        try:
            candidate = self._candidate()
            if self._paths is not None:
                save_settings(candidate, self._paths)
        except (OSError, ValueError) as error:
            self.error.setText(
                _("Could not save settings: {error}").format(error=_display_text(str(error)))
            )
            return
        for name in (
            "theme",
            "locale",
            "units",
            "unit_style",
            "row_density",
            "default_scan",
            "dupes",
            "show_ntfs_metafiles",
        ):
            setattr(self._settings, name, getattr(candidate, name))
        self._theme_controller.set_theme(candidate.theme)
        super().accept()
