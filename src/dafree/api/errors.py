"""Stable Python exceptions for native scan failures."""

from enum import StrEnum

from dafree.api.types import IssueKind


class DafreeError(Exception):
    """Base class for errors reported by the native core."""


class ScanErrorCode(StrEnum):
    """Machine-readable scan failure reason."""

    NO_TARGETS = "no_targets"
    INVALID_TARGET = "invalid_target"
    TARGET_NOT_FOUND = "target_not_found"
    OVERLAPPING_TARGETS = "overlapping_targets"
    MFT_UNAVAILABLE = "mft_unavailable"
    BACKEND = "backend"
    NOT_FINISHED = "not_finished"
    ALREADY_TAKEN = "already_taken"
    INVALID_HANDLE = "invalid_handle"


class ScanError(DafreeError):
    """A scan could not start or its result could not be consumed."""

    def __init__(
        self,
        message: str,
        code: ScanErrorCode,
        *,
        path: str | None = None,
        kind: IssueKind | None = None,
    ) -> None:
        super().__init__(message)
        self.code, self.path, self.kind = code, path, kind


class ExcludeError(DafreeError):
    """An exclusion glob is invalid."""

    def __init__(self, message: str, pattern: str | None = None) -> None:
        super().__init__(message)
        self.pattern = pattern


def _from_native(
    family: str, code: int, message: str, path: str | None, pattern: str | None
) -> DafreeError:
    if family == "exclude":
        return ExcludeError(message, pattern)
    if family == "io":
        kind = IssueKind(code)
        reason = (
            ScanErrorCode.TARGET_NOT_FOUND if kind == IssueKind.NOT_FOUND else ScanErrorCode.BACKEND
        )
        return ScanError(message, reason, path=path, kind=kind)
    if family == "scan":
        reasons = (
            ScanErrorCode.NO_TARGETS,
            ScanErrorCode.INVALID_TARGET,
            ScanErrorCode.OVERLAPPING_TARGETS,
            ScanErrorCode.MFT_UNAVAILABLE,
            ScanErrorCode.NOT_FINISHED,
            ScanErrorCode.ALREADY_TAKEN,
            ScanErrorCode.INVALID_HANDLE,
        )
        return ScanError(message, reasons[code])
    return DafreeError(message)
