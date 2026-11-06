"""Tests for locale negotiation and gettext helpers."""

import runpy
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest
from babel.messages.catalog import Catalog
from babel.messages.pofile import read_po, write_po

from dafree.i18n import _, _file_count_label, current_locale, is_rtl, setup


@pytest.fixture(autouse=True)
def reset_locale() -> None:
    """Keep locale state from leaking between tests."""
    setup("en_US")
    yield
    setup("en_US")


def test_fallback_to_english() -> None:
    """Unsupported locales select English and preserve source messages."""
    assert setup("fr_FR") == "en_US"
    assert current_locale() == "en_US"
    assert _("Untranslated source text") == "Untranslated source text"


def test_arabic_is_rtl() -> None:
    """Arabic regional locale tags negotiate the Arabic catalogue and RTL layout."""
    assert setup("ar-EG") == "ar"
    assert is_rtl()
    assert is_rtl("he_IL")
    assert is_rtl("fa_IR")
    assert is_rtl("ur-PK")
    assert not is_rtl("de_DE")


def test_german_plural() -> None:
    """The compiled German catalogue translates singular and plural file labels."""
    assert setup("de_DE.UTF-8") == "de"
    assert _file_count_label(1) == "Datei"
    assert _file_count_label(2) == "Dateien"


def test_i18n_check_detects_placeholder_mismatch(tmp_path: Path) -> None:
    """A translation that changes a format key is rejected by the catalogue checker."""
    source_dir = tmp_path / "src" / "dafree"
    i18n_dir = source_dir / "i18n"
    locale_dir = i18n_dir / "locales" / "de" / "LC_MESSAGES"
    locale_dir.mkdir(parents=True)
    (source_dir / "messages.py").write_text(
        "from dafree.i18n import ngettext\n"
        "def file_count(count: int) -> str:\n"
        '    return ngettext("{count} file", "{count} files", count)\n',
        encoding="utf-8",
    )
    template_path = i18n_dir / "dafree.pot"
    subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "babel.messages.frontend",
            "extract",
            "--keywords=_",
            "--keywords=ngettext:1,2",
            "--no-location",
            "--sort-output",
            "--output-file",
            str(template_path),
            str(source_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    german = Catalog(locale="de")
    german.add(
        ("{count} file", "{count} files"),
        string=("{anzahl} Datei", "{anzahl} Dateien"),
    )
    with (locale_dir / "dafree.po").open("wb") as catalogue_file:
        write_po(catalogue_file, german)

    checker = Path(__file__).parents[2] / "tools" / "i18n_check.py"
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(checker), "--root", str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "format placeholder mismatch" in result.stderr


def test_normalized_template_preserves_valid_po_header() -> None:
    """A reproducible timestamp must retain the PO header's literal newline escape."""
    checker = Path(__file__).parents[2] / "tools" / "i18n_check.py"
    normalize = runpy.run_path(str(checker))["_normalise_pot"]
    original = "\n".join(
        [
            'msgid ""',
            'msgstr ""',
            '"Project-Id-Version: test 1.0\\n"',
            '"POT-Creation-Date: 2026-11-06 10:00+0000\\n"',
            '"Content-Type: text/plain; charset=utf-8\\n"',
            "",
        ]
    )
    normalized = normalize(original)
    catalogue = read_po(StringIO(normalized))
    assert catalogue.creation_date.isoformat().startswith("2000-01-01")
    assert catalogue.project == "test"
    assert normalize(normalized) == normalized


@pytest.mark.parametrize("language", ["en_US", "ar", "de"])
def test_shipped_catalogues_are_complete(language: str) -> None:
    """Every extracted message has all translated forms and no fuzzy flags."""
    directory = Path(__file__).parents[2] / "src" / "dafree" / "i18n"
    with (directory / "dafree.pot").open(encoding="utf8") as stream:
        template = read_po(stream)
    with (directory / "locales" / language / "LC_MESSAGES" / "dafree.po").open(
        encoding="utf8"
    ) as stream:
        catalogue = read_po(stream)
    assert {m.id for m in catalogue if m.id} == {m.id for m in template if m.id}
    for message in catalogue:
        if not message.id:
            continue
        forms = message.string if isinstance(message.string, tuple) else (message.string,)
        assert len(forms) == (catalogue.num_plurals if isinstance(message.id, tuple) else 1)
        assert all(forms), message.id
        assert not message.fuzzy, message.id
        assert not list(message.check(catalogue)), message.id
