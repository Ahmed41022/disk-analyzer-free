"""Stream native scan reports to Python binary streams."""

import locale
from collections.abc import Sequence
from typing import BinaryIO

from dafree import _core
from dafree.api.tree import Tree

_MAX_DEPTH = (1 << 16) - 1


def _validate(tree: Tree, scopes: Sequence[int], depth: int | None) -> None:
    if depth is not None and not 0 <= depth <= _MAX_DEPTH:
        raise ValueError("depth must fit in an unsigned 16-bit integer")
    node_count = len(tree)
    if any(not 0 < node_id < node_count for node_id in scopes):
        raise IndexError("invalid report scope node ID")


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
    _validate(tree, scopes, depth)
    _core.write_json(
        tree._native, scopes, stream.write, depth, include_files, ndjson, include_owner, pretty
    )


def write_csv(  # noqa: PLR0913 -- Mirror the independent native report options.
    tree: Tree,
    stream: BinaryIO,
    *,
    scopes: Sequence[int] = (),
    depth: int | None = None,
    include_files: bool = True,
    excel: bool = False,
    include_owner: bool = False,
    delimiter: str | None = None,
) -> None:
    """Write UTF-8 CSV with CRLF records to an open binary stream.

    Excel mode adds a BOM and defaults to semicolon in decimal-comma locales.
    An explicit delimiter overrides the default.
    """
    _validate(tree, scopes, depth)
    if delimiter is None:
        delimiter = ";" if excel and locale.localeconv()["decimal_point"] == "," else ","
    if len(delimiter) != 1 or (
        delimiter != "\t" and not (" " <= delimiter <= "~" and delimiter != '"')
    ):
        raise ValueError("CSV delimiter must be printable ASCII other than a quote, or a tab")
    _core.write_csv(
        tree._native, scopes, stream.write, depth, include_files, excel, include_owner, delimiter
    )
