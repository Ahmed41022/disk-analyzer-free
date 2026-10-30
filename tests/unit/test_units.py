"""Unit labels and values exported as JSON for future GUI delegates."""

import json

from dafree.api import UnitMode, UnitStyle, UnitSystem, format_size, parse_size


def test_units_parity_json() -> None:
    """The JSON table uses the native formatter's labels and parser's values."""
    cases = [
        (0, UnitMode.AUTO, UnitStyle(), "0 B"),
        (1023, UnitMode.AUTO, UnitStyle(), "1023 B"),
        (1024, UnitMode.AUTO, UnitStyle(), "1.0 KB"),
        (1536, UnitMode.AUTO, UnitStyle(), "1.5 KB"),
        (1024, UnitMode.AUTO, UnitStyle(UnitSystem.IEC), "1.0 KiB"),
        (1000, UnitMode.AUTO, UnitStyle(UnitSystem.SI), "1.0 kB"),
        (1500, UnitMode.AUTO, UnitStyle(UnitSystem.SI, ","), "1,5 kB"),
    ]
    exported = json.dumps(
        [
            {
                "bytes": amount,
                "system": style.system.name,
                "mode": mode.name,
                "decimal_separator": style.decimal_separator,
                "label": format_size(amount, mode, style),
            }
            for amount, mode, style, _expected in cases
        ],
        ensure_ascii=False,
    )
    rows = json.loads(exported)
    for row, (amount, mode, style, expected) in zip(rows, cases, strict=True):
        assert row["bytes"] == amount
        assert row["mode"] == mode.name
        assert row["system"] == style.system.name
        assert row["label"] == expected
        assert parse_size(row["label"], style) == amount
