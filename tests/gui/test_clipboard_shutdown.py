"""Clipboard ownership must remain safe when the Qt process actually exits."""

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.gui


def test_clipboard_copy_process_exits_cleanly() -> None:
    """Raw MIME data and ordinary text survive copying without a shutdown access violation."""
    script = """
from PySide6.QtWidgets import QApplication
from dafree.gui import _copy_text
app = QApplication([])
_copy_text('full path', {'application/x-dafree-native-path': b'native-path'})
mime = app.clipboard().mimeData()
assert mime.text() == 'full path'
assert bytes(mime.data('application/x-dafree-native-path')) == b'native-path'
"""
    result = subprocess.run(  # noqa: S603 -- fixed clipboard-only probe; no file or network operation.
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        env=os.environ | {"QT_QPA_PLATFORM": "offscreen"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "nanobind: leaked" not in result.stderr
