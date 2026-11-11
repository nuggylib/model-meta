"""Check status icons, read from a results file's JSON (`Results.to_dict()`)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

PENDING = "🟡"
REFRESHING = "🔄"
PASS = "✅"
# Escaped: many viewers drop U+FE0F and draw the text-style warning sign.
WARN = "⚠️"
FAIL = "❌"

WARNING = "warning"

# `True` passed, `False` failed, `None` pending.
Status = bool | Literal["warning"] | None


def is_check(value: object) -> bool:
    return isinstance(value, dict) and (
        {"passed", "failures"}
        <= set(value)
        <= {"passed", "failures", "warning", "duplicates"}
    )


def status_of(value: object) -> Status:
    """A bool, a check's `passed` (`WARNING` for a failing `warning` check), or the
    most severe status in a container.

    `None` for a value holding no status, like a list of mesh names.
    """
    if isinstance(value, bool):
        return value
    if is_check(value):
        if not value["passed"] and value.get("warning"):
            return WARNING
        return value["passed"]
    if isinstance(value, dict):
        statuses = [s for s in map(status_of, value.values()) if s is not None]
        return most_severe(statuses) if statuses else None
    return None


def most_severe(statuses: Iterable[Status]) -> Status:
    """A failure, else a warning, else a pending (`None`) one, else a pass."""
    statuses = list(statuses)
    for status in (False, WARNING, None):
        if status in statuses:
            return status
    return True


def lookup(data: dict, path: tuple[str, ...]) -> object:
    """The value at `path`, or `None` when any key is missing."""
    value: object = data
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def icon(status: Status) -> str:
    return {None: PENDING, True: PASS, WARNING: WARN, False: FAIL}[status]
