"""Mesh roles: `mesh_roles`, a role name → role-fields map.

A role's `vtx_grp` is a pattern in `parenting`'s syntax — a literal base whose
dot-segments may be `{n}` placeholders — inferred from checked
`required_bones` so it matches exactly those. Placeholders are all free for now.
Its `mesh_regex`, required on new roles, is a Python regex naming the mesh
objects in the role; nothing ties its groups to the `vtx_grp`. Its `count`,
also required on new roles, is exactly how many mesh objects that regex must
match. Its `texture_maps` draws from `schema.TEXTURE_MAPS`; unknown names are kept.

Pure functions over strings, like `bones`.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence

from model_meta.specs import bones, parenting, schema


def validate_name(name: str, existing: Collection[str]) -> str | None:
    """Why `name` can't be a new role name, or `None`. Pass it trimmed."""
    if not name:
        return "Enter a role name."
    if name in existing:
        return f"'{name}' is already a mesh role."
    return None


def validate_mesh_regex(pattern: str) -> str | None:
    """Why `pattern` can't be a `mesh_regex`, or `None`. Pass it trimmed."""
    if not pattern:
        return "Enter a mesh regex."
    try:
        re.compile(pattern)
    except re.error as error:
        where = "" if error.pos is None else f" at position {error.pos}"
        return f"Not a valid regex: {error.msg}{where}."
    return None


def parse_count(text: str) -> int:
    """The `count` that `text` names, else `ValueError`. Pass it trimmed."""
    if not text:
        raise ValueError("Enter a count.")
    if not re.fullmatch(r"[0-9]+", text):
        raise ValueError("The count must be a whole number.")
    try:
        count = int(text)
    except ValueError:
        raise ValueError("The count must be a whole number.") from None
    if count < 1:
        raise ValueError("The count must be at least 1.")
    return count


def texture_choices(current: Sequence[str]) -> list[str]:
    """`TEXTURE_MAPS`, then `current`'s unknown names in first-seen order."""
    return list(dict.fromkeys([*schema.TEXTURE_MAPS, *current]))


def order_texture_maps(checked: Collection[str], current: Sequence[str]) -> list[str]:
    return [name for name in texture_choices(current) if name in checked]


def matches(pattern: str, required: Sequence[str]) -> list[str]:
    """The required bones `pattern` matches, in order."""
    return [bone for bone in required if parenting.match(pattern, bone) is not None]


def stale_roles(roles: Mapping[str, Mapping], old: str, new: str) -> list[str]:
    """The roles whose `vtx_grp` matches `old` but not `new`."""
    return [
        name
        for name, role in roles.items()
        if "vtx_grp" in role
        and matches(role["vtx_grp"], [old])
        and not matches(role["vtx_grp"], [new])
    ]


def unmatched_roles(
    roles: Mapping[str, Mapping], gone: str, required: Sequence[str]
) -> list[str]:
    """The roles whose `vtx_grp` matched the deleted `gone` but none of `required`."""
    return [
        name
        for name, role in roles.items()
        if "vtx_grp" in role
        and matches(role["vtx_grp"], [gone])
        and not matches(role["vtx_grp"], required)
    ]


def infer_vtx_grp(checked: Collection[str], required: Sequence[str]) -> str:
    """The pattern matching exactly `checked` among `required`, else `ValueError`."""
    names = [bone for bone in required if bone in checked]
    if not names:
        raise ValueError("Check at least one bone.")
    pattern = parenting.generalize(names)
    if pattern is None:
        first = names[0].split(".")
        other = next(
            name
            for name in names
            if len(name.split(".")) != len(first) or name.split(".")[0] != first[0]
        )
        raise ValueError(f"'{names[0]}' and '{other}' can't share one pattern.")
    if len(pattern.encode("utf-8")) > bones.MAX_BYTES:
        raise ValueError(f"Vertex group names are limited to {bones.MAX_BYTES} bytes.")
    if extra := [bone for bone in matches(pattern, required) if bone not in checked]:
        raise ValueError(f"'{pattern}' would also match {', '.join(extra)}.")
    return pattern
