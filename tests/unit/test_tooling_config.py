"""Checks for project tooling configuration."""

import tomllib
from pathlib import Path


def test_banned_api_rule_configured() -> None:
    """Unsafe recursive deletion and shell APIs stay banned by Ruff."""
    project_root = Path(__file__).parents[2]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    banned_apis = pyproject["tool"]["ruff"]["lint"]["flake8-tidy-imports"]["banned-api"]

    assert "shutil.rmtree" in banned_apis
    assert "os.system" in banned_apis
