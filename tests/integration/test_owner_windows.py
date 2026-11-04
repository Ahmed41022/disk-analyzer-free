"""Check Windows file-owner lookup against the process account."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from dafree import _core, api

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows SID lookup")


def test_owner_of_temp_file_is_current_user(tmp_path: Path) -> None:
    path = tmp_path / "owned.txt"
    path.touch()
    whoami = Path(os.environ["SYSTEMROOT"]) / "System32" / "whoami.exe"
    account = subprocess.check_output(  # noqa: S603 -- fixed Windows system executable.
        [whoami], text=True
    ).strip()
    owner = api.platform.owner_of(path)
    assert owner is not None
    if api.platform.is_elevated() and owner.casefold() != account.casefold():
        # An elevated token can create files owned by its default Administrators group.
        icacls = whoami.with_name("icacls.exe")
        subprocess.run(  # noqa: S603 -- fixed Windows executable and test-owned file.
            [icacls, path, "/setowner", account], check=True, capture_output=True
        )
        owner = api.platform.owner_of(path)
    assert owner is not None and owner.casefold() == account.casefold()
    assert api.platform.owner_of(tmp_path / "missing.txt") is None


def test_sid_cache_hits(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.touch()
    second.touch()
    owner = api.platform.owner_of(first)
    assert owner
    before = _core.testing.sid_cache_hits()
    assert api.platform.owner_of(second) == owner
    assert _core.testing.sid_cache_hits() > before


def test_scan_resolves_windows_owners_on_demand(tmp_path: Path) -> None:
    path = tmp_path / "owner.txt"
    path.touch()
    lazy = api.scan(api.ScanRequest([tmp_path], owner=api.OwnerMode.LAZY)).tree
    node = lazy.find_path(path)
    assert node is not None and lazy.node(node).owner is None
    lazy.resolve_owners([node])
    assert lazy.node(node).owner == api.platform.owner_of(path)
    assert lazy.node(node).owner
    eager = api.scan(api.ScanRequest([tmp_path], owner=api.OwnerMode.EAGER)).tree
    node = eager.find_path(path)
    assert node is not None and eager.node(node).owner == api.platform.owner_of(path)
    disabled = api.scan(api.ScanRequest([tmp_path], owner=api.OwnerMode.OFF)).tree
    node = disabled.find_path(path)
    assert node is not None
    disabled.resolve_owners([node])
    assert disabled.node(node).owner is None


def test_windows_owner_view_filter_and_export(tmp_path: Path) -> None:
    import io  # noqa: PLC0415 -- Keep report-only test dependencies scoped.
    import json  # noqa: PLC0415

    path = tmp_path / "owned.txt"
    path.touch()
    owner = api.platform.owner_of(path)
    assert owner
    tree = api.scan(api.ScanRequest([tmp_path])).tree
    view = api.TreeView(tree, api.ViewOptions(resolve_owner=True))
    root = tree.roots()[0]
    view.expand(root)
    assert all(row[11] == owner for row in view.rows(0, 10))

    fresh = api.scan(api.ScanRequest([tmp_path])).tree
    # Owner predicates are globs. Quote the account's literal backslash.
    owner_pattern = owner.replace("\\", "\\\\")
    filtered = api.TreeView(
        fresh,
        api.ViewOptions(filter=api.FilterSpec(kind=api.FilterKind.OWNER, values=(owner_pattern,))),
    )
    filtered.expand(fresh.roots()[0])
    assert filtered.row_count == len(fresh) - 1

    report_tree = api.scan(api.ScanRequest([tmp_path])).tree
    stream = io.BytesIO()
    api.write_json(report_tree, stream, include_owner=True)
    report = json.loads(stream.getvalue())
    assert report["roots"][0]["owner"] == owner
    assert report["roots"][0]["children"][0]["owner"] == owner
