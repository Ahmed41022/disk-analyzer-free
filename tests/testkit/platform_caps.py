"""Feature availability recorded by a temporary fixture."""

import os
import sys
from dataclasses import dataclass, field

import pytest


@dataclass
class Caps:
    """Capabilities observed while creating the requested fixture."""

    hardlink: bool = True
    symlink: bool = True
    junction: bool = sys.platform == "win32"
    sparse: bool = True
    permission_denied: bool = True
    long_paths: bool = True
    invalid_utf8: bool = sys.platform.startswith("linux")
    reasons: dict[str, str] = field(default_factory=dict)

    def unavailable(self, feature: str, reason: str) -> None:
        """Record an unsupported feature without hiding the reason."""
        setattr(self, feature, False)
        self.reasons[feature] = reason

    def require(self, feature: str) -> None:
        """Skip an unsupported feature locally or fail when CI requires it."""
        if bool(getattr(self, feature)):
            return
        reason = self.reasons.get(feature, f"{feature} is unavailable")
        if os.environ.get("DAFREE_REQUIRE_ALL_CAPS") == "1":
            raise AssertionError(reason)
        pytest.skip(reason)
