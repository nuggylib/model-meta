from dataclasses import replace

import pytest

from model_meta.checks import mesh_roles
from model_meta.core.blender_bridge import (
    MeshReport,
    MeshTarget,
    MeshTextures,
    MeshUvs,
    MeshWeight,
    SceneMesh,
    TextureImage,
    WeightTarget,
)
from model_meta.core.results import FieldCheck, MeshRoleResult
from model_meta.core.spec import MeshRole

WHEELS = MeshRole(
    mesh_regex=r"wheel_hub\.(front|rear)\.[LR]",
    vtx_grp="wheel_hub.{1}.{2}",
    count=4,
    weight=1.0,
    texture_maps=["albedo", "orm"],
    material_slots=["rubber"],
)
BODY = MeshRole(
    mesh_regex="body",
    vtx_grp="body",
    count=1,
    weight=1.0,
    material_slots=["paint", "glass"],
)
ROLES = {"wheels": WHEELS, "body": BODY}
ALL_FIELDS = ("count", "vtx_grp", "weight", "texture_maps", "material_slots")
BODY_FIELDS = ("count", "vtx_grp", "weight", "material_slots")

WHEEL_NAMES = [
    "wheel_hub.front.L",
    "wheel_hub.front.R",
    "wheel_hub.rear.L",
    "wheel_hub.rear.R",
]


def _wheel(name, groups=None, slots=("rubber",)):
    # "paint" is a recoloring group: never a skinning target.
    return SceneMesh(name, [name, "paint"] if groups is None else groups, list(slots))


SCENE = [
    SceneMesh("body", ["body"], ["paint", "glass"]),
    *(_wheel(name) for name in WHEEL_NAMES),
]


def _passing_weight(target):
    return MeshWeight(target.mesh, target.vertex_group, 340, 340, 340)


def _images(mesh, *maps):
    return MeshTextures(
        mesh,
        [TextureImage(f"{mesh}_{m}", f"/textures/{mesh}_{m}.png") for m in maps],
    )


def _passing_textures(target):
    return _images(target.mesh, "albedo", "orm", "normal")


def _unwrapped(target):
    return MeshUvs(target.mesh, False)


def _answer(answer, targets):
    """`None` stands for an add-on that predates the request."""
    return None if answer is None else [answer(target) for target in targets]


def _report(
    roles=ROLES,
    meshes=SCENE,
    weight=_passing_weight,
    textures=_passing_textures,
    uvs=_unwrapped,
):
    weights, textured, _ = mesh_roles.plan(roles, meshes)
    return MeshReport(
        meshes,
        _answer(weight, weights),
        _answer(textures, textured),
        _answer(uvs, textured),
        None,
        None,
    )


def _evaluate(roles=ROLES, **answers):
    return mesh_roles.evaluate(roles, _report(roles, **answers))


def _failures(result):
    return {field: check.failures for field, check in result.checks.items()}


def test_plan_targets_every_matching_group_and_each_textured_and_matched_mesh():
    weights, textured, modifiers = mesh_roles.plan(ROLES, SCENE)
    assert weights == [
        *(WeightTarget(name, name, 1.0) for name in WHEEL_NAMES),
        WeightTarget("body", "body", 1.0),
    ]
    assert textured == [MeshTarget(name) for name in WHEEL_NAMES]
    assert modifiers == [MeshTarget(name) for name in [*WHEEL_NAMES, "body"]]


def test_plan_dedupes_targets_shared_by_two_roles():
    hubs = MeshRole(
        mesh_regex=r"wheel_hub\.front\.L",
        vtx_grp="wheel_hub.front.L",
        weight=1.0,
        texture_maps=["normal", "albedo"],
    )
    plan = mesh_roles.plan({"wheels": WHEELS, "hubs": hubs}, SCENE)
    weights, textured, modifiers = plan
    front_left = "wheel_hub.front.L"
    assert weights.count(WeightTarget(front_left, front_left, 1.0)) == 1
    assert textured.count(MeshTarget(front_left)) == 1
    assert modifiers.count(MeshTarget(front_left)) == 1


def test_plan_fetches_only_modifiers_for_roles_without_weights_or_maps():
    roles = {
        "unweighted": replace(WHEELS, weight=None, texture_maps=None),
        "no_regex": replace(WHEELS, mesh_regex=None),
    }
    modifiers = [MeshTarget(name) for name in WHEEL_NAMES]
    assert mesh_roles.plan(roles, SCENE) == ([], [], modifiers)


def test_a_matching_scene_passes_every_set_field():
    results = _evaluate()
    assert results["wheels"] == MeshRoleResult(
        WHEEL_NAMES, {field: FieldCheck([]) for field in ALL_FIELDS}
    )
    assert results["body"] == MeshRoleResult(
        ["body"], {field: FieldCheck([]) for field in BODY_FIELDS}
    )


def test_unset_fields_are_left_out():
    results = _evaluate({"wheels": MeshRole(mesh_regex=WHEELS.mesh_regex)})
    assert results["wheels"] == MeshRoleResult(WHEEL_NAMES, {})


def test_mesh_regex_must_match_the_whole_name():
    meshes = [*SCENE, _wheel("wheel_hub.front.L.001")]
    assert _evaluate(meshes=meshes)["wheels"].meshes == WHEEL_NAMES


def test_a_wrong_count_names_what_matched():
    result = _evaluate(meshes=SCENE[:-1])["wheels"]
    assert result.meshes == WHEEL_NAMES[:-1]
    assert result.checks["count"] == FieldCheck([{"expected": 4, "matched": 3}])
    assert not result.checks["count"].passed


def test_a_mesh_without_a_matching_group_fails_vtx_grp_and_weight():
    meshes = [*SCENE[:-1], _wheel("wheel_hub.rear.R", groups=["paint"])]
    failures = _failures(_evaluate(meshes=meshes)["wheels"])
    assert failures["vtx_grp"] == [{"mesh": "wheel_hub.rear.R"}]
    assert failures["weight"] == [
        {"mesh": "wheel_hub.rear.R", "error": "no vertex group"}
    ]


def test_every_matching_group_is_weight_checked():
    meshes = [
        SCENE[0],
        _wheel("wheel_hub.front.L", groups=["wheel_hub.front.L", "wheel_hub.front.R"]),
        *SCENE[2:],
    ]

    def weight(target):
        if target == WeightTarget("wheel_hub.front.L", "wheel_hub.front.R", 1.0):
            return MeshWeight(target.mesh, target.vertex_group, 340, 328, 300)
        return _passing_weight(target)

    failures = _failures(_evaluate(meshes=meshes, weight=weight)["wheels"])
    assert failures["vtx_grp"] == []
    assert failures["weight"] == [
        {
            "mesh": "wheel_hub.front.L",
            "vertex_group": "wheel_hub.front.R",
            "vertices": 340,
            "assigned": 328,
            "at_weight": 300,
        }
    ]


def test_a_bridge_weight_error_is_a_failure():
    def weight(target):
        return MeshWeight(target.mesh, target.vertex_group, error="no vertex group")

    failures = _failures(_evaluate({"body": BODY}, weight=weight)["body"])
    assert failures["weight"] == [
        {"mesh": "body", "vertex_group": "body", "error": "no vertex group"}
    ]


def test_weight_without_vtx_grp_fails():
    role = replace(BODY, vtx_grp=None)
    failures = _failures(_evaluate({"body": role})["body"])
    assert failures["weight"] == [{"error": "vtx_grp not set"}]


def test_missing_texture_maps_are_named_per_mesh():
    def textures(target):
        if target.mesh == "wheel_hub.front.R":
            # Unsaved, and saved under another mesh's name: neither counts.
            return MeshTextures(
                target.mesh,
                [
                    TextureImage("wheel_hub.front.R_albedo", None),
                    TextureImage("orm", "/textures/wheel_hub.front.L_orm.png"),
                    TextureImage("albedo", "/textures/wheel_hub.front.R_albedo.png"),
                ],
            )
        if target.mesh == "wheel_hub.rear.L":
            return _images(target.mesh, "albedo")
        if target.mesh == "wheel_hub.rear.R":
            return MeshTextures(target.mesh, [], "no mesh")
        return _passing_textures(target)

    failures = _failures(_evaluate(textures=textures)["wheels"])
    assert failures["texture_maps"] == [
        {
            "mesh": "wheel_hub.front.R",
            "missing": ["orm"],
            "expected": ["wheel_hub.front.R_orm.png"],
        },
        {
            "mesh": "wheel_hub.rear.L",
            "missing": ["orm"],
            "expected": ["wheel_hub.rear.L_orm.png"],
        },
        {"mesh": "wheel_hub.rear.R", "error": "no mesh"},
    ]


def test_texture_maps_list_the_roles_duplicate_groups_even_when_passing():
    groups = [
        ["spare", "wheel_hub.front.L", "wheel_hub.front.R"],
        ["wheel_hub.rear.L", "wheel_hub.rear.R"],
        ["body", "stand"],
    ]
    report = replace(_report(), duplicates=groups)
    check = mesh_roles.evaluate(ROLES, report)["wheels"].checks["texture_maps"]
    assert check == FieldCheck(
        [],
        duplicates=[
            ["wheel_hub.front.L", "wheel_hub.front.R"],
            ["wheel_hub.rear.L", "wheel_hub.rear.R"],
        ],
    )


def test_an_addon_before_image_reports_fails_texture_maps():
    failures = _failures(_evaluate(textures=None)["wheels"])
    assert failures["texture_maps"] == [{"error": "add-on before 0.5.1"}]


def _missing_albedo(target):
    return _images(target.mesh, "orm")


def test_a_missing_map_carries_the_meshes_uv_report():
    def uvs(target):
        if target.mesh == "wheel_hub.front.L":
            return MeshUvs(target.mesh, True)
        if target.mesh == "wheel_hub.rear.L":
            return MeshUvs(target.mesh, False, "in edit mode")
        return _unwrapped(target)

    failures = _failures(_evaluate(textures=_missing_albedo, uvs=uvs)["wheels"])
    assert failures["texture_maps"] == [
        {**_missing("wheel_hub.front.L"), "has_default_uv_map": True},
        _missing("wheel_hub.front.R"),
        {**_missing("wheel_hub.rear.L"), "uv_error": "in edit mode"},
        _missing("wheel_hub.rear.R"),
    ]


def _missing(mesh):
    return {"mesh": mesh, "missing": ["albedo"], "expected": [f"{mesh}_albedo.png"]}


def test_an_addon_without_uvs_leaves_the_unwrap_out():
    failures = _failures(_evaluate(textures=_missing_albedo, uvs=None)["wheels"])
    assert failures["texture_maps"] == [_missing(name) for name in WHEEL_NAMES]


def test_material_slots_must_all_be_present_in_any_order():
    meshes = [
        SceneMesh("body", ["body"], ["glass", "chrome", "paint"]),
        _wheel("wheel_hub.front.L", slots=()),
        *SCENE[2:],
    ]
    results = _evaluate(meshes=meshes)
    assert results["body"].checks["material_slots"].passed
    assert _failures(results["wheels"])["material_slots"] == [
        {"mesh": "wheel_hub.front.L", "missing": ["rubber"]}
    ]


def test_no_matched_meshes_fails_every_field():
    failures = _failures(_evaluate(meshes=SCENE[:1])["wheels"])
    assert failures == {
        "count": [{"expected": 4, "matched": 0}],
        **{field: [{"error": "no meshes matched"}] for field in ALL_FIELDS[1:]},
    }


@pytest.mark.parametrize(
    ("regex", "error"),
    [(None, "mesh_regex not set"), ("body(", "mesh_regex doesn't compile")],
)
def test_an_unusable_mesh_regex_fails_every_set_field(regex, error):
    result = _evaluate({"body": replace(BODY, mesh_regex=regex)})["body"]
    assert result.meshes == []
    assert _failures(result) == {field: [{"error": error}] for field in BODY_FIELDS}
