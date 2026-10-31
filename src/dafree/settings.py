"""Typed shared preferences, JSON migrations, and atomic persistence."""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum, StrEnum
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, cast, get_args, get_origin, get_type_hints

from dafree.api import HardlinkMode, OwnerMode, ScanMode, UnitMode, UnitStyle
from dafree.i18n import _
from dafree.paths import AppPaths

_VERSION = 1
_MAX_RECENT = 10
_U32_MAX = (1 << 32) - 1
_U64_MAX = (1 << 64) - 1


class ColumnId(StrEnum):
    """Stable identifiers for the nine planned tree-table columns."""

    NAME = "name"
    SIZE = "size"
    PCT_PARENT = "pct_parent"
    ALLOC = "alloc"
    FILES = "files"
    DIRS = "dirs"
    MTIME = "mtime"
    OWNER = "owner"
    EXT = "ext"


@dataclass
class ColumnSetting:
    """Visibility, logical width, and display order of a table column."""

    id: ColumnId
    visible: bool = True
    width: int = 120
    order: int = 0


def _columns() -> list[ColumnSetting]:
    widths = (320, 120, 160, 120, 90, 90, 180, 160, 90)
    hidden = {ColumnId.OWNER, ColumnId.EXT}
    return [
        ColumnSetting(column, column not in hidden, width, order)
        for order, (column, width) in enumerate(zip(ColumnId, widths, strict=True))
    ]


@dataclass
class ExcludeRulesModel:
    """JSON-native exclusions mirrored into a scan request by its caller."""

    paths: list[str] = field(default_factory=list)
    globs: list[str] = field(default_factory=list)
    hidden: bool = False
    system: bool = False


@dataclass
class ScanOptionsModel:
    """Pure-Python persisted mirror of the public scan request options."""

    targets: list[str] = field(default_factory=list)
    mode: ScanMode = ScanMode.AUTO
    threads: int = 0
    follow_symlinks: bool = False
    cross_filesystems: bool = False
    exclude: ExcludeRulesModel = field(default_factory=ExcludeRulesModel)
    owner: OwnerMode = OwnerMode.LAZY
    hardlinks: HardlinkMode = HardlinkMode.DEDUP
    include_ads: bool = False
    show_ntfs_metafiles: bool = True


@dataclass
class DupOptionsModel:
    """Duplicate-finder defaults; query text is persisted without evaluating it."""

    min_size: int = 1 << 20
    max_size: int | None = None
    algo: Literal["blake3", "xxh3_128", "sha256"] = "blake3"
    partial_bytes: int = 16 * 1024
    include_hidden: bool = False
    same_volume_only: bool = False
    verify_bytes: bool = False
    io_threads: int = 0
    filter: str | None = None


@dataclass
class WindowState:
    """Last normal window rectangle and maximized state, without Qt types."""

    x: int = 0
    y: int = 0
    width: int = 1100
    height: int = 750
    maximized: bool = False


@dataclass
class TreemapSettings:
    """Persist the planned native treemap options without implementing layout."""

    max_depth: int = 12
    min_px: float = 3.0
    padding: float = 1.0
    header_px: float = 0.0
    max_rects: int = 50_000


@dataclass
class Settings:
    """Version-one preferences shared by every application entry point."""

    version: int = _VERSION
    theme: Literal["system", "light", "dark"] = "system"
    locale: str | None = None
    units: UnitMode = UnitMode.AUTO
    unit_style: UnitStyle = field(default_factory=UnitStyle)
    columns: list[ColumnSetting] = field(default_factory=_columns)
    default_scan: ScanOptionsModel = field(default_factory=ScanOptionsModel)
    dupes: DupOptionsModel = field(default_factory=DupOptionsModel)
    delete_to_trash_default: bool = True
    recent_targets: list[str] = field(default_factory=list)
    window: WindowState | None = None
    shortcuts: dict[str, str] = field(default_factory=dict)
    treemap: TreemapSettings = field(default_factory=TreemapSettings)
    show_ntfs_metafiles: bool = True


class UnsupportedSettingsVersion(ValueError):
    """A newer schema must remain untouched for the version that owns it."""


def _invalid(key: str, expected: str) -> ValueError:
    return ValueError(_("{key}: expected {expected}").format(key=key, expected=expected))


def _decode_generic(origin: Any, args: tuple[Any, ...], value: Any, key: str) -> Any:
    if origin in (Union, UnionType):
        for variant in args:
            try:
                return _decode(variant, value, key)
            except ValueError:
                continue
        raise _invalid(key, " | ".join(str(arg) for arg in args))
    if origin is Literal:
        if not any(type(value) is type(option) and value == option for option in args):
            raise _invalid(key, ", ".join(map(str, args)))
        return value
    if origin is list:
        if not isinstance(value, list):
            raise _invalid(key, _("list"))
        return [_decode(args[0], item, f"{key}.{index}") for index, item in enumerate(value)]
    if origin is dict:
        if not isinstance(value, dict):
            raise _invalid(key, _("object"))
        return {
            _decode(args[0], name, key): _decode(args[1], item, f"{key}.{name}")
            for name, item in value.items()
        }
    raise _invalid(key, str(origin))


def _decode_enum(schema: type[Enum], value: Any, key: str) -> Enum:
    try:
        if isinstance(value, str):
            try:
                return schema[value.upper()]
            except KeyError:
                return schema(value)
        if type(value) is int:
            return schema(value)
    except (KeyError, ValueError):
        pass
    raise _invalid(key, ", ".join(item.name.lower() for item in schema))


def _decode(schema: Any, value: Any, key: str) -> Any:
    if origin := get_origin(schema):
        return _decode_generic(origin, get_args(schema), value, key)
    if isinstance(schema, type) and issubclass(schema, Enum):
        return _decode_enum(schema, value, key)
    if is_dataclass(schema):
        names = {f.name for f in fields(schema)}
        if not isinstance(value, dict) or set(value) - names:
            raise _invalid(key, ", ".join(sorted(names)))
        hints = get_type_hints(schema)
        model = cast(type[Any], schema)
        return model(
            **{name: _decode(hints[name], item, f"{key}.{name}") for name, item in value.items()}
        )
    return _decode_scalar(schema, value, key)


def _decode_scalar(schema: Any, value: Any, key: str) -> Any:
    if schema is float:
        try:
            result = float(value) if type(value) in (int, float) else math.nan
        except OverflowError:
            result = math.nan
        if not math.isfinite(result):
            raise _invalid(key, _("finite number"))
        return result
    if type(value) is not schema:
        raise _invalid(key, getattr(schema, "__name__", str(schema)))
    return value


def _encode(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.name.lower()
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _encode(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {name: _encode(item) for name, item in value.items()}
    return value


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade unversioned/v0 preferences in memory, preserving known values.

    V0 has the same named fields; v1 adds schema metadata and fills missing
    fields from typed defaults. The upgraded document is persisted on save.
    """
    version = data.get("version", 0)
    if type(version) is not int or version < 0:
        raise _invalid("version", _("non-negative integer"))
    if version > _VERSION:
        raise UnsupportedSettingsVersion(
            _("Unsupported settings version: {version}").format(version=version)
        )
    return {**data, "version": _VERSION}


def _from_data(data: Any) -> Settings:
    if not isinstance(data, dict):
        raise _invalid("settings", _("object"))
    settings = cast(Settings, _decode(Settings, migrate(data), "settings"))
    if not settings.columns or len({c.id for c in settings.columns}) != len(settings.columns):
        raise _invalid("columns", _("non-empty list of unique column IDs"))
    if any(c.width < 1 or c.order < 0 for c in settings.columns):
        raise _invalid("columns", _("positive widths and non-negative orders"))
    _bounded("default_scan.threads", settings.default_scan.threads, 0, _U32_MAX)
    _bounded("dupes.io_threads", settings.dupes.io_threads, 0, _U32_MAX)
    _bounded("dupes.min_size", settings.dupes.min_size, 0, _U64_MAX)
    _bounded("dupes.partial_bytes", settings.dupes.partial_bytes, 1, _U32_MAX)
    if settings.dupes.max_size is not None:
        _bounded("dupes.max_size", settings.dupes.max_size, settings.dupes.min_size, _U64_MAX)
    _bounded("treemap.max_depth", settings.treemap.max_depth, 0, 255)
    _bounded("treemap.max_rects", settings.treemap.max_rects, 1, _U32_MAX)
    if min(settings.treemap.min_px, settings.treemap.padding, settings.treemap.header_px) < 0:
        raise _invalid("treemap", _("non-negative dimensions"))
    if len(settings.unit_style.decimal_separator) != 1:
        raise _invalid("unit_style.decimal_separator", _("one character"))
    if settings.window is not None and min(settings.window.width, settings.window.height) < 1:
        raise _invalid("window", _("positive dimensions"))
    settings.recent_targets = settings.recent_targets[:_MAX_RECENT]
    return settings


def _bounded(key: str, value: int, minimum: int, maximum: int) -> None:
    if not minimum <= value <= maximum:
        raise _invalid(key, f"{minimum}..{maximum}")


def load_settings(paths: AppPaths) -> Settings:
    """Load defaults or typed preferences, backing up corrupt files once.

    Permission/I/O errors and future schemas propagate without renaming the
    original. Loading valid v0 data does not write until the next explicit save.
    """
    path = paths.config / "settings.json"
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return Settings()
    try:
        return _from_data(json.loads(raw.decode("utf-8")))
    except UnsupportedSettingsVersion:
        raise
    except (ValueError, TypeError):
        stamp = int(time.time())
        backup = path.with_name(f"settings.json.bad-{stamp}")
        counter = 0
        while backup.exists():
            counter += 1
            backup = path.with_name(f"settings.json.bad-{stamp}-{counter}")
        path.rename(backup)
        return Settings()


def save_settings(settings: Settings, paths: AppPaths) -> None:
    """Validate and atomically replace settings using a flushed sibling temp file."""
    data = _encode(_from_data(_encode(settings)))
    paths.config.mkdir(parents=True, exist_ok=True)
    path = paths.config / "settings.json"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".settings-",
            suffix=".tmp",
            dir=paths.config,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            # ASCII escapes also preserve filesystem surrogate escapes losslessly.
            json.dump(data, stream, indent=2, ensure_ascii=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _parts(key: str) -> list[str]:
    parts = key.split(".")
    if any(not part for part in parts):
        raise _invalid(key, _("dotted setting name"))
    return parts


def _item(value: Any, part: str, key: str) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        if part in {f.name for f in fields(value)}:
            return getattr(value, part)
    elif isinstance(value, dict):
        if part in value:
            return value[part]
    elif isinstance(value, list) and part.isdecimal() and int(part) < len(value):
        return value[int(part)]
    raise _invalid(key, _("existing setting"))


def get_dotted(settings: Settings, key: str) -> Any:
    """Read a declared field, dictionary key, or non-negative list index."""
    value: Any = settings
    for part in _parts(key):
        value = _item(value, part, key)
    return value


def set_dotted(settings: Settings, key: str, raw: str) -> Settings:
    """Return a validated independent copy after parsing a JSON value or bare string."""
    parts = _parts(key)
    if parts[0] == "version":
        raise _invalid(key, _("user preference (version is managed by migrations)"))
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = raw
    data = _encode(settings)
    container = data
    for part in parts[:-1]:
        container = _item(container, part, key)
    last = parts[-1]
    if isinstance(container, dict):
        container[last] = parsed
    elif isinstance(container, list) and last.isdecimal() and int(last) < len(container):
        container[int(last)] = parsed
    else:
        raise _invalid(key, _("existing setting"))
    return _from_data(data)
