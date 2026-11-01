"""Exercise the installed abi3 wheel outside the source checkout."""

import importlib.metadata
import importlib.util
import platform
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from dafree.api import (
    FilterKind,
    FilterSpec,
    ScanRequest,
    TreeView,
    ViewOptions,
    format_size,
    parse_size,
    scan,
)


def main() -> None:
    """Reject incorrect wheel tags, checkout imports, and broken native scanning."""
    metadata = importlib.metadata.distribution("disk-analyzer-free").read_text("WHEEL")
    if metadata is None or "Tag: cp312-abi3-" not in metadata:
        raise RuntimeError("Expected a cp312-abi3 wheel")
    spec = importlib.util.find_spec("dafree._core")
    if spec is None or spec.origin is None:
        raise RuntimeError("Native extension is missing")
    if not Path(spec.origin).resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError("Native extension must come from the installed wheel")
    license_path = Path(spec.origin).parent / "licenses" / "PCRE2.txt"
    if not license_path.is_file() or "Redistribution" not in license_path.read_text(
        encoding="utf-8"
    ):
        raise RuntimeError("Installed wheel must include the linked PCRE2 license")
    with TemporaryDirectory(prefix="dafree-wheel-") as directory:
        root = Path(directory)
        payload = b"wheel verification"
        sample = root / "sample.bin"
        sample.write_bytes(payload)
        tree = scan(ScanRequest(targets=[root])).tree
        node = tree.node(tree.roots()[0])
        if node.size != len(payload) or node.files != 1 or tree.find_path(sample) is None:
            raise RuntimeError("Installed wheel scan returned incorrect totals or paths")
        view = TreeView(tree, ViewOptions(filter=FilterSpec(FilterKind.REGEX, regex=r"\.bin$")))
        rows = view.rows(1, 1)
        expected_rows = 2  # One target root and one matching file.
        if (
            view.row_count != expected_rows
            or len(rows) != 1
            or rows[0][4:6] != (sample.name, len(payload))
        ):
            raise RuntimeError("Installed wheel native regex view returned incorrect rows")
    sample_size = 512
    if parse_size(format_size(sample_size)) != sample_size:
        raise RuntimeError("Installed wheel unit conversion failed")
    print(f"Verified cp312-abi3 wheel on {platform.system()} / Python {platform.python_version()}")


if __name__ == "__main__":
    main()
