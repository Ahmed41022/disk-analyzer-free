"""Process exit codes used by the command line interface."""

from enum import IntEnum


class Exit(IntEnum):
    """Stable process exit statuses shared by all CLI commands."""

    OK = 0
    RUNTIME = 1
    USAGE = 2
    ALERT = 3
    PARTIAL = 4
    FOUND = 5
    BLOCKED = 10
    INTERRUPTED = 130
