"""Real application event loops dispose native-backed windows before interpreter shutdown."""

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


@pytest.mark.gui
@pytest.mark.parametrize("external_quit", [False, True])
def test_application_shutdown_drains_owned_scan(tmp_path: Path, external_quit: bool) -> None:
    """Both closing and external quit cancel a native scan, deliver results, and exit cleanly."""
    script = r"""
import os
from pathlib import Path
from PySide6.QtCore import QDir, QTimer
from PySide6.QtWidgets import QApplication
from dafree import api
from dafree.api.testing import MockEntry, MockSpec, make_mock_backend
from dafree.gui import app
from dafree.gui.main_window import create_main_window
QDir.tempPath = lambda: os.environ["DAFREE_TEST_IPC"]
root = Path(os.environ["DAFREE_TEST_ROOT"])
entries = [MockEntry(root, api.EntryKind.DIR)]
for number in range(12):
    entries.extend([
        MockEntry(root / str(number), api.EntryKind.DIR),
        MockEntry(root / str(number) / 'file', size=1),
    ])
backend = make_mock_backend(MockSpec(entries, delay_ms=80))
def create(**kwargs):
    window = create_main_window(**kwargs, volume_provider=lambda: [], scan_backend=backend)
    window.start_scan(api.ScanRequest([root], threads=1))
    action = QApplication.quit if os.environ['DAFREE_EXTERNAL_QUIT']=='1' else window.close
    QTimer.singleShot(50, action)
    return window
app.create_main_window = create
exit_code = app.main([])
app.create_main_window = create_main_window
del backend  # The probe's own global must not survive into native binding leak auditing.
raise SystemExit(exit_code)
"""
    with TemporaryDirectory(prefix="da-") as ipc:
        env = os.environ | {
            "QT_QPA_PLATFORM": "offscreen",
            "DAFREE_CONFIG_DIR": str(tmp_path / "profile"),
            "DAFREE_TEST_ROOT": str(tmp_path / "native-mock"),
            "DAFREE_TEST_IPC": ipc,
            "DAFREE_EXTERNAL_QUIT": "1" if external_quit else "0",
            "TMPDIR": ipc,
            "TMP": ipc,
            "TEMP": ipc,
        }
        result = subprocess.run(  # noqa: S603 -- fixed script; all target/profile/IPC paths are test-owned.
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    assert result.returncode == 0, result.stderr
    assert "nanobind: leaked" not in result.stderr
    assert "Traceback" not in result.stderr
