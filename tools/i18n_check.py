"""Check gettext catalogues against source messages and placeholders."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from string import Formatter

from babel.messages.catalog import Catalog, Message
from babel.messages.pofile import read_po

_POT_DATE = re.compile(r'(?m)^"POT-Creation-Date: .*\\n"$')


def _load_catalog(path: Path) -> Catalog:
    """Read a gettext catalogue from a UTF-8 PO or POT file."""
    with path.open(encoding="utf-8") as catalogue_file:
        return read_po(catalogue_file)


def _normalise_pot(content: str) -> str:
    """Remove the generated timestamp so template comparisons are reproducible."""
    normalized = _POT_DATE.sub('"POT-Creation-Date: 2000-01-01 00:00+0000\\n"', content)
    return normalized.rstrip("\n") + "\n"


def _extract_pot(source_dir: Path, output_file: Path) -> None:
    """Extract Python gettext messages into a POT file."""
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
            str(output_file),
            str(source_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _message_placeholders(message: str) -> Counter[str]:
    """Collect named and positional Python format placeholders in a message."""
    placeholders: Counter[str] = Counter()
    try:
        for _, field_name, _, _ in Formatter().parse(message):
            if field_name is not None:
                placeholders[field_name.split(".", maxsplit=1)[0].split("[", maxsplit=1)[0]] += 1
    except ValueError:
        placeholders["<invalid-format-string>"] += 1
    return placeholders


def _message_texts(message: Message) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return source and translated text forms for singular or plural messages."""
    source = message.id if isinstance(message.id, tuple) else (message.id,)
    translated = message.string if isinstance(message.string, tuple) else (message.string,)
    return source, translated


def check_catalogue(
    template: Catalog, catalogue: Catalog, locale_name: str
) -> tuple[list[str], list[str]]:
    """Return errors and missing-translation warnings for one locale catalogue."""
    template_ids = {message.id for message in template if message.id}
    errors: list[str] = []
    warnings: list[str] = []

    for message in catalogue:
        if not message.id:
            continue
        if message.id not in template_ids:
            errors.append(f"{locale_name}: unknown msgid {message.id!r}")
            continue

        source_forms, translated_forms = _message_texts(message)
        if not any(translated_forms):
            warnings.append(f"{locale_name}: missing translation for {message.id!r}")
            continue

        source_singular = source_forms[0]
        source_plural = source_forms[-1]
        for index, translated in enumerate(translated_forms):
            if not translated:
                warnings.append(f"{locale_name}: missing plural form {index} for {message.id!r}")
                continue
            source = source_singular if index == 0 else source_plural
            if _message_placeholders(source) != _message_placeholders(translated):
                errors.append(
                    f"{locale_name}: format placeholder mismatch for {message.id!r} "
                    f"in translation form {index}"
                )

    return errors, warnings


def check_project(root: Path) -> tuple[list[str], list[str]]:
    """Extract messages and validate the checked-in template and locale catalogues."""
    i18n_dir = root / "src" / "dafree" / "i18n"
    template_path = i18n_dir / "dafree.pot"
    source_dir = root / "src" / "dafree"
    errors: list[str] = []
    warnings: list[str] = []

    with tempfile.TemporaryDirectory(prefix="dafree-i18n-", dir=root) as temporary_directory:
        extracted_path = Path(temporary_directory) / "dafree.pot"
        try:
            _extract_pot(source_dir, extracted_path)
        except (OSError, subprocess.CalledProcessError) as error:
            return [f"could not extract gettext messages: {error}"], warnings

        expected = _normalise_pot(extracted_path.read_text(encoding="utf-8"))
        try:
            committed = _normalise_pot(template_path.read_text(encoding="utf-8"))
        except OSError as error:
            return [f"could not read {template_path}: {error}"], warnings
        if expected != committed:
            errors.append(
                f"{template_path.relative_to(root)} is stale; regenerate it with pybabel extract"
            )

    try:
        template = _load_catalog(template_path)
    except OSError as error:
        return [*errors, f"could not parse {template_path}: {error}"], warnings

    locales_dir = i18n_dir / "locales"
    for locale_dir in sorted(path for path in locales_dir.iterdir() if path.is_dir()):
        po_path = locale_dir / "LC_MESSAGES" / "dafree.po"
        try:
            catalogue = _load_catalog(po_path)
        except OSError as error:
            errors.append(f"could not read {po_path}: {error}")
            continue
        locale_errors, locale_warnings = check_catalogue(template, catalogue, locale_dir.name)
        errors.extend(locale_errors)
        warnings.extend(locale_warnings)

    return errors, warnings


def main() -> int:
    """Run the catalogue consistency check and return a process status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="project root (defaults to the repository containing this script)",
    )
    args = parser.parse_args()
    errors, warnings = check_project(args.root.resolve())

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    print(f"Validated gettext catalogues with {len(warnings)} missing-translation warning(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
