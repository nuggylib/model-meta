from pathlib import Path

import pytest
from textual.app import App
from textual.signal import Signal
from textual.widgets import Button, Input, SelectionList, Static

from model_meta.core.results import (
    FieldCheck,
    MeshRoleResult,
    ModifiersResult,
    Results,
    TextureMapOverride,
)
from model_meta.tui.screens.check_detail import CheckDetailScreen
from model_meta.tui.screens.texture_map_override_modal import TextureMapOverrideModal
from model_meta.tui.widgets.selectable_row import SelectableRow

_WEIGHT_FAILURE = {
    "mesh": "wheel_hub.front.R",
    "vertex_group": "wheel_hub.front.R",
    "vertices": 340,
    "assigned": 328,
    "at_weight": 300,
}


def _results(**checks):
    return Results(model_file="/m/sedan.blend", spec="vehicle", **checks, path=None)


_ROLES = {
    "wheels": MeshRoleResult(
        ["wheel_hub.front.L", "wheel_hub.front.R"],
        {
            "count": FieldCheck([{"expected": 4, "matched": 2}]),
            "weight": FieldCheck([_WEIGHT_FAILURE]),
            "texture_maps": FieldCheck(
                [
                    {
                        "mesh": "wheel_hub.front.L",
                        "missing": ["orm"],
                        "expected": ["wheel_hub.front.L_orm.png"],
                        "has_default_uv_map": True,
                    },
                    {
                        "mesh": "wheel_hub.front.R",
                        "missing": ["albedo", "orm"],
                        "expected": [
                            "wheel_hub.front.R_albedo.png",
                            "wheel_hub.front.R_orm.png",
                        ],
                        "uv_error": "in edit mode",
                    },
                ],
                duplicates=[["wheel_hub.front.L", "wheel_hub.front.R"]],
            ),
        },
    ),
    "body": MeshRoleResult(["body"], {"material_slots": FieldCheck([])}),
}


class _Source:
    """Stands in for the model dashboard, recording each saved override."""

    model = Path("/m/sedan.blend")

    def __init__(self, results, updates):
        self.results = results
        self.results_changed = updates
        self.saved = []

    def texture_maps(self, _role):
        return ["albedo", "orm", "normal"]

    def add_texture_map_override(self, role, override):
        self.saved.append((role, override))


class _Host(App):
    def __init__(self, path, results):
        super().__init__()
        self.path = path
        self.results = results

    def on_mount(self):
        self.updates = Signal(self, "updates")
        self.source = _Source(self.results, self.updates)
        self.push_screen(
            CheckDetailScreen(self.source, self.path, ("Title", *self.path[1:]))
        )


def _lines(app):
    return [str(line.render()) for line in app.screen.query("#check-lines Static")]


def _sections(app):
    return {
        section.border_title: [str(line.render()) for line in section.query(Static)]
        for section in app.screen.query(".check-section")
    }


async def _open(path, results):
    app = _Host(path, results)
    async with app.run_test() as pilot:
        await pilot.pause()
        return _lines(app)


async def test_never_checked_field_says_so():
    assert await _open(("mesh_roles",), _results()) == ["No results yet."]


async def test_unreadable_results_say_no_results():
    assert await _open(("armature",), None) == ["No results yet."]


async def test_a_failing_bool_check_is_a_section_under_its_fix():
    app = _Host(("armature",), _results(armature=False))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _sections(app) == {
            "Needs Fixes": [
                "armature",
                "1. Name the armature object in Blender as the spec's `object_name`.",
            ],
            "armature": ["❌ failing"],
        }


async def test_mesh_roles_list_one_selectable_row_per_role():
    app = _Host(("mesh_roles",), _results(mesh_roles=_ROLES))
    async with app.run_test() as pilot:
        await pilot.pause()
        rows = list(app.screen.query(SelectableRow))
        assert [str(row.render()) for row in rows] == ["▸ ❌ wheels", "▸ ✅ body"]
        assert app.screen.focused is rows[0]


async def test_enter_on_a_role_opens_its_sections():
    app = _Host(("mesh_roles",), _results(mesh_roles=_ROLES))
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.path == ("mesh_roles", "wheels")
        title = str(app.screen.query_one("#check-title").render())
        assert title == "Models - sedan - Title - wheels"


async def test_a_role_shows_one_section_per_field_and_every_failure():
    app = _Host(("mesh_roles", "wheels"), _results(mesh_roles=_ROLES))
    async with app.run_test() as pilot:
        await pilot.pause()
        sections = _sections(app)
    assert list(sections)[0] == "Needs Fixes"
    assert sections == {
        "Needs Fixes": [
            "count",
            "1. Rename the role's meshes so exactly `count` of them fully match its "
            "`mesh_regex`.",
            "weight",
            "1. In Weight Paint mode, assign every vertex of each listed mesh to its "
            "group at the role's `weight`.",
            "texture_maps",
            "1. Bake a texture map named wheel_hub.front.L_orm.png for "
            "wheel_hub.front.L",
            "2. Bake a texture map named wheel_hub.front.R_albedo.png for "
            "wheel_hub.front.R",
            "3. Bake a texture map named wheel_hub.front.R_orm.png for "
            "wheel_hub.front.R",
        ],
        "meshes": ["wheel_hub.front.L, wheel_hub.front.R"],
        "count": ["❌ failing", "- expected: 4", "  matched: 2"],
        "weight": [
            "❌ failing",
            "- mesh: wheel_hub.front.R",
            "  vertex_group: wheel_hub.front.R",
            "  vertices: 340",
            "  assigned: 328",
            "  at_weight: 300",
        ],
        "texture_maps": [
            "❌ failing",
            "- mesh: wheel_hub.front.L",
            "  missing: orm",
            "  has_default_uv_map: True",
            "- mesh: wheel_hub.front.R",
            "  missing: albedo, orm",
            "  uv_error: in edit mode",
            "Warning: A mesh with `has_default_uv_map: True` may not be unwrapped "
            "yet: its UVs match a primitive's default layout. Check them before "
            "baking.",
        ],
        "texture_maps > duplicates": [
            _DUPLICATES_HELP,
            "▸ wheel_hub.front.L, wheel_hub.front.R",
        ],
    }


async def test_texture_fixes_name_the_override_file_and_skip_errors():
    failures = [
        {
            "mesh": "arm_top.FL",
            "missing": ["albedo"],
            "expected": ["arm_top_albedo.png"],
        },
        {"mesh": "arm_top.FR", "error": "no mesh"},
    ]
    roles = {"arms": MeshRoleResult(_ARMS, {"texture_maps": FieldCheck(failures)})}
    overrides = {"arms": [TextureMapOverride("arm_top", ["albedo"], _ARMS[:2])]}
    results = _results(mesh_roles=roles, texture_map_overrides=overrides)
    app = _Host(("mesh_roles", "arms"), results)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _sections(app)["Needs Fixes"] == [
            "texture_maps",
            "1. Bake a texture map named arm_top_albedo.png for arm_top.FL",
        ]


async def test_a_check_with_no_fix_text_adds_no_fix_section():
    failures = [{"mesh": "arm_top.FR", "error": "no mesh"}]
    roles = {"arms": MeshRoleResult(_ARMS, {"texture_maps": FieldCheck(failures)})}
    app = _Host(("mesh_roles", "arms"), _results(mesh_roles=roles))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "Needs Fixes" not in _sections(app)


_DUPLICATES_HELP = (
    "The meshes in each `duplicates` group have the same shape, so they can share "
    "texture maps. Select a group to link some of its maps under one name."
)
_ARMS = ["arm_top.FL", "arm_top.FR", "arm_top.RL"]
_ARM_ROLES = {
    "arms": MeshRoleResult(_ARMS, {"texture_maps": FieldCheck([], duplicates=[_ARMS])})
}


async def test_a_passing_texture_check_lists_its_duplicates_and_overrides():
    overrides = {"arms": [TextureMapOverride("arm_top", ["albedo"], _ARMS[:2])]}
    results = _results(mesh_roles=_ARM_ROLES, texture_map_overrides=overrides)
    app = _Host(("mesh_roles", "arms"), results)
    async with app.run_test() as pilot:
        await pilot.pause()
        sections = _sections(app)
        assert list(sections)[-2:] == ["texture_maps", "texture_maps > duplicates"]
        assert sections["texture_maps"] == ["✅ passing"]
        assert sections["texture_maps > duplicates"] == [
            _DUPLICATES_HELP,
            "▸ arm_top.FL, arm_top.FR, arm_top.RL",
            "texture_map_overrides:",
            "- name: arm_top",
            "  maps: albedo",
            "  meshes: arm_top.FL, arm_top.FR",
        ]


async def test_overrides_keep_the_duplicates_section_without_a_group():
    roles = {"arms": MeshRoleResult(_ARMS, {"texture_maps": FieldCheck([])})}
    overrides = {"arms": [TextureMapOverride("arm_top", ["albedo"], _ARMS[:2])]}
    results = _results(mesh_roles=roles, texture_map_overrides=overrides)
    app = _Host(("mesh_roles", "arms"), results)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _sections(app)["texture_maps > duplicates"] == [
            "texture_map_overrides:",
            "- name: arm_top",
            "  maps: albedo",
            "  meshes: arm_top.FL, arm_top.FR",
        ]


async def _open_link_modal(pilot, app):
    await pilot.pause()
    app.screen.query_one(SelectableRow).focus()
    await pilot.press("enter")
    await pilot.pause()
    assert isinstance(app.screen, TextureMapOverrideModal)
    return app.screen


async def test_linking_a_group_saves_the_checked_meshes_and_maps_under_the_name():
    app = _Host(("mesh_roles", "arms"), _results(mesh_roles=_ARM_ROLES))
    async with app.run_test() as pilot:
        modal = await _open_link_modal(pilot, app)
        modal.query_one("#override-meshes", SelectionList).deselect("arm_top.RL")
        modal.query_one("#override-maps", SelectionList).select("normal")
        modal.query_one("#override-maps", SelectionList).select("albedo")
        modal.query_one("#override-name", Input).value = " arm_top "
        await pilot.pause()
        preview = str(modal.query_one("#override-preview", Static).render())
        assert preview == "Expected: arm_top_albedo.png, arm_top_normal.png"
        modal.query_one("#override-name", Input).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert app.source.saved == [
            (
                "arms",
                TextureMapOverride("arm_top", ["albedo", "normal"], _ARMS[:2]),
            )
        ]
        assert isinstance(app.screen, CheckDetailScreen)


@pytest.mark.parametrize(
    ("meshes", "maps", "name", "problem"),
    [
        (_ARMS[:1], ["albedo"], "arm_top", "Check at least two meshes to link."),
        (_ARMS, [], "arm_top", "Check at least one map to share."),
        (_ARMS, ["albedo"], "  ", "Type the shared name."),
        (_ARMS, ["albedo"], "arms/top", "The shared name can't hold `/` or `\\`."),
    ],
)
async def test_an_incomplete_link_says_why_and_saves_nothing(
    meshes, maps, name, problem
):
    app = _Host(("mesh_roles", "arms"), _results(mesh_roles=_ARM_ROLES))
    async with app.run_test() as pilot:
        modal = await _open_link_modal(pilot, app)
        mesh_list = modal.query_one("#override-meshes", SelectionList)
        mesh_list.deselect_all()
        for mesh in meshes:
            mesh_list.select(mesh)
        for name_ in maps:
            modal.query_one("#override-maps", SelectionList).select(name_)
        modal.query_one("#override-name", Input).value = name
        modal.query_one("#save-override", Button).press()
        await pilot.pause()
        assert str(modal.query_one("#override-status", Static).render()) == problem
        assert app.screen is modal
        assert app.source.saved == []


async def test_escape_closes_the_link_modal_and_saves_nothing():
    app = _Host(("mesh_roles", "arms"), _results(mesh_roles=_ARM_ROLES))
    async with app.run_test() as pilot:
        await _open_link_modal(pilot, app)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, CheckDetailScreen)
        assert app.source.saved == []


async def test_no_default_uv_map_shows_no_warning():
    failure = {"mesh": "body", "missing": ["orm"]}
    roles = {"body": MeshRoleResult(["body"], {"texture_maps": FieldCheck([failure])})}
    app = _Host(("mesh_roles", "body"), _results(mesh_roles=roles))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not app.screen.query(".check-warning")


async def test_a_passing_field_is_its_section_and_one_passing_line():
    app = _Host(("mesh_roles", "body"), _results(mesh_roles=_ROLES))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _sections(app) == {
            "meshes": ["body"],
            "material_slots": ["✅ passing"],
        }


async def test_an_error_failure_is_listed_as_a_fact():
    roles = {"body": MeshRoleResult([], {"count": FieldCheck([{"error": "x"}])})}
    app = _Host(("mesh_roles", "body"), _results(mesh_roles=roles))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _sections(app)["count"][:2] == ["❌ failing", "- error: x"]


async def test_published_results_relabel_the_role_rows_in_place():
    app = _Host(("mesh_roles",), _results(mesh_roles=_ROLES))
    async with app.run_test() as pilot:
        await pilot.pause()
        body = app.screen.query(SelectableRow).last()
        passing = {**_ROLES, "wheels": MeshRoleResult(["w"], {})}
        app.updates.publish(_results(mesh_roles=passing))
        for _ in range(20):
            await pilot.pause()
            if str(app.screen.query(SelectableRow).first().render()) == "▸ 🟡 wheels":
                break
        assert str(app.screen.query(SelectableRow).first().render()) == "▸ 🟡 wheels"
        assert app.screen.query(SelectableRow).last() is body


_MODIFIERS = ModifiersResult(
    {"skinned_meshes": FieldCheck([{"mesh": "body", "missing": ["ARMATURE"]}])},
    FieldCheck([{"mesh": "body", "modifiers": ["MIRROR", "SUBSURF"]}], warning=True),
    FieldCheck([]),
)
_MODIFIER_SECTIONS = {
    "required > skinned_meshes": ["❌ failing", "- mesh: body", "  missing: ARMATURE"],
    "warn": ["⚠️ warning", "- mesh: body", "  modifiers: MIRROR, SUBSURF"],
    "fail": ["✅ passing"],
}
_MODIFIER_FIXES = {
    "required > skinned_meshes": "1. Add each missing modifier to the listed mesh in "
    "its Modifier Properties.",
    "warn": "1. Confirm each listed modifier belongs on the mesh, or apply or remove "
    "it before export.",
}


def _fix_lines(prefix=""):
    return [
        line
        for label, fix in _MODIFIER_FIXES.items()
        for line in (f"{prefix}{label}", fix)
    ]


async def test_modifiers_show_a_section_per_list_titled_by_its_path():
    app = _Host(("modifiers",), _results(modifiers=_MODIFIERS))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _sections(app) == {"Needs Fixes": _fix_lines(), **_MODIFIER_SECTIONS}


async def test_a_role_shows_its_own_modifier_sections():
    roles = {"body": MeshRoleResult(["body"], {}, _MODIFIERS)}
    app = _Host(("mesh_roles", "body"), _results(mesh_roles=roles))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _sections(app) == {
            "Needs Fixes": _fix_lines("modifiers > "),
            "meshes": ["body"],
            **{
                f"modifiers > {key}": lines for key, lines in _MODIFIER_SECTIONS.items()
            },
        }


async def test_a_role_with_only_a_warning_has_a_warning_row():
    warned = ModifiersResult(
        {"skinned_meshes": FieldCheck([])},
        FieldCheck([{"mesh": "body", "modifiers": ["MIRROR"]}], warning=True),
        FieldCheck([]),
    )
    roles = {**_ROLES, "body": MeshRoleResult(["body"], {}, warned)}
    app = _Host(("mesh_roles",), _results(mesh_roles=roles))
    async with app.run_test() as pilot:
        await pilot.pause()
        rows = [str(row.render()) for row in app.screen.query(SelectableRow)]
        assert rows == ["▸ ❌ wheels", "▸ ⚠️ body"]


async def test_published_results_replace_the_page():
    app = _Host(("armature",), _results(armature=False))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.updates.publish(_results(armature=True))
        for _ in range(20):
            await pilot.pause()
            if _sections(app) == {"armature": ["✅ passing"]}:
                break
        assert _sections(app) == {"armature": ["✅ passing"]}
