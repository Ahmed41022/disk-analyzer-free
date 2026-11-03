"""Exercise the CLI framework through Click's command entry point."""

from pathlib import Path

import click
import pytest
from click.testing import CliRunner
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.single_file import SingleFileSnapshotExtension

from dafree import __version__, api
from dafree.cli.exit_codes import Exit
from dafree.cli.main import CliState, cli
from dafree.cli.progress import set_active_scan


class HelpSnapshot(SingleFileSnapshotExtension):
    """Store the exact help text without serializer indentation."""

    file_extension = "txt"


def test_help_snapshot(snapshot: SnapshotAssertion) -> None:
    result = CliRunner().invoke(cli, ["--help"], prog_name="dafree", terminal_width=80)
    assert result.exit_code == Exit.OK
    assert result.output.encode("utf8") == snapshot(extension_class=HelpSnapshot)


def test_bad_flag_exit_2() -> None:
    result = CliRunner().invoke(cli, ["--bad-option"])
    assert result.exit_code == Exit.USAGE
    assert "No such option" in result.stderr and "--bad-option" in result.stderr


def test_version_matches_package() -> None:
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == Exit.OK
    assert result.stdout == f"dafree, version {__version__}\n"


def test_dafree_error_exit_1(monkeypatch: pytest.MonkeyPatch) -> None:
    @click.command()
    def fail() -> None:
        raise api.DafreeError("cannot read target")

    monkeypatch.setitem(cli.commands, "fail", fail)
    result = CliRunner().invoke(cli, ["fail"])
    assert result.exit_code == Exit.RUNTIME
    assert result.stdout == ""
    assert result.stderr == "Error: cannot read target\n"


def test_toml_defaults_and_explicit_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "defaults.toml"
    path.write_text('threads = 7\nunits = "mb"\nprogress = "never"\nsi = true\n', encoding="utf8")
    observed: list[CliState] = []

    @click.command()
    @click.pass_obj
    def probe(state: CliState) -> None:
        observed.append(state)

    monkeypatch.setitem(cli.commands, "probe", probe)
    explicit_threads = 3
    result = CliRunner().invoke(
        cli,
        [
            "--threads",
            str(explicit_threads),
            "--config",
            str(path),
            "--iec-labels",
            "-vv",
            "-q",
            "probe",
        ],
    )
    assert result.exit_code == Exit.OK, result.output
    assert len(observed) == 1
    state = observed[0]
    assert state.format == "json" and not state.color
    assert state.units == api.UnitMode.MEGA
    assert state.unit_style.system == api.UnitSystem.IEC
    assert state.threads == explicit_threads and state.progress == "never"
    assert state.config == path and state.verbosity == 1


@pytest.mark.parametrize("toml", ['threads = "oops"', "unknown = true", "[malformed"])
def test_invalid_global_defaults_are_usage_errors(tmp_path: Path, toml: str) -> None:
    path = tmp_path / "defaults.toml"
    path.write_text(toml, encoding="utf8")
    result = CliRunner().invoke(cli, ["--config", str(path), "config", "path"])
    assert result.exit_code == Exit.USAGE
    assert result.stdout == ""
    assert "Error:" in result.stderr


def test_keyboard_interrupt_cancels_once_and_preserves_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Scan:
        def cancel(self) -> None:
            events.append("cancelled")

    @click.command()
    @click.pass_context
    def stop(ctx: click.Context) -> None:
        set_active_scan(ctx, Scan())
        click.echo("partial output")
        raise KeyboardInterrupt

    monkeypatch.setitem(cli.commands, "stop", stop)
    result = CliRunner().invoke(cli, ["stop"])
    assert result.exit_code == Exit.INTERRUPTED
    assert result.stdout == "partial output\n"
    assert events == ["cancelled"]


def test_unit_flags_conflict_and_portable_is_explicit() -> None:
    runner = CliRunner()
    conflict = runner.invoke(cli, ["--si", "--iec-labels", "config", "path"])
    assert conflict.exit_code == Exit.USAGE
    assert "cannot be combined" in conflict.stderr
    portable = runner.invoke(cli, ["--portable", "config", "path"])
    assert portable.exit_code == Exit.USAGE
    assert "Portable mode is not available yet" in portable.stderr
