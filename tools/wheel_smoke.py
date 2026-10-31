"""Exercise the installed abi3 wheel outside the source checkout."""

import importlib.metadata
import importlib.util
import platform
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from dafree.api import ScanRequest, format_size, parse_size, scan


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
    with TemporaryDirectory(prefix="dafree-wheel-") as directory:
        root = Path(directory)
        payload = b"wheel verification"
        sample = root / "sample.bin"
        sample.write_bytes(payload)
        tree = scan(ScanRequest(targets=[root])).tree
        node = tree.node(tree.roots()[0])
        if node.size != len(payload) or node.files != 1 or tree.find_path(sample) is None:
            raise RuntimeError("Installed wheel scan returned incorrect totals or paths")
    sample_size = 512
    if parse_size(format_size(sample_size)) != sample_size:
        raise RuntimeError("Installed wheel unit conversion failed")
    print(f"Verified cp312-abi3 wheel on {platform.system()} / Python {platform.python_version()}")


if __name__ == "__main__":
    main()
