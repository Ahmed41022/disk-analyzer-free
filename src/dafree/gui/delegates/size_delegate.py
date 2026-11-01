"""Right-aligned numeric cells using the model's native unit formatting."""

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtWidgets import QStyleOptionViewItem

from dafree.gui.delegates import DisplayDelegate, display_option


class SizeDelegate(DisplayDelegate):
    """Align numeric values while retaining standard selection/focus rendering."""

    alignment = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

    def initStyleOption(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        """Use the formatted display text, including approximate allocated values."""
        display_option(option, index)
        option.displayAlignment = self.alignment
