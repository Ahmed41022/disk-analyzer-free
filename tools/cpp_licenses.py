"""Validate declared C++ dependency licenses and source pins."""

import argparse
import re
import sys
from pathlib import Path

ALLOWED_LICENSES = {
    "MIT",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "Apache-2.0",
    "ISC",
    "Zlib",
    "CC0-1.0",
    "Unlicense",
    "MPL-2.0",
    "BSL-1.0",
}
COMMENT_PATTERN = re.compile(r"^\s*# dafree-dep: name=(\S+) license=(\S+) url=(\S+)\s*$")
DECLARATION_PATTERN = re.compile(r"(?mi)^\s*FetchContent_Declare\s*\(\s*([A-Za-z0-9_.+-]+)")


def _normalize_name(name: str) -> str:
    """Normalize CMake and dependency comment names for comparison."""
    return name.lower().replace("-", "_").replace(".", "_")


def check_dependencies(path: Path) -> list[str]:
    """Return validation errors found in a CMake dependency file."""
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    errors: list[str] = []
    declarations = list(DECLARATION_PATTERN.finditer(content))

    if not declarations:
        return [f"{path}: no FetchContent_Declare entries found"]

    for declaration in declarations:
        line_number = content.count("\n", 0, declaration.start())
        previous_line = line_number - 1
        while previous_line >= 0 and not lines[previous_line].strip():
            previous_line -= 1

        dependency = declaration.group(1)
        if previous_line < 0:
            errors.append(f"{path}:{line_number + 1}: {dependency} has no dafree-dep comment")
            continue

        comment = COMMENT_PATTERN.match(lines[previous_line])
        if comment is None:
            errors.append(f"{path}:{line_number + 1}: {dependency} has no dafree-dep comment")
            continue

        comment_name, license_name, _url = comment.groups()
        if _normalize_name(comment_name) != _normalize_name(dependency):
            errors.append(
                f"{path}:{previous_line + 1}: comment name {comment_name!r} does not match "
                f"FetchContent name {dependency!r}"
            )
        if license_name not in ALLOWED_LICENSES:
            errors.append(
                f"{path}:{previous_line + 1}: {dependency} uses disallowed license {license_name!r}"
            )

        next_declaration = next(
            (item.start() for item in declarations if item.start() > declaration.start()),
            len(content),
        )
        block = content[declaration.start() : next_declaration]
        if re.search(r"(?im)^\s*URL_HASH\s+SHA256=[0-9a-f]{64}\s*$", block) is None:
            errors.append(f"{path}:{line_number + 1}: {dependency} has no SHA256 URL_HASH")

    return errors


def main() -> int:
    """Run dependency policy validation and return a process status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cmake_file", type=Path)
    args = parser.parse_args()

    try:
        errors = check_dependencies(args.cmake_file)
    except OSError as error:
        print(f"{args.cmake_file}: {error}", file=sys.stderr)
        return 1

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    dependency_count = len(DECLARATION_PATTERN.findall(args.cmake_file.read_text(encoding="utf-8")))
    print(f"Validated {dependency_count} C++ dependencies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
