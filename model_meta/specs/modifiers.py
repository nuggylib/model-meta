"""Modifiers: the four modifier lists, and moving a name between them."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import replace

from model_meta.core.spec import Modifiers
from model_meta.specs import schema

# `skinned_meshes` stands for `required.skinned_meshes`.
LISTS = ("skinned_meshes", "allowed", "warn", "fail")

_CONFLICTS = {
    "skinned_meshes": ("fail",),
    "allowed": ("warn", "fail"),
    "warn": ("allowed", "fail"),
    "fail": ("skinned_meshes", "allowed", "warn"),
}


def get(mods: Modifiers, name: str) -> list[str]:
    return {
        "skinned_meshes": mods.required.skinned_meshes,
        "allowed": mods.allowed,
        "warn": mods.warn,
        "fail": mods.fail,
    }[name]


def choices(mods: Modifiers) -> list[str]:
    """`MODIFIERS`, then the unknown names of every list in `LISTS` order."""
    found = [modifier for key in LISTS for modifier in get(mods, key)]
    return list(dict.fromkeys([*schema.MODIFIERS, *found]))


def conflicts(mods: Modifiers, name: str) -> dict[str, list[str]]:
    """Each modifier in a list that conflicts with list `name`, and those lists."""
    found: dict[str, list[str]] = {}
    for other in _CONFLICTS[name]:
        for modifier in dict.fromkeys(get(mods, other)):
            found.setdefault(modifier, []).append(other)
    return found


def assign(mods: Modifiers, name: str, checked: Collection[str]) -> Modifiers:
    """List `name` set to `checked`, which leaves every list it conflicts with."""
    lists = {key: get(mods, key) for key in LISTS}
    lists[name] = [modifier for modifier in choices(mods) if modifier in checked]
    for other in _CONFLICTS[name]:
        lists[other] = [m for m in lists[other] if m not in checked]
    return replace(
        mods,
        required=replace(mods.required, skinned_meshes=lists["skinned_meshes"]),
        allowed=lists["allowed"],
        warn=lists["warn"],
        fail=lists["fail"],
    )


def format_list(names: Sequence[str]) -> str:
    return ", ".join(names) if names else "[]"
