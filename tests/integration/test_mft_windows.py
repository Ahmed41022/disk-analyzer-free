"""Verify raw MFT results and Windows restricted-token fallback."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from dafree import api
from dafree.cli.exit_codes import Exit

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows NTFS volume access")
_RESTRICTED = Path(__file__).parents[2] / "tools" / "run_restricted.py"


def _volume_root() -> Path:
    data = Path("D:\\")
    return data if data.is_dir() else Path("C:\\")


def _require_elevated() -> None:
    if os.environ.get("CI") == "true":
        assert api.platform.is_elevated(), "Windows CI runner must use an elevated token"
    elif not api.platform.is_elevated():
        pytest.skip("An elevated token is required for raw-volume acceptance")


def _restricted_scan(path: Path, mode: str) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("dafree")
    assert executable is not None, "Install the dafree CLI before running Windows integration tests"
    return subprocess.run(  # noqa: S603 -- Installed CLI and test-owned target.
        [
            sys.executable,
            str(_RESTRICTED),
            "--",
            executable,
            "--format",
            "json",
            "--progress",
            "never",
            "scan",
            "--mode",
            mode,
            str(path),
        ],
        capture_output=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def _tree_rows(tree: api.Tree, root: Path) -> dict[str, api.NodeInfo]:
    return {
        Path(tree.path(node_id)).relative_to(root).as_posix(): tree.node(node_id)
        for node_id in range(1, len(tree))
    }


def test_mft_scan_matches_walk_on_fixture() -> None:
    _require_elevated()
    with TemporaryDirectory(prefix="dafree-mft-", dir=_volume_root()) as directory:
        root = Path(directory)
        (root / "nested").mkdir()
        (root / "resident.txt").write_bytes(b"resident")
        large = root / "large.bin"
        large.write_bytes(b"\x7f" * 65536)
        os.link(large, root / "nested" / "large-link.bin")

        walk = api.scan(api.ScanRequest([root], mode=api.ScanMode.WALK))
        mft = api.scan(api.ScanRequest([root], mode=api.ScanMode.MFT))
        assert mft.tree.meta().mode is api.ScanModeUsed.MFT
        walk_rows = _tree_rows(walk.tree, root)
        mft_rows = _tree_rows(mft.tree, root)
        assert walk_rows.keys() == mft_rows.keys()
        for name, expected in walk_rows.items():
            actual = mft_rows[name]
            assert (actual.size, actual.files, actual.dirs) == (
                expected.size,
                expected.files,
                expected.dirs,
            )
        duplicates = api.NodeFlags.HARDLINK_DUP
        assert {name for name, node in walk_rows.items() if node.flags & duplicates} == {
            "nested/large-link.bin"
        }
        assert {name for name, node in mft_rows.items() if node.flags & duplicates} == {
            "nested/large-link.bin"
        }
        assert mft_rows["resident.txt"].alloc == 0
        assert walk_rows["resident.txt"].alloc <= walk.tree.meta().volumes[0].cluster_size


def test_mft_unavailable_when_not_elevated() -> None:
    _require_elevated()
    with TemporaryDirectory(prefix="dafree-restricted-", dir=_volume_root()) as directory:
        result = _restricted_scan(Path(directory), "auto")
    assert result.returncode == Exit.OK, result.stderr
    assert "FastModeUnavailable" in result.stderr and "not elevated" in result.stderr
    assert json.loads(result.stdout)["meta"]["mode"] == "walk"


def test_mft_mode_strict_errors_when_unavailable(tmp_path: Path) -> None:
    result = _restricted_scan(tmp_path, "mft")
    assert result.returncode == Exit.RUNTIME, result.stderr
    assert "not elevated" in result.stderr
    assert not result.stdout
