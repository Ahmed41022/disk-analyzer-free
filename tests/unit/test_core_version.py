"""Version metadata consistency checks."""

from importlib.metadata import version

import dafree


def test_core_version_matches_package() -> None:
    """The C++ extension and package metadata expose the same version."""
    assert dafree.__version__ == version("disk-analyzer-free")
