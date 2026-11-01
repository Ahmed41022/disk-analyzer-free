"""Human properties, background owner lookup, raw clipboard paths, and window actions."""

import os
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from importlib.util import find_spec
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, QLocale, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMenu

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, TreeBuilder, make_mock_backend
from dafree.gui.controllers.task_runner import TaskRunner
from dafree.gui.dialogs.properties_dialog import PropertiesDialog, flag_labels
from dafree.gui.main_window import MainWindow
from dafree.gui.views.tree_tab import TreeTab
from dafree.i18n import current_locale, setup
from dafree.settings import Settings

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def cleanup(qapp: QApplication) -> Iterator[None]:
    previous, language = QLocale(), current_locale()
    QLocale.setDefault(QLocale("en_US"))
    setup("en_US")
    yield
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QLocale.setDefault(previous)
    setup(language)


@pytest.fixture
def properties(qtbot: QtBot) -> Iterator[Callable[..., PropertiesDialog]]:
    runners = []

    def create(tree: api.Tree, node: int, settings: Settings | None = None) -> PropertiesDialog:
        runner = TaskRunner()
        runners.append(runner)
        dialog = PropertiesDialog(tree, node, settings or Settings(), runner)
        qtbot.addWidget(dialog)
        dialog.show()
        return dialog

    yield create
    for runner in runners:
        qtbot.waitUntil(lambda runner=runner: not runner.busy, timeout=5000)
        runner.deleteLater()


def tree_at(root: Path):
    backend = make_mock_backend(
        MockSpec(
            [
                MockEntry(root, api.EntryKind.DIR),
                MockEntry(root / "a.bin", size=100, alloc=200, ino_lo=42, nlink=2, owner_uid=42),
                MockEntry(
                    root / "b.bin",
                    size=100,
                    alloc=200,
                    ino_lo=42,
                    nlink=2,
                    owner_uid=42,
                    hidden=True,
                    sparse=True,
                    compressed=True,
                    cloud=True,
                ),
            ],
            owner_names={42: "test-owner"},
        )
    )
    tree = api.scan(api.ScanRequest([root], threads=1), backend=backend).tree
    return tree, backend


def test_flags_render_human_labels(properties, tmp_path: Path, qtbot: QtBot) -> None:
    """Real native hard-link/accounting flags become readable badges, with allocated ratio."""
    tree, backend = tree_at(tmp_path)
    node = tree.find_path(tmp_path / "b.bin")
    assert node is not None
    dialog = properties(tree, node)
    labels = [badge.text() for badge in dialog.badges]
    assert "Hard link — not counted in totals" in labels
    assert {"Hidden", "Sparse", "Compressed", "Cloud placeholder"} <= set(labels)
    assert dialog.values["type"].text() == "File"
    assert "200.0%" in dialog.values["allocated"].text()
    assert dialog.values["size"].text() == api.format_size(100)
    assert all(dialog.values[key].text() == "—" for key in ("mtime", "btime", "atime"))
    qtbot.waitUntil(lambda: dialog.values["owner"].text() == "test-owner")
    assert backend.owner_resolution_calls == 1
    assert all(flag.name not in labels for flag in api.NodeFlags)


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        (api.NodeFlags.DIR, "Folder"),
        (api.NodeFlags.SYMLINK, "Symbolic link"),
        (api.NodeFlags.REPARSE, "Reparse point"),
        (api.NodeFlags.MOUNT_POINT, "Mount point"),
        (api.NodeFlags.HARDLINK_DUP, "Hard link — not counted in totals"),
        (api.NodeFlags.HIDDEN, "Hidden"),
        (api.NodeFlags.SYSTEM, "System"),
        (api.NodeFlags.ACCESS_DENIED, "Access denied"),
        (api.NodeFlags.PARTIAL, "Partial scan"),
        (api.NodeFlags.SPARSE, "Sparse"),
        (api.NodeFlags.COMPRESSED, "Compressed"),
        (api.NodeFlags.CLOUD_PLACEHOLDER, "Cloud placeholder"),
        (api.NodeFlags.EXCLUDED, "Excluded from totals"),
        (api.NodeFlags.ERROR, "Scan error"),
        (api.NodeFlags.ALLOC_UNRELIABLE, "Allocated size is approximate"),
        (api.NodeFlags.SYNTHETIC, "Combined scan"),
    ],
)
def test_every_flag_has_human_text(flag: api.NodeFlags, expected: str) -> None:
    """Every public bit has a translated label; no numeric masks leak into the UI."""
    assert flag_labels(flag) == [expected]


def test_owner_resolution_is_background_and_only_on_open(
    properties, tmp_path: Path, qtbot: QtBot, monkeypatch
) -> None:
    """Opening properties requests the selected owner without blocking Qt events."""
    tree, backend = tree_at(tmp_path)
    assert backend.owner_resolution_calls == 0
    original = api.Tree.resolve_owners
    entered, release = threading.Event(), threading.Event()

    def resolve(self, ids):
        if self is not tree:
            return original(self, ids)
        entered.set()
        assert release.wait(5)
        original(self, ids)

    monkeypatch.setattr(api.Tree, "resolve_owners", resolve)
    try:
        node = tree.find_path(tmp_path / "a.bin")
        assert node is not None
        dialog = properties(tree, node)
        qtbot.waitUntil(entered.is_set)
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        qtbot.waitUntil(lambda: bool(heartbeat))
        assert dialog.values["owner"].text() == "Resolving…"
    finally:
        release.set()
    qtbot.waitUntil(lambda: dialog.values["owner"].text() == "test-owner")


def test_timestamp_volume_and_approximate_metadata(properties, tmp_path: Path, monkeypatch) -> None:
    """Captured metadata uses local dates, longest matching mount, and explicit approximation."""
    tree = TreeBuilder.flat(tmp_path / "root", 1)
    native_node, metadata = tree.node(1), tree.meta()
    info = replace(
        native_node,
        flags=native_node.flags | api.NodeFlags.ALLOC_UNRELIABLE,
        mtime=1_700_000_000,
        btime=1_600_000_000,
        atime=None,
    )
    original_node, original_meta = api.Tree.node, api.Tree.meta
    monkeypatch.setattr(
        api.Tree, "node", lambda self, node: info if self is tree else original_node(self, node)
    )
    volumes = (
        api.VolumeInfo(str(tmp_path), fs_type="outer"),
        api.VolumeInfo(
            str(tmp_path / "root"), fs_type="inner", label="Recorded", total=1000, free=200
        ),
    )
    monkeypatch.setattr(
        api.Tree,
        "meta",
        lambda self: replace(metadata, volumes=volumes) if self is tree else original_meta(self),
    )
    dialog = properties(tree, 1)
    assert dialog.values["allocated"].text().startswith("≈")
    assert dialog.values["mtime"].text() != "—" and dialog.values["btime"].text() != "—"
    assert dialog.values["atime"].text() == "—"
    assert "Filesystem: inner" in dialog.values["volume"].text()
    assert "Recorded" in dialog.values["volume"].text()
    assert "outer" not in dialog.values["volume"].text()


def test_copy_path_preserves_native_mime(properties, tmp_path: Path) -> None:
    """QString-safe clipboard text accompanies a lossless payload for undecodable native names."""
    root = tmp_path / "bad-\udcff"
    tree = TreeBuilder.flat(root, 1)
    dialog = properties(tree, 1)
    dialog.copy.click()
    mime = QApplication.clipboard().mimeData()
    assert mime.text().endswith(r"bad-\udcff")
    assert bytes(mime.data("application/x-dafree-native-path")).decode(
        "utf-8", "surrogatepass"
    ) == str(root)


def test_owner_failure_keeps_properties_available(
    properties, tmp_path: Path, qtbot: QtBot, monkeypatch
) -> None:
    """A failed optional owner lookup does not hide basic properties or break the dialog."""
    tree = TreeBuilder.flat(tmp_path, 1)

    original = api.Tree.resolve_owners

    def fail(self, ids):
        if self is tree:
            raise RuntimeError("identity lookup failed")
        return original(self, ids)

    monkeypatch.setattr(api.Tree, "resolve_owners", fail)
    dialog = properties(tree, 1)
    qtbot.waitUntil(lambda: dialog.values["owner"].text() == "Unavailable")
    assert dialog.values["owner"].toolTip() == "identity lookup failed"
    assert dialog.values["path"].text() == str(tmp_path)


def test_enter_and_context_menu_open_properties(qtbot: QtBot, tmp_path: Path) -> None:
    """Tree Enter and the Properties-only context menu reach the same read-only dialog."""
    tree = TreeBuilder.flat(tmp_path, 2)
    window = MainWindow(volume_provider=lambda: [])

    def finish(widget):
        window.close()
        qtbot.waitUntil(lambda: not window.runner.busy, timeout=5000)

    qtbot.addWidget(window, before_close_func=finish)
    window.show()
    window._tree_ready(tree)
    page = window._pages["tree"]
    assert isinstance(page, TreeTab)
    qtbot.waitUntil(lambda: page.table is not None)
    table = page.table
    table.setCurrentIndex(table.tree_model.index(0, 0))
    qtbot.keyClick(table, Qt.Key.Key_Return)
    assert len(window._properties_dialogs) == 1
    dialog = window._properties_dialogs[0]
    qtbot.waitUntil(lambda: not window.runner.busy)
    dialog.reject()
    assert window._properties_dialogs == []
    qtbot.keyClick(table, Qt.Key.Key_Menu)
    menu = window.findChild(QMenu, "tree.context-menu")
    assert menu is not None and [action.text() for action in menu.actions()] == ["Properties"]
    menu.actions()[0].trigger()
    assert len(window._properties_dialogs) == 1
    menu.close()
    qtbot.waitUntil(lambda: not window.runner.busy)
