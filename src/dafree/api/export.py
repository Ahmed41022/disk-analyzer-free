"""Stream native scan reports to Python binary streams."""

from collections.abc import Sequence
from typing import BinaryIO

from dafree import _core
from dafree.api.tree import Tree

_MAX_DEPTH = (1 << 16) - 1


def write_json(  # noqa: PLR0913 -- Mirror the independent native report options.
    tree: Tree,
    stream: BinaryIO,
    *,
    scopes: Sequence[int] = (),
    depth: int | None = None,
    include_files: bool = True,
    ndjson: bool = False,
    include_owner: bool = False,
    pretty: bool = False,
) -> None:
    """Write UTF-8 JSON to an open binary stream, leaving it open.

    An empty scope list selects all scan roots. Depth is measured from each
    scope. NDJSON writes one compact object with a path per line.
    """
    if depth is not None and not 0 <= depth <= _MAX_DEPTH:
        raise ValueError("depth must fit in an unsigned 16-bit integer")
    node_count = len(tree)
    if any(not 0 < node_id < node_count for node_id in scopes):
        raise IndexError("invalid JSON scope node ID")
    _core.write_json(
        tree._native, scopes, stream.write, depth, include_files, ndjson, include_owner, pretty
    )
