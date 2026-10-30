import enum

def version() -> str:
    """Return the installed package version."""

class UnitMode(enum.Enum):
    AUTO = 0

    BYTES = 1

    KILO = 2

    MEGA = 3

    GIGA = 4

    TERA = 5

    PETA = 6

    EXA = 7

class UnitSystem(enum.Enum):
    TRADITIONAL = 0

    IEC = 1

    SI = 2

class UnitStyle:
    def __init__(self, system: UnitSystem, decimal_separator: str) -> None: ...
    @property
    def system(self) -> UnitSystem: ...
    @system.setter
    def system(self, arg: UnitSystem, /) -> None: ...
    @property
    def decimal_separator(self) -> str: ...
    @decimal_separator.setter
    def decimal_separator(self, arg: str, /) -> None: ...

def format_size(bytes: int, mode: UnitMode, style: UnitStyle) -> str:
    """Format a byte count."""

def parse_size(text: str, style: UnitStyle) -> int:
    """Parse a byte count."""
