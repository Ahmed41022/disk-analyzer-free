"""Plain name-substring queries; the structured grammar is deferred to T6.1."""

from dataclasses import dataclass
from datetime import datetime

from dafree import api
from dafree.api.errors import QueryError as QueryError
from dafree.i18n import N_


@dataclass(frozen=True)
class Query:
    """A canonical literal substring compiled to the existing native name-glob filter."""

    text: str

    def to_filter_spec(self) -> api.FilterSpec:
        """Escape glob metacharacters so the input remains a literal substring."""
        if not self.text:
            return api.FilterSpec()
        escaped = "".join("\\" + char if char in "\\*?[]" else char for char in self.text)
        return api.FilterSpec(kind=api.FilterKind.NAME_GLOB, values=(f"*{escaped}*",))

    def needs_owner(self) -> bool:
        """Name-substring searches never require owner resolution."""
        return False

    def __str__(self) -> str:
        """Return the normalized substring for lossless query roundtrips."""
        return self.text


def parse(
    text: str, *, si: bool = False, now: datetime | None = None, max_depth: int = 32
) -> Query:
    """Parse a literal name substring using the planned parser entry point.

    Unit/date arguments are reserved for T6.1; no field/operator grammar is
    interpreted yet. Outer whitespace is ignored; inner whitespace is literal.
    Error spans refer to the original Python string, before normalization.
    """
    if max_depth < 1:
        raise ValueError("max_depth must be positive")
    if (index := text.find("\0")) >= 0:
        raise QueryError((index, index + 1), N_("Search text cannot contain a NUL character."))
    return Query(text.strip())
