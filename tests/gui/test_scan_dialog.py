"""Target validation, keyboard behavior, deferred modes, and persisted scan defaults."""

# ruff: noqa: PLR2004 -- fixture option values and target counts are contract assertions.

import os
import threading
from collections.abc import Callable, Iterator
from importlib.util import find_spec
from pathlib import Path

import pytest

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog
from pytestqt.qtbot import QtBot

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.dialogs import scan_dialog as module
from dafree.gui.dialogs.scan_dialog import ScanDialog
from dafree.gui.main_window import MainWindow
from dafree.paths import AppPaths
from dafree.settings import ExcludeRulesModel, ScanOptionsModel, Settings, load_settings

pytestmark = pytest.mark.gui


@pytest.fixture
def dialog_factory(qtbot: QtBot) -> Iterator[Callable[..., ScanDialog]]:
    runners: list[TaskRunner] = []

    def create(**kwargs) -> ScanDialog:
        runner = TaskRunner()
        runners.append(runner)
        kwargs.setdefault("volume_provider", lambda: [])
        settings = kwargs.pop("settings", Settings())
        dialog = ScanDialog(settings, runner, **kwargs)
        qtbot.addWidget(dialog)
        dialog.show()
        return dialog

    yield create
    for runner in runners:
        qtbot.waitUntil(lambda runner=runner: not runner.busy, timeout=5000)
        runner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_empty_targets_disables_start(dialog_factory) -> None:
    """Empty acceptance cannot modify settings or produce a scan request."""
    dialog = dialog_factory()
    assert not dialog.start.isEnabled()
    dialog.accept()
    assert dialog.request is None and dialog.result() == QDialog.DialogCode.Rejected


def test_multiple_folders_added(dialog_factory, tmp_path: Path, qtbot: QtBot, monkeypatch) -> None:
    """Repeated standard folder picks append separate validated roots; duplicates are ignored."""
    folders = [tmp_path / "one", tmp_path / "two"]
    for folder in folders:
        folder.mkdir()
    choices = iter(map(str, folders))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: next(choices))
    dialog = dialog_factory()
    dialog.add_folder.click()
    dialog.add_folder.click()
    qtbot.waitUntil(dialog.start.isEnabled)
    assert set(dialog.target_paths()) == set(map(str, folders))
    dialog.add_target(str(folders[0]))
    assert dialog.targets.count() == 2
    dialog.targets.selectAll()
    dialog.remove.click()
    assert not dialog.start.isEnabled() and dialog.target_paths() == []


@pytest.mark.parametrize("windows", [False, True])
def test_mft_option_only_on_windows(dialog_factory, monkeypatch, windows: bool) -> None:
    """Only Windows lists MFT, explicitly disabled while the native fast engine is paused."""
    monkeypatch.setattr(module, "_WINDOWS", windows)

    def unavailable():
        raise api.Unsupported("Unavailable")

    dialog = dialog_factory(elevation_provider=unavailable)
    index = dialog.mode.findData(api.ScanMode.MFT)
    assert (index >= 0) is windows
    if windows:
        assert not dialog.mode.model().item(index).isEnabled()
        assert dialog.restart.isVisible() and not dialog.restart.isEnabled()
    else:
        assert dialog.restart.isHidden()


def test_options_persist_to_settings(dialog_factory, tmp_path: Path, qtbot: QtBot) -> None:
    """Acceptance saves every exposed option and preserves unexposed policies independently."""
    paths = AppPaths(
        tmp_path / "config", tmp_path / "data", tmp_path / "logs", tmp_path / "snapshots", False
    )
    settings = Settings(
        default_scan=ScanOptionsModel(owner=api.OwnerMode.OFF, hardlinks=api.HardlinkMode.COUNT_ALL)
    )
    dialog = dialog_factory(settings=settings, paths=paths, targets=[str(tmp_path)])
    qtbot.waitUntil(dialog.start.isEnabled)
    dialog.threads.setValue(3)
    dialog.mode.setCurrentIndex(dialog.mode.findData(api.ScanMode.WALK))
    for checkbox in (
        dialog.follow_symlinks,
        dialog.cross_filesystems,
        dialog.hidden,
        dialog.system,
    ):
        checkbox.setChecked(True)
    dialog.globs.setPlainText("*.tmp\n*.cache")
    dialog.exclude_paths.setPlainText(str(tmp_path / "excluded"))
    qtbot.keyClick(dialog.start, Qt.Key.Key_Return)
    assert dialog.result() == QDialog.DialogCode.Accepted
    options = load_settings(paths).default_scan
    assert options == settings.default_scan
    assert options.targets == [str(tmp_path)] and options.threads == 3
    assert (
        options.mode == api.ScanMode.WALK and options.follow_symlinks and options.cross_filesystems
    )
    assert options.exclude == ExcludeRulesModel(
        [str(tmp_path / "excluded")], ["*.tmp", "*.cache"], True, True
    )
    assert options.owner == api.OwnerMode.OFF and options.hardlinks == api.HardlinkMode.COUNT_ALL
    assert dialog.request is not None
    assert dialog.request.threads == 3 and dialog.request.exclude.globs == ["*.tmp", "*.cache"]
    options.targets.append("independent")
    settings.default_scan.targets.append("separate")
    assert dialog.request.targets == [str(tmp_path)]


def test_typed_path_validation(dialog_factory, tmp_path: Path, qtbot: QtBot) -> None:
    """Nonexistent roots and files are rejected; typed directories can then be accepted."""
    regular = tmp_path / "file"
    regular.write_text("test", encoding="utf-8")
    dialog = dialog_factory()
    for path in (tmp_path / "missing", regular):
        dialog.path.setText(str(path))
        dialog.add_path.click()
        qtbot.waitUntil(lambda: not dialog._pending)
        assert "unavailable" in dialog.error.text() and not dialog.start.isEnabled()
    dialog.path.setText(str(tmp_path))
    dialog.add_path.click()
    qtbot.waitUntil(dialog.start.isEnabled)
    assert dialog.target_paths() == [str(tmp_path)]


def test_volume_multiselection(dialog_factory, tmp_path: Path, qtbot: QtBot) -> None:
    """Selected mounted roots are added as a group, retaining their native paths."""
    folders = [tmp_path / "one", tmp_path / "two"]
    for folder in folders:
        folder.mkdir()
    volumes = [api.VolumeInfo(str(folder), total=100, free=50) for folder in folders]
    dialog = dialog_factory(volume_provider=lambda: volumes)
    qtbot.waitUntil(lambda: not dialog.volumes.loading)
    dialog.volumes.list.selectAll()
    dialog.add_volumes.click()
    qtbot.waitUntil(dialog.start.isEnabled)
    assert set(dialog.target_paths()) == set(map(str, folders))


def test_validation_does_not_block_qt(
    dialog_factory, tmp_path: Path, qtbot: QtBot, monkeypatch
) -> None:
    """A slow path check keeps Qt responsive and disables Start until validation finishes."""
    entered, release = threading.Event(), threading.Event()

    def check(path):
        entered.set()
        assert release.wait(5)
        return True

    monkeypatch.setattr(module, "_directory", check)
    dialog = dialog_factory()
    try:
        dialog.add_target(str(tmp_path))
        qtbot.waitUntil(entered.is_set)
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        qtbot.waitUntil(lambda: bool(heartbeat))
        assert not dialog.start.isEnabled()
    finally:
        release.set()
    qtbot.waitUntil(dialog.start.isEnabled)


def test_escape_does_not_persist(dialog_factory, tmp_path: Path, qtbot: QtBot) -> None:
    """Rejecting a configured request leaves shared defaults untouched."""
    settings = Settings()
    dialog = dialog_factory(settings=settings, targets=[str(tmp_path)])
    qtbot.waitUntil(dialog.start.isEnabled)
    dialog.threads.setValue(8)
    qtbot.keyClick(dialog, Qt.Key.Key_Escape)
    assert dialog.result() == QDialog.DialogCode.Rejected and dialog.request is None
    assert settings.default_scan == ScanOptionsModel()


def test_unchanged_exclusions_remain_lossless(dialog_factory, tmp_path: Path, qtbot: QtBot) -> None:
    """Display escaping and multiline editors do not rewrite untouched stored patterns/paths."""
    rules = ExcludeRulesModel(
        paths=[str(tmp_path / "bad-\udcff"), "line\nbreak"], globs=["bad-\udcff*"]
    )
    settings = Settings(default_scan=ScanOptionsModel(exclude=rules))
    dialog = dialog_factory(settings=settings, targets=[str(tmp_path)])
    qtbot.waitUntil(dialog.start.isEnabled)
    dialog.accept()
    assert dialog.request is not None
    assert (
        dialog.request.exclude.paths == rules.paths and dialog.request.exclude.globs == rules.globs
    )


def test_save_failure_keeps_dialog_open(
    dialog_factory, tmp_path: Path, qtbot: QtBot, monkeypatch
) -> None:
    """A failed profile write cannot start a scan or mutate shared defaults."""
    paths = AppPaths(tmp_path, tmp_path, tmp_path, tmp_path, False)
    settings = Settings()
    dialog = dialog_factory(settings=settings, paths=paths, targets=[str(tmp_path)])
    qtbot.waitUntil(dialog.start.isEnabled)

    def fail(*args):
        raise OSError("test write failure")

    monkeypatch.setattr(module, "save_settings", fail)
    dialog.accept()
    assert dialog.request is None and dialog.isVisible()
    assert settings.default_scan == ScanOptionsModel()
    assert "test write failure" in dialog.error.text()


def test_main_window_acceptance_starts_native_scan(qtbot: QtBot, tmp_path: Path) -> None:
    """The toolbar opens one dialog; explicit acceptance starts the owned native controller."""
    backend = make_mock_backend(
        MockSpec([MockEntry(tmp_path, api.EntryKind.DIR), MockEntry(tmp_path / "one", size=1)])
    )
    window = MainWindow(volume_provider=lambda: [], scan_backend=backend)

    def finish(widget):
        window.close()
        qtbot.waitUntil(
            lambda: not window.runner.busy and not window.controller.running, timeout=5000
        )

    qtbot.addWidget(window, before_close_func=finish)
    window.show()
    window.open_scan_dialog([str(tmp_path)])
    dialog = window._scan_dialog
    assert dialog is not None and not window.controller.running
    window.open_scan_dialog([str(tmp_path)])
    assert window._scan_dialog is dialog
    qtbot.waitUntil(dialog.start.isEnabled)
    with qtbot.waitSignal(window.controller.finished, timeout=5000):
        dialog.accept()
    assert window._scan_dialog is None
    qtbot.waitUntil(lambda: not window.runner.busy)
    window.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_enter_starts_and_restores_defaults(dialog_factory, tmp_path: Path, qtbot: QtBot) -> None:
    """Enter in a path field accepts the existing roots; defaults reappear on the next dialog."""
    settings = Settings(default_scan=ScanOptionsModel(targets=[str(tmp_path)], threads=4))
    dialog = dialog_factory(settings=settings)
    qtbot.waitUntil(dialog.start.isEnabled)
    assert dialog.threads.value() == 4
    dialog.path.setFocus()
    qtbot.keyClick(dialog.path, Qt.Key.Key_Return)
    assert dialog.request is not None and dialog.request.targets == [str(tmp_path)]
    assert dialog.request.threads == 4


def test_relaunch_contract_preserves_targets(
    dialog_factory, tmp_path: Path, qtbot: QtBot, monkeypatch
) -> None:
    """The platform seam forwards targets and quits only after successful relaunch."""

    monkeypatch.setattr(module, "_WINDOWS", True)
    calls = []
    quits = []
    monkeypatch.setattr(QApplication, "quit", lambda: quits.append(True))
    dialog = dialog_factory(
        targets=[str(tmp_path)],
        elevation_provider=lambda: False,
        relaunch=calls.append,
    )
    qtbot.waitUntil(dialog.start.isEnabled)
    dialog.restart.click()
    assert calls == [[str(tmp_path)]] and quits == [True]


def test_thread_control_preserves_full_saved_range(dialog_factory) -> None:
    """The integer-valued control cannot truncate the public uint32 settings range."""
    dialog = dialog_factory(settings=Settings(default_scan=ScanOptionsModel(threads=(1 << 32) - 1)))
    assert dialog.threads.decimals() == 0 and dialog.threads.value() == (1 << 32) - 1
