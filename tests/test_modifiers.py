"""Unit tests for modifier-list logic (model_meta.specs.modifiers)."""

import pytest

from model_meta.core.spec import Modifiers, RequiredModifiers
from model_meta.specs import modifiers, schema


def _mods(skinned_meshes=("ARMATURE",), allowed=(), warn=(), fail=()):
    return Modifiers(
        required=RequiredModifiers(skinned_meshes=list(skinned_meshes)),
        allowed=list(allowed),
        warn=list(warn),
        fail=list(fail),
    )


# --- get -------------------------------------------------------------------


def test_get_reads_skinned_meshes_from_required():
    mods = _mods(skinned_meshes=["ARMATURE"], warn=["MIRROR"])
    assert modifiers.get(mods, "skinned_meshes") == ["ARMATURE"]
    assert modifiers.get(mods, "warn") == ["MIRROR"]


# --- choices ---------------------------------------------------------------


def test_choices_without_extras_is_the_schema():
    assert modifiers.choices(_mods(fail=["BOOLEAN"])) == list(schema.MODIFIERS)


def test_choices_appends_unknown_names_once_in_list_order():
    mods = _mods(
        skinned_meshes=["armature"],
        allowed=["NODES"],
        warn=["NODES", "MIRROR"],
        fail=["armature", "SKIN"],
    )
    assert modifiers.choices(mods) == [*schema.MODIFIERS, "armature", "NODES", "SKIN"]


# --- conflicts -------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("skinned_meshes", {"BOOLEAN": ["fail"]}),
        ("allowed", {"MIRROR": ["warn"], "BOOLEAN": ["fail"]}),
        ("warn", {"TRIANGULATE": ["allowed"], "BOOLEAN": ["fail"]}),
        (
            "fail",
            {
                "ARMATURE": ["skinned_meshes"],
                "TRIANGULATE": ["allowed"],
                "MIRROR": ["warn"],
            },
        ),
    ],
)
def test_conflicts_follow_the_category_rules(name, expected):
    mods = _mods(
        skinned_meshes=["ARMATURE"],
        allowed=["TRIANGULATE"],
        warn=["MIRROR"],
        fail=["BOOLEAN"],
    )
    assert modifiers.conflicts(mods, name) == expected


def test_conflicts_name_every_list_a_hand_written_overlap_sits_in():
    mods = _mods(warn=["MIRROR", "MIRROR"], fail=["MIRROR"])
    assert modifiers.conflicts(mods, "allowed") == {"MIRROR": ["warn", "fail"]}


# --- assign ----------------------------------------------------------------


def test_assign_orders_by_choices_and_dedupes():
    mods = _mods(allowed=["NODES", "WELD", "WELD"])
    after = modifiers.assign(mods, "allowed", ["NODES", "WELD", "BEVEL"])
    assert after.allowed == ["BEVEL", "WELD", "NODES"]


def test_assign_moves_checked_names_out_of_conflicting_lists():
    mods = _mods(allowed=["MIRROR"], warn=["SUBSURF"], fail=["BOOLEAN", "REMESH"])
    after = modifiers.assign(mods, "allowed", ["MIRROR", "BOOLEAN"])
    assert after == _mods(
        allowed=["BOOLEAN", "MIRROR"], warn=["SUBSURF"], fail=["REMESH"]
    )


def test_assign_moves_between_fail_and_skinned_meshes():
    into_fail = modifiers.assign(_mods(), "fail", ["ARMATURE"])
    assert into_fail == _mods(skinned_meshes=[], fail=["ARMATURE"])
    back = modifiers.assign(into_fail, "skinned_meshes", ["ARMATURE"])
    assert back == _mods()


def test_assign_leaves_required_alone_when_editing_allowed_or_warn():
    after = modifiers.assign(_mods(), "warn", ["ARMATURE"])
    assert after == _mods(warn=["ARMATURE"])


def test_assign_unchecking_only_removes_from_this_list():
    mods = _mods(allowed=["MIRROR", "WELD"])
    after = modifiers.assign(mods, "allowed", ["WELD"])
    assert after == _mods(allowed=["WELD"])


def test_assign_of_nothing_empties_the_list():
    assert modifiers.assign(_mods(), "skinned_meshes", []) == _mods(skinned_meshes=[])


def test_assign_keeps_extra_and_leaves_the_input_alone():
    mods = _mods(fail=["BOOLEAN"])
    mods.extra = {"notes": "x"}
    mods.required.extra = {"static_meshes": []}
    after = modifiers.assign(mods, "warn", ["BOOLEAN"])
    assert after.extra == {"notes": "x"}
    assert after.required.extra == {"static_meshes": []}
    assert mods.fail == ["BOOLEAN"]
    assert mods.warn == []


# --- format_list -----------------------------------------------------------


@pytest.mark.parametrize(
    ("names", "expected"),
    [([], "[]"), (["ARMATURE"], "ARMATURE"), (["BEVEL", "WELD"], "BEVEL, WELD")],
)
def test_format_list(names, expected):
    assert modifiers.format_list(names) == expected
