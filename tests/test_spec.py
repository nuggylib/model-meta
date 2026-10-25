import json

import pytest

from model_meta.core.spec import Armature, MeshRole, Spec

_FULL = {
    "model_type": "vehicle",
    "armature": {
        "object_name": "rig",
        "required_bones": ["root", "window_fl"],
        "bone_name_inverses": {"_fl": "_fr"},
        "parenting": {"root": ["window_fl"]},
    },
    "mesh_roles": {
        "body": {
            "mesh_regex": "^body",
            "vtx_grp": "body",
            "count": 1,
            "weight": 0.5,
            "texture_maps": ["albedo"],
            "material_slots": ["paint", "glass"],
        },
        # An animated front-left window: skinned to its own bone, so it gets a role.
        "window_fl": {"mesh_regex": "^window_fl", "vtx_grp": "window_fl"},
    },
}


def _spec(data, tmp_path):
    return Spec.from_dict(data, path=tmp_path / "vehicle.json")


def _with_role(role):
    return {**_FULL, "mesh_roles": {"body": role}}


def test_a_full_spec_round_trips_in_key_order(tmp_path):
    written = _spec(_FULL, tmp_path).to_dict()
    assert written == _FULL
    assert json.dumps(written) == json.dumps(_FULL)


def test_a_full_spec_parses_into_typed_fields(tmp_path):
    spec = _spec(_FULL, tmp_path)
    assert spec.model_type == "vehicle"
    assert spec.armature.parenting == {"root": ["window_fl"]}
    assert spec.mesh_roles["body"] == MeshRole(
        vtx_grp="body",
        mesh_regex="^body",
        count=1,
        weight=0.5,
        texture_maps=["albedo"],
        material_slots=["paint", "glass"],
    )
    assert spec.mesh_roles["window_fl"] == MeshRole(
        vtx_grp="window_fl", mesh_regex="^window_fl"
    )


def test_an_empty_role_has_every_field_absent(tmp_path):
    spec = _spec(_with_role({}), tmp_path)
    assert spec.mesh_roles["body"] == MeshRole()
    assert spec.to_dict()["mesh_roles"]["body"] == {}


def test_role_keys_are_written_in_canonical_order_then_extra(tmp_path):
    role = {
        "future": True,
        "material_slots": ["paint"],
        "weight": 1,
        "vtx_grp": "body",
        "texture_maps": ["albedo"],
        "count": 2,
        "mesh_regex": "^body",
    }
    written = _spec(_with_role(role), tmp_path).to_dict()["mesh_roles"]["body"]
    assert list(written) == [
        "mesh_regex",
        "vtx_grp",
        "count",
        "weight",
        "texture_maps",
        "material_slots",
        "future",
    ]


def test_empty_material_slots_are_omitted_on_write(tmp_path):
    spec = _spec(_with_role({"vtx_grp": "body", "material_slots": []}), tmp_path)
    assert spec.mesh_roles["body"].material_slots == []
    assert spec.to_dict()["mesh_roles"]["body"] == {"vtx_grp": "body"}


def test_unknown_keys_survive_at_every_level(tmp_path):
    data = {
        **_FULL,
        "modifiers": ["bevel"],
        "armature": {**_FULL["armature"], "ik": {"leg": "foot"}},
        "mesh_roles": {"window_fl": {"vtx_grp": "window_fl", "hinge": "top"}},
    }
    spec = _spec(data, tmp_path)
    assert spec.extra == {"modifiers": ["bevel"]}
    assert spec.armature.extra == {"ik": {"leg": "foot"}}
    assert spec.mesh_roles["window_fl"].extra == {"hinge": "top"}
    assert spec.to_dict() == data


def test_missing_keys_default_and_are_added_on_write(tmp_path):
    spec = _spec({"model_type": "vehicle"}, tmp_path)
    assert spec.armature == Armature()
    assert spec.mesh_roles == {}
    assert spec.to_dict() == {
        "model_type": "vehicle",
        "armature": {
            "object_name": "",
            "required_bones": [],
            "bone_name_inverses": {},
            "parenting": {},
        },
        "mesh_roles": {},
    }


def test_a_missing_model_type_stays_absent_on_write(tmp_path):
    spec = _spec({}, tmp_path)
    assert spec.model_type is None
    assert "model_type" not in spec.to_dict()


@pytest.mark.parametrize(
    "payload",
    [
        {"model_type": 3},
        {"armature": []},
        {"armature": {"required_bones": "body"}},
        {"armature": {"required_bones": ["body", 3]}},
        {"armature": {"bone_name_inverses": []}},
        {"armature": {"bone_name_inverses": {"_fl": 1}}},
        {"armature": {"object_name": 3}},
        {"armature": {"parenting": []}},
        {"armature": {"parenting": {"root": "window_fl"}}},
        {"armature": {"parenting": {"root": [3]}}},
        {"mesh_roles": []},
        {"mesh_roles": {"body": "body"}},
    ],
    ids=[
        "model-type-not-string",
        "armature-not-object",
        "bones-not-list",
        "bones-not-strings",
        "inverses-not-object",
        "inverses-not-strings",
        "object-name-not-string",
        "parenting-not-object",
        "parenting-not-lists",
        "parenting-not-strings",
        "mesh-roles-not-object",
        "mesh-role-not-object",
    ],
)
def test_a_malformed_spec_is_rejected(tmp_path, payload):
    with pytest.raises(ValueError):
        _spec(payload, tmp_path)


@pytest.mark.parametrize(
    ("role", "message"),
    [
        ({"vtx_grp": 3}, "`vtx_grp` is not a string"),
        ({"mesh_regex": 5}, "`mesh_regex` is not a string"),
        ({"count": "4"}, "`count` is not a whole number"),
        ({"count": 4.0}, "`count` is not a whole number"),
        ({"count": True}, "`count` is not a whole number"),
        ({"weight": "1"}, "`weight` is not a number"),
        ({"weight": True}, "`weight` is not a number"),
        ({"weight": None}, "`weight` is not a number"),
        ({"texture_maps": "albedo"}, "`texture_maps` is not a list of strings"),
        ({"texture_maps": [1]}, "`texture_maps` is not a list of strings"),
        ({"texture_maps": None}, "`texture_maps` is not a list of strings"),
        ({"material_slots": "paint"}, "`material_slots` is not a list of strings"),
        ({"material_slots": [1]}, "`material_slots` is not a list of strings"),
        ({"material_slots": None}, "`material_slots` is not a list of strings"),
    ],
)
def test_a_malformed_role_is_rejected_with_a_reason(tmp_path, role, message):
    with pytest.raises(ValueError, match=message):
        _spec(_with_role(role), tmp_path)


@pytest.mark.parametrize("weight", [1, 0.0])
def test_integer_and_float_weights_are_accepted(tmp_path, weight):
    spec = _spec(_with_role({"weight": weight}), tmp_path)
    assert spec.mesh_roles["body"].weight == weight


def test_load_then_save_round_trips_on_disk(tmp_path):
    path = tmp_path / "vehicle.json"
    path.write_text(json.dumps(_FULL), encoding="utf-8")
    spec = Spec.load(path)
    spec.mesh_roles["window_fl"].count = 2
    spec.save()
    assert Spec.load(path) == spec
    assert json.loads(path.read_text(encoding="utf-8"))["mesh_roles"]["window_fl"] == {
        "mesh_regex": "^window_fl",
        "vtx_grp": "window_fl",
        "count": 2,
    }


def test_save_refuses_a_mistyped_field_and_keeps_the_file(tmp_path):
    path = tmp_path / "vehicle.json"
    path.write_text(json.dumps(_FULL), encoding="utf-8")
    spec = Spec.load(path)
    spec.mesh_roles["body"].count = "4"
    with pytest.raises(ValueError, match="`count` is not a whole number"):
        spec.save()
    assert json.loads(path.read_text(encoding="utf-8")) == _FULL


def test_path_for_joins_a_normalized_name(tmp_path):
    assert Spec.path_for(tmp_path, "vehicle") == tmp_path / "vehicle.json"


@pytest.mark.parametrize(
    ("model_type", "message"),
    [
        ("", "Enter a name"),
        ("../escape", "letters, numbers"),
        ("a/b", "letters, numbers"),
        ("con", "reserved"),
        ("Vehicle", "not normalized"),
        (" vehicle", "not normalized"),
        ("big truck", "not normalized"),
    ],
)
def test_path_for_rejects_an_unusable_name(tmp_path, model_type, message):
    with pytest.raises(ValueError, match=message):
        Spec.path_for(tmp_path, model_type)
