"""Check status icons, read from a results file's JSON (`Results.to_dict()`)."""

from __future__ import annotations

from collections.abc import Iterable

PENDING = "🟡"
REFRESHING = "🔄"
PASS = "✅"
FAIL = "❌"


def is_check(value: object) -> bool:
    return isinstance(value, dict) and set(value) == {"passed", "failures"}


def status_of(value: object) -> bool | None:
    """A bool, a check's `passed`, or the most severe status in a container.

    `None` for a value holding no status, like a list of mesh names.
    """
    if isinstance(value, bool):
        return value
    if is_check(value):
        return value["passed"]
    if isinstance(value, dict):
        statuses = [s for s in map(status_of, value.values()) if s is not None]
        return most_severe(statuses) if statuses else None
    return None


def most_severe(statuses: Iterable[bool | None]) -> bool | None:
    """A failure, else a pending (`None`) one, else a pass."""
    statuses = list(statuses)
    if False in statuses:
        return False
    if None in statuses:
        return None
    return True


def lookup(data: dict, path: tuple[str, ...]) -> object:
    """The value at `path`, or `None` when any key is missing."""
    value: object = data
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def icon(status: bool | None) -> str:
    if status is None:
        return PENDING
    return PASS if status else FAIL
