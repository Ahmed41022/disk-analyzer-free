"""Check script generation and the completion protocol for every supported shell."""

import pytest
from click.testing import CliRunner

from dafree.cli.exit_codes import Exit
from dafree.cli.main import cli


@pytest.mark.parametrize(
    ("shell", "registration", "word", "expected"),
    [
        ("bash", "complete -o", "1", "plain,scan"),
        ("zsh", "compdef", "1", "plain\nscan\n"),
        ("fish", "complete --no-files", "sc", "plain,scan"),
        ("powershell", "Register-ArgumentCompleter", "1", "plain\nscan\n"),
    ],
)
def test_completion_scripts_generate(
    shell: str, registration: str, word: str, expected: str
) -> None:
    runner = CliRunner()
    source = runner.invoke(cli, ["completion", shell], prog_name="dafree")
    assert source.exit_code == Exit.OK, source.output
    assert registration in source.stdout and "_DAFREE_COMPLETE" in source.stdout
    assert not source.stderr

    suggestions = runner.invoke(
        cli,
        prog_name="dafree",
        env={
            "_DAFREE_COMPLETE": f"{shell}_complete",
            "COMP_WORDS": "dafree sc",
            "COMP_CWORD": word,
        },
    )
    assert suggestions.exit_code == Exit.OK, suggestions.output
    assert expected in suggestions.stdout
    assert not suggestions.stderr
