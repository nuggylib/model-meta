from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace

from model_meta.checks.mesh_roles import NO_MESHES
from model_meta.core.blender_bridge import MeshModifiers
from model_meta.core.results import FieldCheck, MeshRoleResult, ModifiersResult
from model_meta.core.spec import Modifiers

Facts = Callable[[list[str]], dict[str, object]]


def evaluate(
    mods: Modifiers,
    roles: Mapping[str, MeshRoleResult],
    report: Sequence[MeshModifiers],
) -> tuple[ModifiersResult, dict[str, MeshRoleResult]]:
    """The check over every role's meshes, and each role with its own meshes' check.

    Pass the `report` fetched for `mesh_roles.plan`'s modifier targets.
    """
    stacks = {item.mesh: item for item in report}
    every = list(dict.fromkeys(mesh for role in roles.values() for mesh in role.meshes))
    checked = {
        name: replace(role, modifiers=_check(mods, role.meshes, stacks, unmatched=True))
        for name, role in roles.items()
    }
    return _check(mods, every, stacks, unmatched=False), checked


def _check(
    mods: Modifiers,
    meshes: list[str],
    stacks: dict[str, MeshModifiers],
    *,
    unmatched: bool,
) -> ModifiersResult:
    """`unmatched` fails every check when `meshes` is empty, as a role with no meshes."""

    def check(facts: Facts, warning: bool = False) -> FieldCheck:
        if unmatched and not meshes:
            return FieldCheck([{"error": NO_MESHES}], warning)
        failures = []
        for mesh in meshes:
            stack = stacks[mesh]
            if stack.error is not None:
                failures.append({"mesh": mesh, "error": stack.error})
            elif found := facts(stack.modifiers):
                failures.append({"mesh": mesh, **found})
        return FieldCheck(failures, warning)

    return ModifiersResult(
        {"skinned_meshes": check(_missing(mods.required.skinned_meshes))},
        check(_present(mods.warn), warning=True),
        check(_present(mods.fail)),
    )


def _missing(required: list[str]) -> Facts:
    def facts(stack: list[str]) -> dict[str, object]:
        missing = [name for name in dict.fromkeys(required) if name not in stack]
        return {"missing": missing} if missing else {}

    return facts


def _present(listed: list[str]) -> Facts:
    def facts(stack: list[str]) -> dict[str, object]:
        present = [name for name in dict.fromkeys(stack) if name in listed]
        return {"modifiers": present} if present else {}

    return facts
