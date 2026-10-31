"""Shared application directories; portable detection follows in T10.2."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import platformdirs

from dafree.i18n import _


@dataclass(frozen=True)
class AppPaths:
    """Directories used by the CLI and GUI without creating them on detection."""

    config: Path
    data: Path
    logs: Path
    snapshots: Path
    portable: bool


def detect(
    exe: Path | None = None,
    *,
    cli_flag: bool = False,
    env: Mapping[str, str] = os.environ,
) -> AppPaths:
    """Find normal paths or a test-only DAFREE_CONFIG_DIR sandbox.

    Portable mode is deliberately unavailable until T10.2. An explicit request
    fails rather than silently writing preferences to a non-portable location.
    The test override contains all application directories to isolate test I/O.
    """
    del exe  # Executable/portable.txt detection belongs to T10.2.
    if cli_flag or env.get("DAFREE_PORTABLE") == "1":
        raise NotImplementedError(_("Portable mode is not available yet"))
    if override := env.get("DAFREE_CONFIG_DIR"):
        config = Path(override).expanduser().absolute()
        data = config / "data"
    else:
        config = Path(platformdirs.user_config_dir("disk-analyzer-free", appauthor=False))
        data = Path(platformdirs.user_data_dir("disk-analyzer-free", appauthor=False))
    return AppPaths(config, data, data / "logs", data / "snapshots", portable=False)
