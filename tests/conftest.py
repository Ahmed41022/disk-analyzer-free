"""Shared pytest configuration."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_configure(config: pytest.Config) -> None:
    """Register project markers when configuration is loaded outside the repo."""
    markers = (
        "gui: requires the Qt GUI dependencies",
        "slow: long-running tests",
        "windows_only: Windows-specific behavior",
        "needs_mounts: requires mount privileges",
        "needs_scheduler: requires OS scheduler integration",
        "needs_smb: requires an SMB share",
    )
    configured = {line.split(":", maxsplit=1)[0] for line in config.getini("markers")}
    for marker in markers:
        if marker.split(":", maxsplit=1)[0] not in configured:
            config.addinivalue_line("markers", marker)
