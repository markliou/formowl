"""Type-driven value normalization for candidate records.

Normalization depends only on the declared value type, never on a specific
part, supplier or country. The raw string is always kept by the caller; an
ambiguous value is reported as unresolved instead of guessed.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

VALUE_TYPES = frozenset({"date", "country", "quantity", "identifier", "text"})

# Character-level orthographic variants that CLDR names do not cover.
_CJK_VARIANTS = str.maketrans({"臺": "台"})


def _fold(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw).translate(_CJK_VARIANTS)
    return " ".join(text.casefold().split())


def _result(norm: str | None, **extra: Any) -> dict[str, Any]:
    return {"norm": norm, "status": "ok" if norm is not None else "unresolved", **extra}


_DATE_PATTERNS = (
    re.compile(r"(?P<y>\d{4})\s*[-/.]\s*(?P<m>\d{1,2})\s*[-/.]\s*(?P<d>\d{1,2})(?:[ t]\d{1,2}:\d{2}.*)?"),
    re.compile(r"(?P<y>\d{4})\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*[日号號]?"),
    re.compile(r"(?P<y>\d{4})(?P<m>\d{2})(?P<d>\d{2})"),
)


_MONTHS = {name: index + 1 for index, names in enumerate((
    "jan january", "feb february", "mar march", "apr april", "may", "jun june",
    "jul july", "aug august", "sep sept september", "oct october", "nov november", "dec december",
)) for name in names.split()}
_MONTH = "(?P<mon>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_NAMED_DATE_PATTERNS = (
    re.compile(_MONTH + r"[\s.-]*(?P<d>\d{1,2})(?:st|nd|rd|th)?,?[\s.-]*(?P<y>\d{4})"),
    re.compile(r"(?P<d>\d{1,2})(?:st|nd|rd|th)?[\s.-]*" + _MONTH + r",?[\s.-]*(?P<y>\d{4})"),
)
_NUMERIC_DMY_OR_MDY = re.compile(r"(?P<a>\d{1,2})\s*[-/.]\s*(?P<b>\d{1,2})\s*[-/.]\s*(?P<y>\d{4})")
# Spreadsheet day serials (1900 date system) for roughly 1955-2119.
_SERIAL_RANGE = range(20000, 80000)


def _iso(year: int, month: int, day: int, **extra: Any) -> dict[str, Any]:
    try:
        return _result(date(year, month, day).isoformat(), **extra)
    except ValueError:
        return _result(None)


def normalize_date(raw: str) -> dict[str, Any]:
    """Unambiguous full dates only; partial, two-digit-year or day/month-ambiguous dates stay unresolved."""
    text = _fold(raw)
    for pattern in _DATE_PATTERNS:
        match = pattern.fullmatch(text)
        if match:
            return _iso(int(match["y"]), int(match["m"]), int(match["d"]))
    for pattern in _NAMED_DATE_PATTERNS:
        match = pattern.fullmatch(text)
        if match:
            return _iso(int(match["y"]), _MONTHS[match["mon"]], int(match["d"]))
    match = _NUMERIC_DMY_OR_MDY.fullmatch(text)
    if match:
        first, second = int(match["a"]), int(match["b"])
        if first > 12 >= second:
            return _iso(int(match["y"]), second, first, match="day_first")
        if second > 12 >= first:
            return _iso(int(match["y"]), first, second, match="month_first")
        return _result(None)  # Both readings are possible; never guess the locale.
    if text.isdigit() and int(text) in _SERIAL_RANGE:
        return _result((date(1899, 12, 30) + timedelta(days=int(text))).isoformat(), match="spreadsheet_serial")
    return _result(None)


@lru_cache(maxsize=1)
def _country_index() -> tuple[dict[str, str], tuple[tuple[str, str], ...]]:
    data = json.loads((Path(__file__).parent / "data" / "country_names.json").read_text("utf-8"))
    exact: dict[str, str] = {}
    ambiguous: set[str] = set()
    for code, names in data["countries"].items():
        for name in names:
            key = _fold(name)
            if exact.get(key, code) != code:
                ambiguous.add(key)
            exact[key] = code
    for key in ambiguous:
        exact.pop(key, None)
    # Substring search uses only names of at least two CJK characters or four
    # Latin letters, so short codes such as "CN" never match inside other words.
    contained = tuple(sorted(
        ((key, code) for key, code in exact.items()
         if (len(key) >= 2 and all("一" <= ch <= "鿿" for ch in key)) or len(key) >= 4),
        key=lambda item: -len(item[0])))
    return exact, contained


def normalize_country(raw: str) -> dict[str, Any]:
    """ISO 3166-1 alpha-2 from ISO and CLDR names; a single unambiguous contained name also counts."""
    exact, contained = _country_index()
    text = _fold(raw)
    if text in exact:
        return _result(exact[text])
    found: dict[str, str] = {}
    remaining = text
    for key, code in contained:
        is_cjk = all("一" <= ch <= "鿿" for ch in key)
        pattern = re.escape(key) if is_cjk else rf"(?<![a-z]){re.escape(key)}(?![a-z])"
        if re.search(pattern, remaining):
            found[key] = code
            remaining = re.sub(pattern, " ", remaining)
    codes = set(found.values())
    return _result(codes.pop() if len(codes) == 1 else None, match="contained" if found else None)


_QUANTITY = re.compile(r"(?P<number>[+-]?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*(?P<unit>[^\d\s][^\d]*)?")


def normalize_quantity(raw: str) -> dict[str, Any]:
    text = unicodedata.normalize("NFKC", raw).strip()
    match = _QUANTITY.fullmatch(text)
    if not match:
        return _result(None)
    number = match["number"].replace(",", "")
    if "e" in number.lower():
        number = format(Decimal(number).normalize(), "f")
    if "." in number:
        number = number.rstrip("0").rstrip(".")
    unit = (match["unit"] or "").strip() or None
    return _result(number, unit=unit)


def normalize(value_type: str, raw: Any) -> dict[str, Any]:
    if value_type not in VALUE_TYPES:
        raise ValueError(f"unknown value type: {value_type}")
    if not isinstance(raw, str) or not raw.strip():
        return _result(None)
    if value_type == "date":
        return normalize_date(raw)
    if value_type == "country":
        return normalize_country(raw)
    if value_type == "quantity":
        return normalize_quantity(raw)
    return _result(_fold(raw))
