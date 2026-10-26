"""Bone-name segments, their inverses, and the variants a name implies.

A bone name is a base plus dot-segments: `susarm.front.top.L` is `susarm` with
`.front`, `.top`, `.L`. Every segment either has an inverse (`.L`/`.R` built in,
the rest from the spec's `armature.bone_name_inverses`) or maps to itself.

Pure functions over strings and dicts — the manual form and a later
scene-inferred flow both call these, regardless of where a name came from.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping

BUILTIN_INVERSES = {".L": ".R", ".R": ".L"}
MAX_BYTES = 63  # Blender's bone-name limit (MAX_NAME 64, incl. NUL)


def split(name: str) -> tuple[str, tuple[str, ...]]:
    """`susarm.front.top.L` → (`susarm`, (`.front`, `.top`, `.L`))."""
    base, *rest = name.split(".")
    return base, tuple(f".{part}" for part in rest)


def validate_name(name: str) -> str | None:
    """Why `name` is unusable as a bone name, or `None` if it is fine."""
    if not name:
        return "Enter a bone name."
    if len(name.encode("utf-8")) > MAX_BYTES:
        return f"Bone names are limited to {MAX_BYTES} bytes."
    if "" in name.split("."):
        return f"'{name}' has an empty segment."
    return None


def next_missing(name: str, known: Mapping[str, str]) -> str | None:
    """The first segment of `name` with no inverse yet, or `None`."""
    for segment in split(name)[1]:
        if segment not in BUILTIN_INVERSES and segment not in known:
            return segment
    return None


def normalize_inverse(answer: str) -> str:
    """Trim, and add the leading dot if it was left off. Blank stays blank."""
    answer = answer.strip()
    if answer and not answer.startswith("."):
        return f".{answer}"
    return answer


def validate_inverse(segment: str, answer: str, known: Mapping[str, str]) -> str | None:
    """Why `answer` can't be `segment`'s inverse, or `None`. Blank is fine."""
    answer = normalize_inverse(answer)
    if not answer:
        return None
    if answer.count(".") != 1 or answer == ".":
        return f"'{answer}' must be a single segment."
    if answer in BUILTIN_INVERSES:
        return f"'{answer}' is reserved for left/right."
    if answer == segment:
        return f"Leave it blank if '{segment}' has no inverse."
    return _pairing_conflict(segment, answer, known)


def _pairing_conflict(
    segment: str, answer: str, known: Mapping[str, str]
) -> str | None:
    paired = known.get(answer)
    if paired is None or paired == segment:
        return None
    if paired == answer:
        return f"'{answer}' is already recorded as having no inverse."
    return f"'{answer}' is already paired with '{paired}'."


def pairs(segment: str, answer: str) -> dict[str, str]:
    """Both directions, or a single self-mapping for a blank answer."""
    answer = normalize_inverse(answer)
    if not answer:
        return {segment: segment}
    return {segment: answer, answer: segment}


def variants(name: str, known: Mapping[str, str]) -> list[str]:
    """Every other name in `name`'s inverse family, in product order.

    Raises `ValueError` on an unmapped segment: the chain must be complete.
    """
    inverses = {**known, **BUILTIN_INVERSES}
    base, segments = split(name)
    choices = []
    for segment in segments:
        if segment not in inverses:
            raise ValueError(f"'{segment}' has no inverse yet.")
        inverse = inverses[segment]
        choices.append((segment,) if inverse == segment else (segment, inverse))
    names = (base + "".join(combo) for combo in itertools.product(*choices))
    return [candidate for candidate in names if candidate != name]
