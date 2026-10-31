"""Shared coercion rules for existing plugin configuration inputs."""

from __future__ import annotations

from typing import Any


def as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw_values = value.split(",")
    else:
        raw_values = list(value)
    return tuple(str(item).strip() for item in raw_values if str(item).strip())


def parse_credit_pairs(items: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """Parse normalized entries while preserving their first-seen order."""
    pairs: list[tuple[str, str]] = []
    for item in items:
        parts = [part.strip().upper() for part in item.replace("/", ":").split(":")]
        if len(parts) != 2 or not all(parts):
            raise ValueError(f"credit pair must use NUMERATOR:DENOMINATOR syntax: {item!r}")
        pair = (parts[0], parts[1])
        if pair not in pairs:
            pairs.append(pair)
    return tuple(pairs)
