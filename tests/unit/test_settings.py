"""Shared preference persistence, migrations, typed edits, and CLI behavior."""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from dafree.api import ScanMode, UnitMode, UnitSystem
from dafree.cli.exit_codes import ExitCode
from dafree.cli.main import cli
from dafree.paths import AppPaths, detect
from dafree.settings import (
    Settings,
    UnsupportedSettingsVersion,
    get_dotted,
    load_settings,
    save_settings,
    set_dotted,
)

_THREADS = 4
_WINDOW_X = -50


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """Every preference and backup remains in a test-owned directory."""
    return AppPaths(
        tmp_path / "config", tmp_path / "data", tmp_path / "logs", tmp_path / "snap", False
    )


def test_settings_atomic_write(paths: AppPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace only a complete flushed sibling file while the old file remains readable."""
    save_settings(Settings(theme="light"), paths)
    target = paths.config / "settings.json"
    old = target.read_bytes()
    replace = os.replace
    calls = []
    fsynced = []
    fsync = os.fsync

    def inspect_fsync(descriptor: int) -> None:
        fsynced.append(os.fstat(descriptor).st_size)
        fsync(descriptor)

    def inspect_replace(source: Any, destination: Any) -> None:
        source, destination = Path(source), Path(destination)
        assert destination == target
        assert source.parent == destination.parent
        assert target.read_bytes() == old
        assert len(fsynced) == 1 and fsynced[0] > 0
        assert json.loads(source.read_text(encoding="utf-8"))["theme"] == "dark"
        calls.append(source)
        replace(source, destination)

    monkeypatch.setattr(os, "replace", inspect_replace)
    monkeypatch.setattr(os, "fsync", inspect_fsync)
    save_settings(Settings(theme="dark"), paths)
    assert len(calls) == 1
    assert load_settings(paths).theme == "dark"
    assert not list(paths.config.glob(".settings-*.tmp"))


def test_failed_write_preserves_original(paths: AppPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed atomic replace leaves valid old preferences and cleans its temporary file."""
    save_settings(Settings(), paths)
    target = paths.config / "settings.json"
    old = target.read_bytes()

    def fail_replace(source: Any, destination: Any) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        save_settings(Settings(theme="dark"), paths)
    assert target.read_bytes() == old
    assert not list(paths.config.glob(".settings-*.tmp"))


@pytest.mark.parametrize("raw", [b"{broken", b"\xff", b"[]", b'{"default_scan":{"threads":true}}'])
def test_corrupt_settings_backed_up(paths: AppPaths, raw: bytes) -> None:
    """Malformed JSON, UTF-8, shape, and field types are preserved in a backup."""
    paths.config.mkdir()
    source = paths.config / "settings.json"
    source.write_bytes(raw)
    assert load_settings(paths) == Settings()
    backups = list(paths.config.glob("settings.json.bad-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == raw
    assert not source.exists()
    assert load_settings(paths) == Settings()
    assert len(list(paths.config.glob("settings.json.bad-*"))) == 1


def test_corrupt_backup_collision_preserves_both(
    paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two corrupt files in the same second never overwrite the earlier backup."""
    paths.config.mkdir()
    monkeypatch.setattr("dafree.settings.time.time", lambda: 1234)
    for raw in (b"first", b"second"):
        (paths.config / "settings.json").write_bytes(raw)
        load_settings(paths)
    assert {p.read_bytes() for p in paths.config.glob("settings.json.bad-*")} == {
        b"first",
        b"second",
    }


@pytest.mark.parametrize("version", [None, 0])
def test_migration_v0_to_v1(paths: AppPaths, version: int | None) -> None:
    """Unversioned/v0 known values survive while missing fields receive v1 defaults."""
    paths.config.mkdir()
    old: dict[str, Any] = {"theme": "dark", "default_scan": {"threads": _THREADS}, "units": "mega"}
    if version is not None:
        old["version"] = version
    target = paths.config / "settings.json"
    target.write_text(json.dumps(old), encoding="utf-8")
    settings = load_settings(paths)
    assert settings.version == 1
    assert settings.theme == "dark"
    assert settings.default_scan.threads == _THREADS
    assert settings.default_scan.mode == ScanMode.AUTO
    assert settings.units == UnitMode.MEGA
    assert json.loads(target.read_text(encoding="utf-8")) == old
    save_settings(settings, paths)
    assert json.loads(target.read_text(encoding="utf-8"))["version"] == 1


def test_future_version_is_not_renamed_or_overwritten(paths: AppPaths) -> None:
    """A newer application retains ownership of its schema and data."""
    paths.config.mkdir()
    target = paths.config / "settings.json"
    raw = b'{"version":2,"new_field":"retain me"}'
    target.write_bytes(raw)
    with pytest.raises(UnsupportedSettingsVersion):
        load_settings(paths)
    assert target.read_bytes() == raw
    assert not list(paths.config.glob("*.bad-*"))


def test_settings_nested_roundtrip_and_independent_defaults(paths: AppPaths) -> None:
    """Enums, optional models, container edits, and raw filesystem names round-trip."""
    original = Settings()
    changed = set_dotted(original, "default_scan.mode", "walk")
    changed = set_dotted(changed, "unit_style.system", "iec")
    changed = set_dotted(
        changed, "window", json.dumps({"width": 900, "height": 600, "x": _WINDOW_X})
    )
    changed = set_dotted(changed, "shortcuts.new_scan", '"Ctrl+N"')
    changed = set_dotted(changed, "columns.0.width", "400")
    changed.recent_targets = ["العربية/ß", "raw-\udcff"]
    save_settings(changed, paths)
    loaded = load_settings(paths)
    assert loaded == changed
    assert loaded.unit_style.system == UnitSystem.IEC
    assert get_dotted(loaded, "window.x") == _WINDOW_X
    assert original == Settings()
    assert original.default_scan.mode == ScanMode.AUTO
    assert original.shortcuts == {}


def test_recent_targets_limit(paths: AppPaths) -> None:
    """Keep the first ten (most recent) targets in stored preferences."""
    settings = Settings(recent_targets=[f"target-{i}" for i in range(15)])
    save_settings(settings, paths)
    assert load_settings(paths).recent_targets == settings.recent_targets[:10]


@pytest.mark.parametrize(
    ("key", "raw"),
    [
        ("theme", "blue"),
        ("default_scan.threads", "true"),
        ("default_scan.threads", "-1"),
        ("delete_to_trash_default", "0"),
        ("locale", "42"),
        ("default_scan.mode", "unknown"),
        ("columns.0.width", "0"),
        ("columns", "[]"),
        ("treemap.padding", "NaN"),
        ("treemap.padding", "Infinity"),
        ("treemap.padding", "-1"),
        ("unit_style.decimal_separator", "ab"),
        ("recent_targets", '["ok",1]'),
        ("shortcuts.foo", "12"),
        ("default_scan.exclude.unknown", "true"),
        ("unknown", "1"),
        ("window.width", "-1"),
        ("columns.-1.width", "10"),
        ("version", "0"),
        ("__class__", "anything"),
        ("theme..x", "1"),
    ],
)
def test_invalid_typed_edit_keeps_original(key: str, raw: str) -> None:
    """Invalid preferences do not mutate the original object."""
    original = Settings()
    with pytest.raises(ValueError):
        set_dotted(original, key, raw)
    assert original == Settings()


def test_config_set_get_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI invocations share the same typed preferences file in the sandbox."""
    monkeypatch.setenv("DAFREE_CONFIG_DIR", str(tmp_path))
    runner = CliRunner()
    for key, raw, expected in (("theme", "dark", "dark"), ("default_scan.threads", "4", 4)):
        result = runner.invoke(cli, ["config", "set", key, raw])
        assert result.exit_code == 0, result.output
        result = runner.invoke(cli, ["config", "get", key])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == expected
    path_result = runner.invoke(cli, ["config", "path"])
    assert path_result.exit_code == 0
    assert Path(path_result.output.strip()) == tmp_path / "settings.json"
    assert load_settings(detect()).theme == "dark"


def test_config_set_invalid_type_exit_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An invalid type is a usage error and leaves the existing file unchanged."""
    monkeypatch.setenv("DAFREE_CONFIG_DIR", str(tmp_path))
    save_settings(Settings(), detect())
    target = tmp_path / "settings.json"
    old = target.read_bytes()
    result = CliRunner().invoke(cli, ["config", "set", "default_scan.threads", "many"])
    assert result.exit_code == ExitCode.USAGE
    assert "threads" in result.output
    assert target.read_bytes() == old
    assert CliRunner().invoke(cli, ["config", "get", "missing"]).exit_code == ExitCode.USAGE


def test_paths_detection_is_non_creating(tmp_path: Path) -> None:
    """The test override isolates every application path and does not create it."""
    root = tmp_path / "isolated"
    paths = detect(env={"DAFREE_CONFIG_DIR": str(root)})
    assert paths.config == root
    assert all(p.is_relative_to(root) for p in (paths.data, paths.logs, paths.snapshots))
    assert not root.exists()
    assert not paths.portable
    with pytest.raises(NotImplementedError, match="Portable"):
        detect(cli_flag=True, env={})


def test_normal_paths_use_platformdirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the planned app ID without creating real user directories."""
    calls = []

    def config_dir(appname: str, *, appauthor: bool) -> str:
        calls.append((appname, appauthor))
        return str(tmp_path / "config")

    def data_dir(appname: str, *, appauthor: bool) -> str:
        calls.append((appname, appauthor))
        return str(tmp_path / "data")

    monkeypatch.setattr("dafree.paths.platformdirs.user_config_dir", config_dir)
    monkeypatch.setattr("dafree.paths.platformdirs.user_data_dir", data_dir)
    paths = detect(env={})
    assert paths.config == tmp_path / "config"
    assert paths.logs == tmp_path / "data" / "logs"
    assert paths.snapshots == tmp_path / "data" / "snapshots"
    assert calls == [("disk-analyzer-free", False), ("disk-analyzer-free", False)]
    assert list(tmp_path.iterdir()) == []


def test_config_path_does_not_create_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Path inspection is read-only, including an unsupported portable request."""
    directory = tmp_path / "not-created"
    monkeypatch.setenv("DAFREE_CONFIG_DIR", str(directory))
    result = CliRunner().invoke(cli, ["config", "path"])
    assert result.exit_code == 0
    assert Path(result.output.strip()) == directory / "settings.json"
    monkeypatch.setenv("DAFREE_PORTABLE", "1")
    result = CliRunner().invoke(cli, ["config", "path"])
    assert result.exit_code == ExitCode.USAGE
    assert not directory.exists()
