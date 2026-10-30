"""Desktop application startup tests."""

import os
from importlib.util import find_spec

import pytest
from pytestqt.qtbot import QtBot

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from dafree.gui.main_window import create_main_window


@pytest.mark.gui
def test_gui_main_window_opens_and_closes(qtbot: QtBot) -> None:
    """The main window can be shown and closed by the Qt test harness."""
    window = create_main_window()
    qtbot.addWidget(window)
    window.show()

    assert window.windowTitle() == "Disk Analyzer Free"

    window.close()
