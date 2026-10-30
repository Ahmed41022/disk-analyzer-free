"""Process exit codes used by the command line interface."""

from enum import IntEnum


class ExitCode(IntEnum):
    """Standard CLI success, runtime failure, and usage failure codes."""

    SUCCESS = 0
    ERROR = 1
    USAGE = 2
