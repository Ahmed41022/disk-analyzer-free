"""Native read-only host metadata is exposed without adding a GUI dependency."""

import os
import sys
from pathlib import Path

import pytest

from dafree import api


def test_native_volumes_include_the_test_directory_volume(tmp_path: Path) -> None:
    """Only a test-owned file is created; the host query reads volume metadata, not entries."""
    (tmp_path / "sample").write_bytes(b"data")
    tree = api.scan(api.ScanRequest([tmp_path])).tree
    target = tree.meta().volumes[0]
    volumes = api.platform.volumes()
    assert volumes
    assert all(isinstance(volume, api.VolumeInfo) for volume in volumes)
    assert any(
        volume.mount == target.mount and volume.serial == target.serial for volume in volumes
    )
    assert all(volume.total >= 0 and 0 <= volume.free <= volume.total for volume in volumes)


def test_privilege_information_never_guesses_false() -> None:
    """Windows remains explicitly unavailable until T3.7; POSIX uses its existing native API."""
    if sys.platform == "win32":
        with pytest.raises(api.Unsupported, match="Privilege information"):
            api.platform.is_elevated()
    else:
        assert api.platform.is_elevated() == (os.geteuid() == 0)
