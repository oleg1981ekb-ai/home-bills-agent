"""Anomaly detection helpers for billing cycles.

Median of whole readings per account/period, consumption delta,
boundary cases (<3 intervals, zero median => require confirmation).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def median_of_list(values: list[Decimal]) -> Decimal | None:
    """Median of numeric values; None if empty."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def median_of_whole_readings(rows: list[dict[str, Any]]) -> Decimal | None:
    """Median of whole-reading values from rows (each: reading_value + is_integer + reading_date)."""
    whole = [r for r in rows if r.get("is_integer") == 1]
    vals: list[Decimal] = []
    for r in sorted(whole, key=lambda x: x.get("reading_date") or ""):
        d = _to_decimal(r.get("reading_value"))
        if d is not None:
            vals.append(d)
    return median_of_list(vals)


def compute_debt_delta(rows: list[dict[str, Any]]) -> Decimal | None:
    """Net debt delta (debt_after - debt_before) summed over the period."""
    total = Decimal(0)
    found = False
    for r in rows:
        d_before = _to_decimal(r.get("debt_before"))
        d_after = _to_decimal(r.get("debt_after"))
        if d_before is not None and d_after is not None:
            found = True
            diff = d_after - d_before
            if diff > 0:
                total += diff
    if not found:
        return None
    return total


def can_detect_anomaly(rows: list[dict[str, Any]], anomaly_factor: float) -> bool:
    """Return True if detection is possible.

    Requires at least 3 whole readings (enough intervals) and a
    positive median; otherwise the flow must ask the user to confirm.
    """
    whole = [r for r in rows if r.get("is_integer") == 1]
    if len(whole) < 3:
        return False
    med = median_of_whole_readings(rows)
    return med is not None and med > 0
