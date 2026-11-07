from pathlib import Path

from textual.app import App
from textual.signal import Signal
from textual.widgets import Static

from model_meta.core.results import FieldCheck, MeshRoleResult, Results
from model_meta.tui.screens.check_detail import CheckDetailScreen
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
                        "has_default_uv_map": True,
                    },
                    {
                        "mesh": "wheel_hub.front.R",
                        "missing": ["albedo", "orm"],
                        "uv_error": "in edit mode",
                    },
                ]
            ),
        },
    ),
    "body": MeshRoleResult(["body"], {"material_slots": FieldCheck([])}),
}


class _Host(App):
    def __init__(self, path, results):
        super().__init__()
        self.path = path
        self.results = results

    def on_mount(self):
        self.updates = Signal(self, "updates")
        self.push_screen(
            CheckDetailScreen(
                Path("/m/sedan.blend"),
                self.path,
                ("Title", *self.path[1:]),
                self.results,
                self.updates,
            )
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


async def test_a_failing_bool_check_is_a_section_with_its_fix():
    app = _Host(("armature",), _results(armature=False))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _sections(app) == {
            "armature": [
                "❌ failing",
                "How to fix: Name the armature object in Blender as the spec's "
                "`object_name`.",
            ]
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
    assert sections == {
        "meshes": ["wheel_hub.front.L, wheel_hub.front.R"],
        "count": [
            "❌ failing",
            "- expected: 4",
            "  matched: 2",
            "How to fix: Rename the role's meshes so exactly `count` of them fully "
            "match its `mesh_regex`.",
        ],
        "weight": [
            "❌ failing",
            "- mesh: wheel_hub.front.R",
            "  vertex_group: wheel_hub.front.R",
            "  vertices: 340",
            "  assigned: 328",
            "  at_weight: 300",
            "How to fix: In Weight Paint mode, assign every vertex of each listed "
            "mesh to its group at the role's `weight`.",
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
            "How to fix: Bake each missing map, save it as `<mesh>_<map>.png`, and "
            "load it in an Image Texture node of the mesh's material.",
        ],
    }


async def test_no_default_uv_map_shows_no_warning():
    failure = {"mesh": "body", "missing": ["orm"], "has_default_uv_map": False}
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
