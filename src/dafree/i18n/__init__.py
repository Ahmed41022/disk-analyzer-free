"""gettext setup and helpers shared by the CLI and desktop interface."""

from __future__ import annotations

import gettext
import locale as _locale
import os
from dataclasses import dataclass, field
from pathlib import Path

_LOCAL_DIR = Path(__file__).parent / "locales"
_SUPPORTED = {"en": "en_US", "ar": "ar", "de": "de"}
_RTL_LANGUAGES = {"ar", "he", "fa", "ur"}


@dataclass(slots=True)
class _LocaleState:
    """Hold the selected locale and catalogue as one mutable process state."""

    locale: str = "en_US"
    translation: gettext.NullTranslations = field(default_factory=gettext.NullTranslations)


_state = _LocaleState()


def _language_tag(value: str | None) -> str:
    """Return the normalized language portion of a locale tag."""
    if value is None:
        return ""
    language = value.strip().split(".", maxsplit=1)[0].split("@", maxsplit=1)[0]
    return language.replace("-", "_").split("_", maxsplit=1)[0].lower()


def _candidate_locale() -> str | None:
    """Return the first configured process locale without changing process state."""
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
        candidate = os.environ.get(variable)
        if candidate:
            return candidate
    try:
        return _locale.getlocale()[0]
    except (ValueError, TypeError):
        return None


def _negotiate_locale(candidate: str | None) -> str:
    """Map a requested locale to a shipped catalogue or the English fallback."""
    value = candidate if candidate is not None else _candidate_locale()
    language = _language_tag(value)
    return _SUPPORTED.get(language, "en_US")


def setup(locale: str | None = None) -> str:
    """Select the closest shipped translation and return its canonical locale."""
    selected_locale = _negotiate_locale(locale)
    translation = gettext.translation(
        "dafree",
        localedir=_LOCAL_DIR,
        languages=[selected_locale],
        fallback=True,
    )
    _state.locale = selected_locale
    _state.translation = translation
    return selected_locale


def _(msg: str) -> str:
    """Translate a message, falling back to the original English text."""
    return _state.translation.gettext(msg)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Translate a singular or plural message using the active locale rules."""
    return _state.translation.ngettext(singular, plural, n)


def is_rtl(locale: str | None = None) -> bool:
    """Return whether a locale uses a right-to-left writing direction."""
    candidate = _state.locale if locale is None else locale
    return _language_tag(candidate) in _RTL_LANGUAGES


def current_locale() -> str:
    """Return the canonical locale currently selected by :func:`setup`."""
    return _state.locale


def _file_count_label(count: int) -> str:
    """Translate the generic file-count plural used to validate catalogue forms."""
    return ngettext("file", "files", count)


__all__ = ["_", "current_locale", "is_rtl", "ngettext", "setup"]
