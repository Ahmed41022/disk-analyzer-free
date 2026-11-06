"""End-to-end checks for the installed and frozen scan self-test entry point."""

import json
import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

import pytest

if find_spec("PySide6") is None:
    if os.environ.get("DAFREE_REQUIRE_GUI") == "1":
        pytest.fail("PySide6 is required when DAFREE_REQUIRE_GUI=1", pytrace=False)
    pytest.skip("PySide6 is not installed", allow_module_level=True)

pytestmark = pytest.mark.gui

_TIMEOUT_SECONDS = 75
_UINT64_MAX = (1 << 64) - 1


def _command() -> list[str]:
    """Use the requested frozen executable, or always exercise the installed package."""
    executable = os.environ.get("DAFREE_FROZEN_EXECUTABLE")
    if executable:
        return [executable]
    return [sys.executable, "-m", "dafree.gui.app"]


def _run_self_test(
    directory: Path,
    expected_size: str | int,
    *,
    env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    child_env = os.environ.copy() if env is None else env.copy()
    runtime = directory.parent / "runtime"
    runtime.mkdir(exist_ok=True)
    child_env.update(
        TMPDIR=str(runtime), TMP=str(runtime), TEMP=str(runtime), PYTHONDONTWRITEBYTECODE="1"
    )
    # The hook must select offscreen mode itself, even when the caller has a bad value.
    child_env.setdefault("QT_QPA_PLATFORM", "offscreen")
    command = [
        *_command(),
        "--self-test",
        str(directory),
        "--expect-size",
        str(expected_size),
    ]
    completed = subprocess.run(  # noqa: S603 -- fixed command prefix, test-owned path, no shell.
        command,
        capture_output=True,
        check=False,
        cwd=Path(__file__).resolve().parents[2],
        env=child_env,
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"self-test did not emit one JSON object on stdout: {exc}; "
            f"stdout={completed.stdout!r}; stderr={completed.stderr!r}",
            pytrace=False,
        )
    assert isinstance(payload, dict), f"expected JSON object, got {payload!r}"
    assert set(payload) == {"ok", "name", "size", "expected_size", "error"}
    assert type(payload["ok"]) is bool
    assert payload["error"] is None or isinstance(payload["error"], str)
    assert payload["name"] is None or isinstance(payload["name"], str)
    for key in ("size", "expected_size"):
        assert payload[key] is None or type(payload[key]) is int
    return completed, payload


def _assert_result(
    completed: subprocess.CompletedProcess[str],
    payload: dict[str, object],
    expected_exit: int,
    expected: dict[str, object],
) -> None:
    assert completed.returncode == expected_exit, completed.stderr
    assert payload == expected


@pytest.fixture
def unicode_scan_target(tmp_path: Path) -> tuple[Path, int]:
    """Build then rename a nested Unicode target with both empty and populated files."""
    original = tmp_path / "scan-target"
    nested = original / "資料" / "éléments"
    nested.mkdir(parents=True)
    (original / "empty-file.dat").write_bytes(b"")
    contents = b"raw bytes: \x00\xff\n"
    (nested / "résumé.bin").write_bytes(contents)
    target = tmp_path / "分析対象-é"
    original.rename(target)
    return target, len(contents)


def test_frozen_selftest(unicode_scan_target: tuple[Path, int]) -> None:
    target, size = unicode_scan_target
    completed, payload = _run_self_test(target, size)
    _assert_result(
        completed,
        payload,
        0,
        {"ok": True, "name": target.name, "size": size, "expected_size": size, "error": None},
    )


def test_self_test_reports_size_mismatch(
    unicode_scan_target: tuple[Path, int],
) -> None:
    target, size = unicode_scan_target
    expected = size + 1
    completed, payload = _run_self_test(target, expected)
    _assert_result(
        completed,
        payload,
        1,
        {
            "ok": False,
            "name": target.name,
            "size": size,
            "expected_size": expected,
            "error": payload["error"],
        },
    )
    assert payload["error"]


def test_self_test_accepts_empty_directory(tmp_path: Path) -> None:
    target = tmp_path / "empty-資料"
    target.mkdir()
    completed, payload = _run_self_test(target, 0)
    _assert_result(
        completed,
        payload,
        0,
        {"ok": True, "name": target.name, "size": 0, "expected_size": 0, "error": None},
    )


def test_self_test_normalizes_dotdot_paths(unicode_scan_target: tuple[Path, int]) -> None:
    """Lexical path normalization preserves the requested directory without resolving links."""
    target, size = unicode_scan_target
    spare = target.parent / "spare"
    spare.mkdir()
    completed, payload = _run_self_test(spare / ".." / target.name, size)
    assert completed.returncode == 0, completed.stderr
    assert payload["ok"] is True
    assert payload["name"] == target.name
    assert payload["size"] == size


@pytest.mark.parametrize("invalid_target", ["missing", "file"], ids=["nonexistent", "file"])
def test_self_test_rejects_invalid_target(tmp_path: Path, invalid_target: str) -> None:
    target = tmp_path / "target"
    if invalid_target == "file":
        target.write_bytes(b"not a directory")
    else:
        target = tmp_path / "missing"
    completed, payload = _run_self_test(target, 0)
    _assert_result(
        completed,
        payload,
        1,
        {
            "ok": False,
            "name": target.name,
            "size": None,
            "expected_size": 0,
            "error": payload["error"],
        },
    )
    assert payload["error"]


@pytest.mark.parametrize("value", ["not-a-number", "-1", str(_UINT64_MAX + 1)])
def test_self_test_rejects_invalid_expected_size(
    tmp_path: Path,
    value: str,
) -> None:
    target = tmp_path / "valid-target"
    target.mkdir()
    completed, payload = _run_self_test(target, value)
    _assert_result(
        completed,
        payload,
        1,
        {
            "ok": False,
            "name": target.name,
            "size": None,
            "expected_size": None,
            "error": payload["error"],
        },
    )
    assert payload["error"]


def test_self_test_does_not_touch_caller_config_or_qpa(
    tmp_path: Path,
    unicode_scan_target: tuple[Path, int],
) -> None:
    target, size = unicode_scan_target
    caller_config = tmp_path / "caller-config"
    caller_config.mkdir()
    settings = caller_config / "settings.json"
    original = b'{"marker": "leave unchanged", "unicode": "\xe2\x98\x83"}\n'
    settings.write_bytes(original)
    env = os.environ.copy()
    env["DAFREE_CONFIG_DIR"] = str(caller_config)
    env["QT_QPA_PLATFORM"] = "dafree-invalid-platform"

    completed, payload = _run_self_test(target, size, env=env)

    _assert_result(
        completed,
        payload,
        0,
        {"ok": True, "name": target.name, "size": size, "expected_size": size, "error": None},
    )
    assert settings.read_bytes() == original
    assert list(caller_config.iterdir()) == [settings]
