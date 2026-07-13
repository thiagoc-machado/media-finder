"""Parsing and formatting for media sizes."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_SIZE_PATTERN = re.compile(
    r"^\s*(?P<number>\d+(?:[.,]\d+)?)\s*(?P<unit>bytes?|b|kb|mb|gb|tb|kib|mib|gib|tib)\s*$",
    re.IGNORECASE,
)
_DECIMAL_FACTORS = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4, "BYTES": 1, "BYTE": 1}
_BINARY_FACTORS = {"KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "TIB": 1024**4}


def parse_size(value: str | int | float | Decimal | None) -> int | None:
    """Convert a size value into bytes, returning None for an absent value."""

    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean is not a valid size")
    if isinstance(value, (int, float, Decimal)):
        try:
            number = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("Invalid numeric size") from exc
        if not number.is_finite() or number < 0:
            raise ValueError("Size cannot be negative")
        return int(number.to_integral_value(rounding=ROUND_HALF_UP))
    if not isinstance(value, str):
        raise ValueError("Size must be a number, string, or None")

    match = _SIZE_PATTERN.fullmatch(value)
    if not match:
        raise ValueError(f"Invalid size: {value!r}")
    number_text = match.group("number").replace(",", ".")
    try:
        number = Decimal(number_text)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid size: {value!r}") from exc
    if number < 0:
        raise ValueError("Size cannot be negative")

    unit = match.group("unit").upper()
    factor = _BINARY_FACTORS.get(unit, _DECIMAL_FACTORS.get(unit))
    if factor is None:
        raise ValueError(f"Unsupported size unit: {unit}")
    return int((number * factor).to_integral_value(rounding=ROUND_HALF_UP))


def format_size(value: int | None, *, binary: bool = True, precision: int = 2) -> str:
    """Format bytes for humans; absent values are represented as ``Unknown``."""

    if value is None:
        return "Unknown"
    if isinstance(value, bool) or value < 0:
        raise ValueError("Size cannot be negative")
    if value == 0:
        return "0 B"

    base = 1024 if binary else 1000
    units = ("B", "KiB", "MiB", "GiB", "TiB") if binary else ("B", "KB", "MB", "GB", "TB")
    amount = float(value)
    unit_index = 0
    while amount >= base and unit_index < len(units) - 1:
        amount /= base
        unit_index += 1
    return f"{amount:.{precision}f} {units[unit_index]}"
