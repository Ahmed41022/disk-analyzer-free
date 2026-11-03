"""Run the native allocation oracle through CTest's Python interpreter."""

import re
import subprocess
import sys
from pathlib import Path


def test_json_streaming_constant_memory(executable: Path) -> None:
    """Use the instrumented test binary rather than a process RSS estimate."""
    command = [
        str(executable.resolve(strict=True)),
        "--test-case=test_json_streaming_constant_memory",
        "--no-colors",
    ]
    result = subprocess.run(  # noqa: S603
        command, capture_output=True, text=True, check=False, timeout=180
    )
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    result.check_returncode()
    if not re.search(r"test cases:\s+1\s+\|\s+1 passed", result.stdout):
        raise RuntimeError("the native JSON allocation case did not run")


if __name__ == "__main__":
    test_json_streaming_constant_memory(Path(sys.argv[1]))
