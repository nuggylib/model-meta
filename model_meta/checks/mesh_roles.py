from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import PurePath

from model_meta.core.blender_bridge import (
    TEXTURES_VERSION,
    MeshReport,
    MeshTarget,
    MeshTextures,
    MeshUvs,
    MeshWeight,
    SceneMesh,
    WeightTarget,
)
from model_meta.core.results import FieldCheck, MeshRoleResult, TextureMapOverride
from model_meta.core.spec import MeshRole
from model_meta.specs import parenting

NO_MESHES = "no meshes matched"
OLD_ADDON = f"add-on before {'.'.join(map(str, TEXTURES_VERSION))}"


def plan(
    roles: Mapping[str, MeshRole], meshes: Sequence[SceneMesh]
) -> tuple[list[WeightTarget], list[MeshTarget], list[MeshTarget]]:
    """The bridge targets `evaluate` needs, deduped: weights, one target per textured
    mesh, and one per matched mesh."""
    weights: dict[WeightTarget, None] = {}
    textured: dict[str, None] = {}
    matched_names: dict[str, None] = {}
    for role in roles.values():
        matched, _ = _matched(role, meshes)
        for mesh in matched:
            matched_names[mesh.name] = None
            if role.weight is not None and role.vtx_grp is not None:
                for group in _groups(role.vtx_grp, mesh):
                    weights[WeightTarget(mesh.name, group, role.weight)] = None
            if role.texture_maps:
                textured[mesh.name] = None
    return (
        list(weights),
        [MeshTarget(mesh) for mesh in textured],
        [MeshTarget(mesh) for mesh in matched_names],
    )


def evaluate(
    roles: Mapping[str, MeshRole],
    report: MeshReport,
    overrides: Mapping[str, Sequence[TextureMapOverride]] | None = None,
) -> dict[str, MeshRoleResult]:
    """Pass a `report` fetched with `plan(roles, ...)`, so its items line up."""
    weight_targets, textured, _ = plan(roles, report.meshes)
    scene = _Scene(
        dict(zip(weight_targets, report.weights, strict=True)),
        _by_mesh(textured, report.textures),
        _by_mesh(textured, report.uvs),
        report.duplicates or [],
        {},
    )
    overrides = overrides or {}
    return {
        name: _role_result(
            role,
            report.meshes,
            replace(scene, stems=_stems(overrides.get(name, ()))),
        )
        for name, role in roles.items()
    }


def _stems(overrides: Sequence[TextureMapOverride]) -> dict[tuple[str, str], str]:
    """`(mesh, map)` → the name its texture file starts with. The first override wins."""
    stems: dict[tuple[str, str], str] = {}
    for override in overrides:
        for mesh in override.meshes:
            for name in override.maps:
                stems.setdefault((mesh, name), override.name)
    return stems


def _by_mesh(targets: list[MeshTarget], results: list | None) -> dict | None:
    if results is None:
        return None
    return {
        target.mesh: result for target, result in zip(targets, results, strict=True)
    }


@dataclass(frozen=True)
class _Scene:
    """`textures` / `uvs` are `None` when the add-on predates them."""

    weights: dict[WeightTarget, MeshWeight]
    textures: dict[str, MeshTextures] | None
    uvs: dict[str, MeshUvs] | None
    duplicates: list[list[str]]
    stems: dict[tuple[str, str], str]


def _role_result(
    role: MeshRole, meshes: Sequence[SceneMesh], scene: _Scene
) -> MeshRoleResult:
    matched, problem = _matched(role, meshes)
    checks = {}
    for field, is_set, check in _CHECKS:
        if not is_set(role):
            continue
        if problem is not None:
            checks[field] = FieldCheck([{"error": problem}])
        elif not matched and field != "count":
            checks[field] = FieldCheck([{"error": NO_MESHES}])
        else:
            checks[field] = check(role, matched, scene)
    return MeshRoleResult([mesh.name for mesh in matched], checks)


def _count(role: MeshRole, matched: list[SceneMesh], _scene: _Scene) -> FieldCheck:
    if len(matched) == role.count:
        return FieldCheck([])
    return FieldCheck([{"expected": role.count, "matched": len(matched)}])


def _vtx_grp(role: MeshRole, matched: list[SceneMesh], _scene: _Scene) -> FieldCheck:
    return FieldCheck(
        [{"mesh": mesh.name} for mesh in matched if not _groups(role.vtx_grp, mesh)]
    )


def _weight(role: MeshRole, matched: list[SceneMesh], scene: _Scene) -> FieldCheck:
    if role.vtx_grp is None:
        return FieldCheck([{"error": "vtx_grp not set"}])
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
    return FieldCheck(failures)


def _texture_maps(
    role: MeshRole, matched: list[SceneMesh], scene: _Scene
) -> FieldCheck:
    names = {mesh.name for mesh in matched}
    shared = [[n for n in group if n in names] for group in scene.duplicates]
    duplicates = [group for group in shared if len(group) > 1]
    if scene.textures is None:
        return FieldCheck([{"error": OLD_ADDON}], duplicates=duplicates)
    failures = []
    for mesh in matched:
        result = scene.textures[mesh.name]
        if result.error is not None:
            failures.append({"mesh": mesh.name, "error": result.error})
            continue
        files = [
            PurePath(image.filepath).name
            for image in result.images
            if image.filepath is not None
        ]
        expected = {
            name: f"{scene.stems.get((mesh.name, name), mesh.name)}_{name}.png"
            for name in role.texture_maps
        }
        missing = [
            name
            for name, file in expected.items()
            if not any(f.endswith(file) for f in files)
        ]
        if missing:
            failures.append(
                {
                    "mesh": mesh.name,
                    "missing": missing,
                    "expected": [expected[name] for name in missing],
                    **_unwrap(mesh.name, scene),
                }
            )
    return FieldCheck(failures, duplicates=duplicates)


def _unwrap(mesh: str, scene: _Scene) -> dict[str, object]:
    if scene.uvs is None:
        return {}
    result = scene.uvs[mesh]
    if result.error is not None:
        return {"uv_error": result.error}
    return {"has_default_uv_map": True} if result.has_default_uv_map else {}


def _material_slots(
    role: MeshRole, matched: list[SceneMesh], _scene: _Scene
) -> FieldCheck:
    failures = []
    for mesh in matched:
        missing = [s for s in role.material_slots if s not in mesh.material_slots]
        if missing:
            failures.append({"mesh": mesh.name, "missing": missing})
    return FieldCheck(failures)


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
