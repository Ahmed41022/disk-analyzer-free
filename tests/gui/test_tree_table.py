"""Tree table interaction, persistent columns, real delegate painting, and accessibility."""

# ruff: noqa: PLR2004 -- fixed row counts, column positions, and geometry are assertions.

import gc
import os
from collections.abc import Callable, Iterator
from importlib.util import find_spec
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtCore import QCoreApplication, QEvent, QRect, Qt
from PySide6.QtGui import QImage, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleOptionViewItem

from dafree import api
from dafree.api.testing import MockEntry, MockSpec, TreeBuilder, make_mock_backend
from dafree.gui.delegates import TextCache
from dafree.gui.delegates.name_delegate import NameDelegate
from dafree.gui.delegates.size_delegate import SizeDelegate
from dafree.gui.models.tree_model import TreeTableModel
from dafree.gui.widgets.tree_table import TreeTableView
from dafree.paths import AppPaths
from dafree.settings import ColumnId, Settings, load_settings

pytestmark = pytest.mark.gui
type TableFactory = Callable[..., TreeTableView]


@pytest.fixture
def make_table(qtbot: QtBot, tmp_path: Path) -> Iterator[TableFactory]:
    """Every real/synthetic path and persisted preference stays in this test root."""
    tables: list[TreeTableView] = []

    def create(settings: Settings | None = None, paths: AppPaths | None = None) -> TreeTableView:
        root = tmp_path / "tree"
        entries = [
            MockEntry(root, api.EntryKind.DIR),
            MockEntry(root / "folder", api.EntryKind.DIR),
            MockEntry(root / "folder/nested", api.EntryKind.DIR),
            MockEntry(root / "folder/nested/leaf.bin", size=7),
            MockEntry(root / "folder/child.bin", size=9),
        ] + [MockEntry(root / f"file{i}.bin", size=i + 1, owner_uid=42) for i in range(80)]
        tree = api.scan(
            api.ScanRequest([root]),
            backend=make_mock_backend(MockSpec(entries, owner_names={42: "Alice"})),
        ).tree
        model = TreeTableModel(api.TreeView(tree), list(ColumnId))
        table = TreeTableView(model, settings or Settings(), paths=paths)
        qtbot.addWidget(table)
        tables.append(table)
        table.resize(1100, 400)
        table.show()
        return table

    yield create
    for table in tables:
        table.close()
        table.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    tables.clear()


def test_keyboard_navigation(qtbot: QtBot, make_table: TableFactory, tmp_path: Path) -> None:
    """Native expansion, parent/child jumps, ordinary Qt keys, and action signals work."""
    table = make_table()
    model = table.tree_model
    table.setCurrentIndex(model.index(0, 0))
    qtbot.keyClick(table, Qt.Key.Key_Down)
    assert table.currentIndex().row() == 1
    qtbot.keyClick(table, Qt.Key.Key_Up)
    assert table.currentIndex().row() == 0
    qtbot.keyClick(table, Qt.Key.Key_End)
    assert table.currentIndex().row() == model.rowCount() - 1
    qtbot.keyClick(table, Qt.Key.Key_Home)
    assert table.currentIndex().row() == 0
    qtbot.keyClick(table, Qt.Key.Key_PageDown)
    page_row = table.currentIndex().row()
    assert page_row > 1
    qtbot.keyClick(table, Qt.Key.Key_PageUp)
    assert table.currentIndex().row() < page_row
    folder = model.view.tree.find_path(tmp_path / "tree/folder")
    assert folder is not None
    row = model.row_of(folder)
    assert row is not None
    table.setCurrentIndex(model.index(row, 0))
    qtbot.keyClick(table, Qt.Key.Key_Right)
    assert model.data(table.currentIndex(), model.ROW_ROLE)[3]
    qtbot.keyClick(table, Qt.Key.Key_Right)
    assert table.currentIndex().row() == row + 1
    qtbot.keyClick(table, Qt.Key.Key_Left)
    assert model.node_at(table.currentIndex().row()) == folder
    qtbot.keyClick(table, Qt.Key.Key_Left)
    assert not model.data(table.currentIndex(), model.ROW_ROLE)[3]
    qtbot.keyClick(table, Qt.Key.Key_Asterisk)
    leaf = model.view.tree.find_path(tmp_path / "tree/folder/nested/leaf.bin")
    assert leaf is not None and model.row_of(leaf) is not None
    with qtbot.waitSignal(table.propertiesRequested) as properties:
        qtbot.keyClick(table, Qt.Key.Key_Return)
    assert properties.args == [folder]
    with qtbot.waitSignal(table.contextMenuRequested) as context:
        qtbot.keyClick(table, Qt.Key.Key_Menu)
    assert context.args is not None and context.args[0] == folder


class ArrowStyle(QProxyStyle):
    """Observe the actual primitive selected during delegate painting."""

    def __init__(self) -> None:
        super().__init__("Fusion")
        self.arrows: list[tuple[QStyle.PrimitiveElement, QRect]] = []
        self.focuses: list[QRect] = []

    def drawPrimitive(self, element, option, painter, widget=None) -> None:
        if element in (
            self.PrimitiveElement.PE_IndicatorArrowLeft,
            self.PrimitiveElement.PE_IndicatorArrowRight,
            self.PrimitiveElement.PE_IndicatorArrowDown,
        ):
            self.arrows.append((element, QRect(option.rect)))
        if element == self.PrimitiveElement.PE_FrameFocusRect:
            self.focuses.append(QRect(option.rect))
        super().drawPrimitive(element, option, painter, widget)


def test_rtl_chevron_mirrors(make_table: TableFactory, tmp_path: Path) -> None:
    """Painting mirrors both arrow direction and its hit rectangle around the cell."""
    table = make_table()
    style = ArrowStyle()
    style.setParent(table)
    table.setStyle(style)
    model = table.tree_model
    node = model.view.tree.find_path(tmp_path / "tree/folder")
    assert node is not None
    index = model.index(model.row_of(node), 0)
    delegate = table.itemDelegateForColumn(0)
    assert isinstance(delegate, NameDelegate)
    image = QImage(320, 26, QImage.Format.Format_ARGB32_Premultiplied)
    option = QStyleOptionViewItem()
    option.rect, option.widget = QRect(0, 0, 320, 26), table
    rectangles: list[QRect] = []
    for direction, element in (
        (Qt.LayoutDirection.LeftToRight, QStyle.PrimitiveElement.PE_IndicatorArrowRight),
        (Qt.LayoutDirection.RightToLeft, QStyle.PrimitiveElement.PE_IndicatorArrowLeft),
    ):
        table.setLayoutDirection(direction)
        option.direction = direction
        painter = QPainter(image)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()
        assert style.arrows[-1][0] == element
        rectangles.append(style.arrows[-1][1])
    assert rectangles[0].left() == option.rect.right() - rectangles[1].right()
    assert rectangles[0].size() == rectangles[1].size()
    assert (
        delegate.chevron_element(True, Qt.LayoutDirection.RightToLeft)
        == QStyle.PrimitiveElement.PE_IndicatorArrowDown
    )


@pytest.mark.parametrize(
    "direction", [Qt.LayoutDirection.LeftToRight, Qt.LayoutDirection.RightToLeft]
)
def test_chevron_click_toggles(
    qtbot: QtBot,
    make_table: TableFactory,
    direction: Qt.LayoutDirection,
) -> None:
    """Clicking the painted control uses the same LTR/RTL hit geometry."""
    table = make_table()
    table.setLayoutDirection(direction)
    index = table.tree_model.index(0, 0)
    option = QStyleOptionViewItem()
    option.rect, option.direction = table.visualRect(index), direction
    position = NameDelegate.chevron_rect(option, 0).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=position)
    assert table.tree_model.rowCount() == 1
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=position)
    assert table.tree_model.rowCount() == 82


def test_column_visibility_persists(
    qtbot: QtBot,
    make_table: TableFactory,
    tmp_path: Path,
) -> None:
    """The header menu, dragged order, hidden widths, timer save and close flush persist."""
    paths = AppPaths(
        tmp_path / "config", tmp_path / "data", tmp_path / "logs", tmp_path / "snapshots", False
    )
    settings = Settings()
    table = make_table(settings, paths)
    owner = list(ColumnId).index(ColumnId.OWNER)
    assert table.isColumnHidden(owner)
    assert table.isColumnHidden(list(ColumnId).index(ColumnId.EXT))
    menu = table.column_menu()
    action = next(action for action in menu.actions() if action.objectName() == "column.owner")
    action.trigger()
    assert not table.isColumnHidden(owner)
    assert table.tree_model.view.options.resolve_owner
    assert table.tree_model.index(1, owner).data() == "Alice"
    table.setColumnWidth(owner, 233)
    table.setColumnHidden(owner, True)
    assert not table.tree_model.view.options.resolve_owner
    table.setColumnWidth(0, 411)
    table.horizontalHeader().moveSection(0, 3)
    qtbot.waitUntil((paths.config / "settings.json").exists)
    stored = load_settings(paths)
    assert next(c for c in stored.columns if c.id == ColumnId.NAME).width == 411
    assert next(c for c in stored.columns if c.id == ColumnId.OWNER).width == 233
    assert not next(c for c in stored.columns if c.id == ColumnId.OWNER).visible
    menu.close()
    table.close()
    restored = make_table(stored, paths)
    assert restored.isColumnHidden(owner)
    assert restored.horizontalHeader().visualIndex(0) == 3
    assert restored.columnWidth(0) == 411
    restored.setColumnHidden(owner, False)
    assert restored.columnWidth(owner) == 233
    restored.setColumnWidth(0, 427)
    restored.close()  # Flush without waiting another debounce interval.
    assert next(c for c in load_settings(paths).columns if c.id == ColumnId.NAME).width == 427


def test_accessible_text_role_present(make_table: TableFactory) -> None:
    """Rows describe name/type/size/percentage through Qt's accessible text role."""
    table = make_table()
    assert table.accessibleName() == "Directory tree"
    root = table.tree_model.index(0, 0).data(Qt.ItemDataRole.AccessibleTextRole)
    file = table.tree_model.index(1, 0).data(Qt.ItemDataRole.AccessibleTextRole)
    assert "folder" in root and "of parent" in root
    assert "file" in file and "of parent" in file
    assert file.count(",") >= 3


def test_numeric_delegate_and_category_icons(
    qtbot: QtBot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allocated uncertainty remains visible and all category icons are cached originals."""
    tree = TreeBuilder.flat(tmp_path / "synthetic", 1)
    view = api.TreeView(tree)
    value = list(view.rows(0, 1)[0])
    value[6], value[13] = 2048, int(api.NodeFlags.ALLOC_UNRELIABLE)
    monkeypatch.setattr(view, "rows", lambda start, count: [tuple(value)])
    model = TreeTableModel(view, list(ColumnId))
    table = TreeTableView(model, Settings())
    qtbot.addWidget(table)
    index = model.index(0, list(ColumnId).index(ColumnId.ALLOC))
    assert index.data() == "≈" + api.format_size(2048)
    delegate = table.itemDelegateForColumn(index.column())
    assert isinstance(delegate, SizeDelegate)
    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, index)
    assert option.displayAlignment & Qt.AlignmentFlag.AlignRight
    name = table.itemDelegateForColumn(0)
    assert isinstance(name, NameDelegate)
    icons = [name._category_icon(category) for category in range(len(api.ExtCategory))]
    assert len({icon.cacheKey() for icon in icons}) == len(api.ExtCategory)
    assert name._category_icon(0) is icons[0]
    table.show()
    assert not table.grab().isNull()


def test_delegate_selection_alternation_and_focus(make_table: TableFactory) -> None:
    """Fast painting retains palette backgrounds and the actual native focus primitive."""
    table = make_table()
    style = ArrowStyle()
    style.setParent(table)
    table.setStyle(style)
    index = table.tree_model.index(1, list(ColumnId).index(ColumnId.SIZE))
    delegate = table.itemDelegateForColumn(index.column())
    image = QImage(120, 26, QImage.Format.Format_ARGB32_Premultiplied)
    option = QStyleOptionViewItem()
    option.widget, option.rect = table, QRect(0, 0, 120, 26)
    option.palette = table.palette()
    option.state = (
        QStyle.StateFlag.State_Enabled
        | QStyle.StateFlag.State_Selected
        | QStyle.StateFlag.State_HasFocus
    )
    painter = QPainter(image)
    try:
        delegate.paint(painter, option, index)
    finally:
        painter.end()
    assert image.pixelColor(3, 10) == option.palette.color(QPalette.ColorRole.Highlight)
    assert len(style.focuses) == 1
    option.state = QStyle.StateFlag.State_Enabled
    option.features |= QStyleOptionViewItem.ViewItemFeature.Alternate
    painter = QPainter(image)
    try:
        delegate.paint(painter, option, index)
    finally:
        painter.end()
    assert image.pixelColor(3, 10) == option.palette.color(QPalette.ColorRole.AlternateBase)
    assert len(style.focuses) == 1


def test_text_layout_cache_owns_fonts_and_stays_bounded(qtbot: QtBot) -> None:
    """Prepared layouts survive their borrowed options and cannot grow with scanned nodes."""
    cache = TextCache()
    image = QImage(120, 26, QImage.Format.Format_ARGB32_Premultiplied)
    rect = QRect(0, 0, 120, 26)
    option = QStyleOptionViewItem()
    painter = QPainter(image)
    try:
        cache.draw(painter, option, rect, "same", Qt.AlignmentFlag.AlignRight)
        del option
        gc.collect()
        option = QStyleOptionViewItem()
        cache.draw(painter, option, rect, "same", Qt.AlignmentFlag.AlignRight)
        assert len(cache._layouts) == 1
        for number in range(300):
            cache.draw(painter, option, rect, str(number), Qt.AlignmentFlag.AlignRight)
        assert len(cache._layouts) == 256
    finally:
        painter.end()


@pytest.mark.parametrize(
    "direction", [Qt.LayoutDirection.LeftToRight, Qt.LayoutDirection.RightToLeft]
)
def test_virtual_paint_covers_visible_cells_only(
    make_table: TableFactory,
    monkeypatch: pytest.MonkeyPatch,
    direction: Qt.LayoutDirection,
) -> None:
    """Every visible cell uses its real Qt geometry; hidden/offscreen rows are never painted."""
    table = make_table()
    table.setLayoutDirection(direction)
    QApplication.processEvents()
    painted: list[tuple[int, int, QRect]] = []
    delegates = {table.itemDelegate()}
    delegates.update(table.itemDelegateForColumn(i) for i in range(table.tree_model.columnCount()))
    delegates.discard(None)
    for delegate in delegates:
        original = delegate.paint

        def observe(painter, option, index, original=original):
            painted.append((index.row(), index.column(), QRect(option.rect)))
            original(painter, option, index)

        monkeypatch.setattr(delegate, "paint", observe)
    table.scrollTo(table.tree_model.index(50, 0), table.ScrollHint.PositionAtTop)
    QApplication.processEvents()
    painted.clear()
    table.viewport().repaint()
    viewport = table.viewport().rect()
    first, last = table.rowAt(0), table.rowAt(viewport.bottom())
    assert first == 50 and last < table.tree_model.rowCount() - 1
    expected = {
        (row, column)
        for row in range(first, last + 1)
        for column in range(table.tree_model.columnCount())
        if not table.isColumnHidden(column)
        and table.visualRect(table.tree_model.index(row, column)).intersects(viewport)
    }
    assert {(row, column) for row, column, rect in painted} == expected
    for row, column, rect in painted:
        assert rect == table.visualRect(table.tree_model.index(row, column))
    table.tree_model.toggle(0)
    QApplication.processEvents()
    painted.clear()
    image = table.viewport().grab().toImage()
    assert {row for row, column, rect in painted} == {0}
    assert image.pixelColor(10, viewport.bottom() - 2) == table.palette().color(
        QPalette.ColorRole.Base
    )
