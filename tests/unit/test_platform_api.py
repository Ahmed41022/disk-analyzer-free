"""Native host services work without a GUI dependency."""

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
    """A real privilege query returns a boolean on each supported platform."""
    if sys.platform == "win32":
        assert type(api.platform.is_elevated()) is bool
    else:
        assert api.platform.is_elevated() == (os.geteuid() == 0)


@pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("CI") != "true",
    reason="Requires the elevated Windows CI runner",
)
def test_is_elevated_true_on_ci_windows() -> None:
    assert api.platform.is_elevated() is True, "Windows CI runner must use an elevated token"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX does not support relaunch")
def test_elevated_relaunch_is_unsupported_on_posix() -> None:
    with pytest.raises(api.Unsupported, match="unsupported on POSIX"):
        api.platform.relaunch_elevated(["argument with spaces"])
