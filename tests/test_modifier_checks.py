from model_meta.checks import modifiers
from model_meta.core.blender_bridge import MeshModifiers
from model_meta.core.results import FieldCheck, MeshRoleResult, ModifiersResult
from model_meta.core.spec import Modifiers, RequiredModifiers

MODS = Modifiers(
    required=RequiredModifiers(["ARMATURE"]),
    allowed=["TRIANGULATE"],
    warn=["MIRROR", "SUBSURF"],
    fail=["BOOLEAN"],
)
ROLES = {
    "wheels": MeshRoleResult(["wheel.L", "wheel.R"], {"count": FieldCheck([])}),
    "body": MeshRoleResult(["body"], {"count": FieldCheck([])}),
}


def _evaluate(stacks, roles=ROLES, mods=MODS):
    report = [MeshModifiers(mesh, stack) for mesh, stack in stacks.items()]
    return modifiers.evaluate(mods, roles, report)


def _passing():
    return ModifiersResult(
        {"skinned_meshes": FieldCheck([])},
        FieldCheck([], warning=True),
        FieldCheck([]),
    )


def test_skinned_meshes_with_no_listed_modifiers_pass():
    root, roles = _evaluate(
        {
            "wheel.L": ["ARMATURE"],
            "wheel.R": ["ARMATURE", "TRIANGULATE"],
            "body": ["ARMATURE", "WELD"],
        }
    )
    assert root == _passing()
    assert roles["wheels"] == MeshRoleResult(
        ["wheel.L", "wheel.R"], {"count": FieldCheck([])}, _passing()
    )


def test_each_mesh_lists_its_missing_warn_and_fail_modifiers():
    root, _ = _evaluate(
        {
            "wheel.L": ["SUBSURF", "MIRROR", "SUBSURF"],
            "wheel.R": ["ARMATURE", "BOOLEAN"],
            "body": [],
        }
    )
    assert root == ModifiersResult(
        {
            "skinned_meshes": FieldCheck(
                [
                    {"mesh": "wheel.L", "missing": ["ARMATURE"]},
                    {"mesh": "body", "missing": ["ARMATURE"]},
                ]
            )
        },
        FieldCheck(
            [{"mesh": "wheel.L", "modifiers": ["SUBSURF", "MIRROR"]}], warning=True
        ),
        FieldCheck([{"mesh": "wheel.R", "modifiers": ["BOOLEAN"]}]),
    )


def test_a_role_checks_only_its_own_meshes():
    _, roles = _evaluate({"wheel.L": ["ARMATURE"], "wheel.R": ["ARMATURE"], "body": []})
    assert roles["wheels"].modifiers == _passing()
    assert roles["body"].modifiers.required["skinned_meshes"] == FieldCheck(
        [{"mesh": "body", "missing": ["ARMATURE"]}]
    )


def test_a_mesh_in_two_roles_is_listed_once_at_the_root():
    roles = {**ROLES, "left": MeshRoleResult(["wheel.L"], {})}
    root, _ = _evaluate(
        {"wheel.L": [], "wheel.R": ["ARMATURE"], "body": ["ARMATURE"]}, roles
    )
    assert root.required["skinned_meshes"] == FieldCheck(
        [{"mesh": "wheel.L", "missing": ["ARMATURE"]}]
    )


def test_a_mesh_gone_from_the_report_is_an_error_in_every_check():
    report = [
        MeshModifiers("wheel.L", ["ARMATURE"]),
        MeshModifiers("wheel.R", [], "no mesh"),
        MeshModifiers("body", ["ARMATURE"]),
    ]
    root, _ = modifiers.evaluate(MODS, ROLES, report)
    error = [{"mesh": "wheel.R", "error": "no mesh"}]
    assert root == ModifiersResult(
        {"skinned_meshes": FieldCheck(error)},
        FieldCheck(error, warning=True),
        FieldCheck(error),
    )


def test_a_role_with_no_meshes_fails_every_check():
    roles = {**ROLES, "spoiler": MeshRoleResult([], {})}
    stacks = {"wheel.L": ["ARMATURE"], "wheel.R": ["ARMATURE"], "body": ["ARMATURE"]}
    root, checked = _evaluate(stacks, roles)
    unmatched = [{"error": "no meshes matched"}]
    assert checked["spoiler"].modifiers == ModifiersResult(
        {"skinned_meshes": FieldCheck(unmatched)},
        FieldCheck(unmatched, warning=True),
        FieldCheck(unmatched),
    )
    assert root == _passing()


def test_no_roles_pass_at_the_root():
    assert _evaluate({}, roles={}) == (_passing(), {})
