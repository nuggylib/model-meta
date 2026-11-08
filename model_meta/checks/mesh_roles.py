from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from model_meta.core.blender_bridge import (
    MeshReport,
    MeshTarget,
    MeshTextures,
    MeshUvs,
    MeshWeight,
    SceneMesh,
    TextureTarget,
    WeightTarget,
)
from model_meta.core.results import FieldCheck, MeshRoleResult
from model_meta.core.spec import MeshRole
from model_meta.specs import parenting

NO_MESHES = "no meshes matched"

Failures = list[dict[str, object]]


def plan(
    roles: Mapping[str, MeshRole], meshes: Sequence[SceneMesh]
) -> tuple[list[WeightTarget], list[TextureTarget], list[MeshTarget], list[MeshTarget]]:
    """The bridge targets `evaluate` needs: deduped, one texture and UV target per
    textured mesh, and one modifier target per matched mesh."""
    weights: dict[WeightTarget, None] = {}
    maps: dict[str, dict[str, None]] = {}
    matched_names: dict[str, None] = {}
    for role in roles.values():
        matched, _ = _matched(role, meshes)
        for mesh in matched:
            matched_names[mesh.name] = None
            if role.weight is not None and role.vtx_grp is not None:
                for group in _groups(role.vtx_grp, mesh):
                    weights[WeightTarget(mesh.name, group, role.weight)] = None
            for name in role.texture_maps or []:
                maps.setdefault(mesh.name, {})[name] = None
    textures = [TextureTarget(mesh, list(names)) for mesh, names in maps.items()]
    return (
        list(weights),
        textures,
        [MeshTarget(mesh) for mesh in maps],
        [MeshTarget(mesh) for mesh in matched_names],
    )


def evaluate(
    roles: Mapping[str, MeshRole], report: MeshReport
) -> dict[str, MeshRoleResult]:
    """Pass a `report` fetched with `plan(roles, ...)`, so its items line up."""
    weight_targets, texture_targets, uv_targets, _ = plan(roles, report.meshes)
    scene = _Scene(
        dict(zip(weight_targets, report.weights, strict=True)),
        {
            target.mesh: result
            for target, result in zip(texture_targets, report.textures, strict=True)
        },
        None
        if report.uvs is None
        else {
            target.mesh: result
            for target, result in zip(uv_targets, report.uvs, strict=True)
        },
    )
    return {
        name: _role_result(role, report.meshes, scene) for name, role in roles.items()
    }


@dataclass(frozen=True)
class _Scene:
    """`uvs` is `None` when the add-on predates `get_mesh_uvs`."""

    weights: dict[WeightTarget, MeshWeight]
    textures: dict[str, MeshTextures]
    uvs: dict[str, MeshUvs] | None


def _role_result(
    role: MeshRole, meshes: Sequence[SceneMesh], scene: _Scene
) -> MeshRoleResult:
    matched, problem = _matched(role, meshes)
    checks = {}
    for field, is_set, check in _CHECKS:
        if not is_set(role):
            continue
        if problem is not None:
            failures = [{"error": problem}]
        elif not matched and field != "count":
            failures = [{"error": NO_MESHES}]
        else:
            failures = check(role, matched, scene)
        checks[field] = FieldCheck(failures)
    return MeshRoleResult([mesh.name for mesh in matched], checks)


def _count(role: MeshRole, matched: list[SceneMesh], _scene: _Scene) -> Failures:
    if len(matched) == role.count:
        return []
    return [{"expected": role.count, "matched": len(matched)}]


def _vtx_grp(role: MeshRole, matched: list[SceneMesh], _scene: _Scene) -> Failures:
    return [{"mesh": mesh.name} for mesh in matched if not _groups(role.vtx_grp, mesh)]


def _weight(role: MeshRole, matched: list[SceneMesh], scene: _Scene) -> Failures:
    if role.vtx_grp is None:
        return [{"error": "vtx_grp not set"}]
    failures = []
    for mesh in matched:
        groups = _groups(role.vtx_grp, mesh)
        if not groups:
            failures.append({"mesh": mesh.name, "error": "no vertex group"})
        for group in groups:
            result = scene.weights[WeightTarget(mesh.name, group, role.weight)]
            if result.error is not None:
                failures.append(
                    {"mesh": mesh.name, "vertex_group": group, "error": result.error}
                )
            elif not result.vertices == result.assigned == result.at_weight:
                counts = asdict(result)
                del counts["error"]
                failures.append(counts)
    return failures


def _texture_maps(role: MeshRole, matched: list[SceneMesh], scene: _Scene) -> Failures:
    failures = []
    for mesh in matched:
        result = scene.textures[mesh.name]
        if result.error is not None:
            failures.append({"mesh": mesh.name, "error": result.error})
            continue
        missing = [name for name in role.texture_maps if not result.maps.get(name)]
        if missing:
            failures.append(
                {"mesh": mesh.name, "missing": missing, **_unwrap(mesh.name, scene)}
            )
    return failures


def _unwrap(mesh: str, scene: _Scene) -> dict[str, object]:
    if scene.uvs is None:
        return {}
    result = scene.uvs[mesh]
    if result.error is not None:
        return {"uv_error": result.error}
    return {"has_default_uv_map": True} if result.has_default_uv_map else {}


def _material_slots(
    role: MeshRole, matched: list[SceneMesh], _scene: _Scene
) -> Failures:
    failures = []
    for mesh in matched:
        missing = [s for s in role.material_slots if s not in mesh.material_slots]
        if missing:
            failures.append({"mesh": mesh.name, "missing": missing})
    return failures


# Spec order, which is also the order results are written in. `[]` lists check nothing.
_CHECKS = (
    ("count", lambda role: role.count is not None, _count),
    ("vtx_grp", lambda role: role.vtx_grp is not None, _vtx_grp),
    ("weight", lambda role: role.weight is not None, _weight),
    ("texture_maps", lambda role: bool(role.texture_maps), _texture_maps),
    ("material_slots", lambda role: bool(role.material_slots), _material_slots),
)


def _matched(
    role: MeshRole, meshes: Sequence[SceneMesh]
) -> tuple[list[SceneMesh], str | None]:
    """The meshes `mesh_regex` fully matches, and why none can be, or `None`."""
    if role.mesh_regex is None:
        return [], "mesh_regex not set"
    try:
        pattern = re.compile(role.mesh_regex)
    except re.error:
        return [], "mesh_regex doesn't compile"
    return [mesh for mesh in meshes if pattern.fullmatch(mesh.name)], None


def _groups(vtx_grp: str, mesh: SceneMesh) -> list[str]:
    return [g for g in mesh.vertex_groups if parenting.match(vtx_grp, g) is not None]
