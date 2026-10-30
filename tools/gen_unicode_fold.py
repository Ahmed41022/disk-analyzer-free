"""Generate the checked-in BMP simple case-fold table from Unicode data."""

from __future__ import annotations

import argparse
from pathlib import Path

_BMP_MAX = 0xFFFF


def parse_mappings(source: Path) -> list[tuple[int, int]]:
    """Return one-code-point common and simple folds whose source and target are BMP."""
    mappings: list[tuple[int, int]] = []
    seen: set[int] = set()
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        fields = line.split("#", maxsplit=1)[0].strip()
        if not fields:
            continue
        source_text, status, mapping_text = [field.strip() for field in fields.split(";")[:3]]
        codepoint = int(source_text, 16)
        targets = mapping_text.split()
        if status not in {"C", "S"} or codepoint > _BMP_MAX or len(targets) != 1:
            continue
        target = int(targets[0], 16)
        if target > _BMP_MAX:
            continue
        if codepoint in seen:
            raise ValueError(f"duplicate BMP mapping on line {line_number}: U+{codepoint:04X}")
        seen.add(codepoint)
        mappings.append((codepoint, target))
    if not mappings:
        raise ValueError(f"no BMP simple folds found in {source}")
    return sorted(mappings)


def render(mappings: list[tuple[int, int]]) -> str:
    """Render C++ mappings with the required Unicode attribution."""
    lines = [
        "// Generated from tools/data/CaseFolding-17.0.0.txt by tools/gen_unicode_fold.py.",
        "// Copyright © 2025 Unicode, Inc. and others. Unicode License V3; see",
        "// LICENSES/Unicode-Data-Files-and-Software-License.txt.",
        "#pragma once",
        "",
        "#include <array>",
        "#include <cstdint>",
        "#include <utility>",
        "",
        "namespace dafree::detail {",
        "",
        "struct SimpleFoldPair {",
        "    char32_t source;",
        "    char32_t target;",
        "};",
        "",
        f"inline constexpr std::array<SimpleFoldPair, {len(mappings)}> kSimpleFoldPairs{{{{",
    ]
    entries = [f"{{0x{source:04X}, 0x{target:04X}}}," for source, target in mappings]
    lines.extend("    " + " ".join(entries[i : i + 5]) for i in range(0, len(entries), 5))
    lines.extend(["}};", "", "} // namespace dafree::detail", ""])
    return "\n".join(lines)


def main() -> int:
    """Generate the checked-in header from the licensed Unicode source file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("tools/data/CaseFolding-17.0.0.txt"))
    parser.add_argument(
        "--output", type=Path, default=Path("core/src/model/unicode_fold_table.hpp")
    )
    args = parser.parse_args()
    args.output.write_text(render(parse_mappings(args.input)), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
