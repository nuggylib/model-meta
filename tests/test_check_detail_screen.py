from pathlib import Path

from textual.app import App
from textual.signal import Signal

from model_meta.core.results import FieldCheck, MeshRoleResult, Results
from model_meta.tui.screens.check_detail import CheckDetailScreen
from model_meta.tui.widgets.fix_panel import FixPanel

_WEIGHT_FAILURE = {
    "mesh": "wheel_hub.front.R",
    "vertex_group": "wheel_hub.front.R",
    "vertices": 340,
    "assigned": 328,
    "at_weight": 300,
}


def _results(**checks):
    return Results(model_file="/m/sedan.blend", spec="vehicle", **checks, path=None)


class _Host(App):
    def __init__(self, field, results):
        super().__init__()
        self.field = field
        self.results = results

    def on_mount(self):
        self.updates = Signal(self, "updates")
        self.push_screen(
            CheckDetailScreen(
                Path("/m/sedan.blend"), self.field, "Title", self.results, self.updates
            )
        )


def _lines(app):
    return [
        (_depth(line), str(line.render()))
        for line in app.screen.query("#check-lines Static")
    ]


def _depth(line):
    depths = [name for name in line.classes if name.startswith("check-depth-")]
    return int(depths[0].removeprefix("check-depth-")) if depths else None


def _steps(app):
    return app.screen.query_one(FixPanel).steps


async def _open(field, results):
    app = _Host(field, results)
    async with app.run_test() as pilot:
        await pilot.pause()
        return _lines(app), _steps(app)


async def test_never_checked_field_says_so():
    lines, steps = await _open("mesh_roles", _results())
    assert lines == [(None, "No results yet.")]
    assert steps == ()


async def test_unreadable_results_say_no_results():
    lines, _ = await _open("armature", None)
    assert lines == [(None, "No results yet.")]


async def test_a_bool_check_is_one_line_with_its_fix():
    lines, steps = await _open("armature", _results(armature=False))
    assert lines == [(0, "❌ armature")]
    assert len(steps) == 1
    assert "object_name" in steps[0]


async def test_mesh_roles_mirror_the_results_file_and_list_every_failure():
    roles = {
        "wheels": MeshRoleResult(
            ["wheel_hub.front.L", "wheel_hub.front.R"],
            {
                "count": FieldCheck([{"expected": 4, "matched": 2}]),
                "weight": FieldCheck([_WEIGHT_FAILURE]),
                "texture_maps": FieldCheck(
                    [
                        {"mesh": "wheel_hub.front.L", "missing": ["orm"]},
                        {"mesh": "wheel_hub.front.R", "missing": ["albedo", "orm"]},
                    ]
                ),
            },
        ),
        "body": MeshRoleResult(["body"], {"material_slots": FieldCheck([])}),
    }
    lines, steps = await _open("mesh_roles", _results(mesh_roles=roles))
    assert lines == [
        (0, "❌ wheels"),
        (1, "meshes: wheel_hub.front.L, wheel_hub.front.R"),
        (1, "❌ count"),
        (2, "- expected: 4"),
        (2, "  matched: 2"),
        (1, "❌ weight"),
        (2, "- mesh: wheel_hub.front.R"),
        (2, "  vertex_group: wheel_hub.front.R"),
        (2, "  vertices: 340"),
        (2, "  assigned: 328"),
        (2, "  at_weight: 300"),
        (1, "❌ texture_maps"),
        (2, "- mesh: wheel_hub.front.L"),
        (2, "  missing: orm"),
        (2, "- mesh: wheel_hub.front.R"),
        (2, "  missing: albedo, orm"),
        (0, "✅ body"),
        (1, "meshes: body"),
        (1, "✅ material_slots"),
    ]
    assert [step.split(" ")[0] for step in steps] == ["Rename", "In", "Bake"]


async def test_an_error_failure_is_listed_as_a_fact():
    roles = {"body": MeshRoleResult([], {"count": FieldCheck([{"error": "x"}])})}
    lines, _ = await _open("mesh_roles", _results(mesh_roles=roles))
    assert lines[-2:] == [(1, "❌ count"), (2, "- error: x")]


async def test_published_results_replace_the_page():
    app = _Host("armature", _results(armature=False))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.updates.publish(_results(armature=True))
        for _ in range(20):
            await pilot.pause()
            if _lines(app) == [(0, "✅ armature")]:
                break
        assert _lines(app) == [(0, "✅ armature")]
        assert _steps(app) == ()
