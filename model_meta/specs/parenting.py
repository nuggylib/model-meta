"""Parenting patterns: `armature.parenting`, a parent-pattern → child-patterns map.

A pattern is a bone name whose dot-segments may be `{n}` placeholders, each
matching exactly one whole segment. The base is always literal. A placeholder
in the key is *bound* — its children reuse what it matched — and one that only
appears in a child is *free*. Patterns resolve against `required_bones`, so a
key never repeats a name the spec already holds.

Pure functions over strings and dicts, like `bones`.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Mapping, Sequence

_PLACEHOLDER = re.compile(r"^\{\d+\}$")


def is_placeholder(part: str) -> bool:
    """Whether one dot-separated part of a pattern is a `{n}` placeholder."""
    return bool(_PLACEHOLDER.match(part))


def has_placeholder_segment(name: str) -> bool:
    """A bone with a literal `{n}` segment can't be told apart from a pattern."""
    return any(is_placeholder(part) for part in name.split(".")[1:])


def match(
    pattern: str, name: str, bound: Mapping[str, str] | None = None
) -> dict[str, str] | None:
    """The placeholder bindings that make `pattern` match `name`, or `None`."""
    pattern_parts = pattern.split(".")
    name_parts = name.split(".")
    if len(pattern_parts) != len(name_parts) or pattern_parts[0] != name_parts[0]:
        return None
    bindings = dict(bound or {})
    for part, segment in zip(pattern_parts[1:], name_parts[1:], strict=True):
        if is_placeholder(part):
            if bindings.setdefault(part, segment) != segment:
                return None
        elif part != segment:
            return None
    return bindings


def pairs(
    parenting: Mapping[str, Sequence[str]], required: Sequence[str]
) -> list[tuple[str, str]]:
    """Every distinct (parent, child) the map resolves to among `required`."""
    found: dict[tuple[str, str], None] = {}
    for key, patterns in parenting.items():
        for parent in required:
            bound = match(key, parent)
            if bound is None:
                continue
            for pattern in patterns:
                for child in required:
                    if match(pattern, child, bound) is not None:
                        found[(parent, child)] = None
    return list(found)


def resolve(
    parenting: Mapping[str, Sequence[str]], required: Sequence[str]
) -> dict[str, list[str]]:
    """Each child bone → its distinct parents. More than one is a conflict."""
    parents: dict[str, list[str]] = {}
    for parent, child in pairs(parenting, required):
        parents.setdefault(child, []).append(parent)
    return parents


def ancestors(bone: str, resolved: Mapping[str, Sequence[str]]) -> set[str]:
    """Every bone above `bone`. Contains `bone` itself only on a cycle."""
    found: set[str] = set()
    stack = list(resolved.get(bone, ()))
    while stack:
        parent = stack.pop()
        if parent not in found:
            found.add(parent)
            stack.extend(resolved.get(parent, ()))
    return found


def is_valid(parenting: Mapping[str, Sequence[str]], required: Sequence[str]) -> bool:
    """At most one parent per bone, and no bone above itself."""
    resolved = resolve(parenting, required)
    if any(len(parents) > 1 for parents in resolved.values()):
        return False
    return all(bone not in ancestors(bone, resolved) for bone in resolved)


def merge(
    parenting: Mapping[str, Sequence[str]], entries: Mapping[str, Sequence[str]]
) -> dict[str, list[str]]:
    """A copy of `parenting` with `entries` appended per key, deduped."""
    merged = {key: list(patterns) for key, patterns in parenting.items()}
    for key, patterns in entries.items():
        existing = merged.setdefault(key, [])
        existing.extend(p for p in dict.fromkeys(patterns) if p not in existing)
    return merged


def is_stale(pattern: str, old: str, new: str) -> bool:
    """Whether `pattern` matches a renamed bone's `old` name but not its `new` one."""
    return match(pattern, old) is not None and match(pattern, new) is None


def stale_keys(parenting: Mapping[str, Sequence[str]], old: str, new: str) -> list[str]:
    """The keys whose key or a child pattern matches `old` but not `new`."""
    return [
        key
        for key, patterns in parenting.items()
        if any(is_stale(pattern, old, new) for pattern in [key, *patterns])
    ]


def is_unmatched(pattern: str, gone: str, required: Sequence[str]) -> bool:
    """Whether `pattern` matched the deleted bone `gone` but no bone in `required`."""
    return match(pattern, gone) is not None and not any(
        match(pattern, bone) is not None for bone in required
    )


def unmatched_keys(
    parenting: Mapping[str, Sequence[str]], gone: str, required: Sequence[str]
) -> list[str]:
    """The keys whose key or a child pattern `is_unmatched`."""
    return [
        key
        for key, patterns in parenting.items()
        if any(is_unmatched(pattern, gone, required) for pattern in [key, *patterns])
    ]


def generalize(names: Sequence[str]) -> str | None:
    """`names` with `{n}` wherever they differ, or `None` if bases or lengths do."""
    split = [name.split(".") for name in names]
    if len({len(parts) for parts in split}) != 1:
        return None
    parts = []
    count = 0
    for values in zip(*split, strict=True):
        if len(set(values)) == 1:
            parts.append(values[0])
        else:
            count += 1
            parts.append(f"{{{count}}}")
    if is_placeholder(parts[0]):
        return None
    return ".".join(parts)


def infer(
    parents: Sequence[str],
    children: Sequence[str],
    required: Sequence[str],
    parenting: Mapping[str, Sequence[str]],
) -> dict[str, list[str]]:
    """The entries that parent each checked child to its checked parent.

    A pattern is kept only if it resolves to exactly the intended pairs and
    leaves the merged map valid; otherwise the exact names are used. Raises
    `ValueError` naming a child that matches no checked parent, or several.
    """
    intended = _pair(parents, children)
    wanted = {(parent, child) for child, parent in intended.items()}
    key = _key(parents, required)
    entries: dict[str, list[str]] = {}
    covered: set[tuple[str, str]] = set()
    for child in required:
        parent = intended.get(child)
        if parent is None or (parent, child) in covered:
            continue
        found = None
        if key is not None:
            for pattern in _child_patterns(key, parent, child):
                trial = merge(entries, {key: [pattern]})
                matched = set(pairs({key: [pattern]}, required))
                if (
                    matched <= wanted
                    and _varies(key, pattern, matched)
                    and is_valid(merge(parenting, trial), required)
                ):
                    found = trial, matched
                    break
        if found is None:
            entries = merge(entries, {parent: [child]})
            covered.add((parent, child))
        else:
            entries, matched = found
            covered |= matched
    return entries


# --- internals -------------------------------------------------------------


def _pair(parents: Sequence[str], children: Sequence[str]) -> dict[str, str]:
    """Child → the one checked parent whose distinguishing segments it holds."""
    split = {parent: parent.split(".") for parent in parents}
    distinct = {
        parent: [p for p in parts if not all(p in other for other in split.values())]
        for parent, parts in split.items()
    }
    paired = {}
    for child in children:
        parts = child.split(".")
        matches = [p for p in parents if _in_order(distinct[p], parts)]
        if len(matches) != 1:
            which = "no checked parent" if not matches else "more than one parent"
            raise ValueError(f"'{child}' matches {which}.")
        paired[child] = matches[0]
    return paired


def _key(parents: Sequence[str], required: Sequence[str]) -> str | None:
    """A key matching exactly `parents` among `required`, or `None`."""
    key = generalize(parents)
    if key is None:
        return None
    if {bone for bone in required if match(key, bone) is not None} != set(parents):
        return None
    return key


def _child_patterns(key: str, parent: str, child: str) -> list[str]:
    """Child patterns to try: bound to the key, most free segments first."""
    bound = match(key, parent) or {}
    parts = child.split(".")
    replaced: set[int] = set()
    start = 1
    for placeholder, value in bound.items():
        j = next((j for j in range(start, len(parts)) if parts[j] == value), None)
        if j is not None:
            parts[j] = placeholder
            replaced.add(j)
            start = j + 1
    open_positions = [j for j in range(1, len(parts)) if j not in replaced]
    first = len(bound) + 1
    patterns = []
    for size in range(len(open_positions), -1, -1):
        for chosen in itertools.combinations(open_positions, size):
            candidate = list(parts)
            for n, j in enumerate(chosen, start=first):
                candidate[j] = f"{{{n}}}"
            patterns.append(".".join(candidate))
    return patterns


def _varies(key: str, pattern: str, matched: set[tuple[str, str]]) -> bool:
    """Every free placeholder in `pattern` takes at least two values."""
    values: dict[str, set[str]] = {}
    for parent, child in matched:
        bound = match(key, parent) or {}
        for placeholder, value in (match(pattern, child, bound) or {}).items():
            if placeholder not in bound:
                values.setdefault(placeholder, set()).add(value)
    return all(len(seen) > 1 for seen in values.values())


def _in_order(needles: Sequence[str], parts: Sequence[str]) -> bool:
    """Whether `needles` appear in `parts` in order (not necessarily adjacent)."""
    rest = iter(parts)
    return all(needle in rest for needle in needles)
