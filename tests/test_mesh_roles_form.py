"""Mesh roles form tests, pushed directly over a dashboard-booted app."""

import json

from textual.widgets import Input, SelectionList, Static

from model_meta.app import ModelMetaApp
from model_meta.config import store as config_store
from model_meta.config.settings import Settings
from model_meta.godot import discovery
from model_meta.specs import store as specs_store
from model_meta.tui.screens.confirm_modal import ConfirmModal
from model_meta.tui.screens.dashboard import DashboardScreen
from model_meta.tui.screens.mesh_role_form import MeshRoleFormScreen
from model_meta.tui.screens.mesh_roles_form import MeshRolesFormScreen
from model_meta.tui.widgets.field_list import FieldList

BONES = ["body", "susarm.front.top.L", "susarm.front.top.R", "arm[L]"]
SUSARM_REGEX = r"(?i)^sus\.?arm\.(?P<pos>front|rear)\.top\.(?P<side>[LR])$"


async def _wait_for(pilot, predicate, tries=100):
    for _ in range(tries):
        if predicate():
            return True
        await pilot.pause()
    return False


def _app(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "find_projects", lambda root, max_depth=4: [])
    cfg = tmp_path / "config.toml"
    (tmp_path / "models").mkdir()
    (tmp_path / "godot").mkdir()
    config_store.save(
        cfg,
        Settings(
            blender_executable="blender",
            blender_version="4.5.0",
            models_directories=(str(tmp_path / "models"),),
            godot_projects_root=str(tmp_path / "godot"),
        ),
    )
    return ModelMetaApp(config_path=cfg)


def _spec(tmp_path, bones=BONES):
    path = specs_store.create(tmp_path / "specs", "vehicle")
    specs_store.update_armature(path, add_bones=bones)
    return path


def _roles(path):
    return json.loads(path.read_text(encoding="utf-8"))["mesh_roles"]


async def _open(pilot, app, path):
    await pilot.pause()
    app.push_screen(MeshRolesFormScreen(path))
    assert await _wait_for(pilot, lambda: isinstance(app.screen, MeshRolesFormScreen))
    await pilot.pause()


async def _start_add(pilot):
    await pilot.press("a")
    await pilot.pause()


async def _type(pilot, text):
    if text:
        await pilot.press(*text)
    await pilot.press("enter")
    await pilot.pause()


def _focused_id(app):
    return app.screen.focused.id if app.screen.focused else None


def _status(app):
    return str(app.screen.query_one("#role-status", Static).render())


def _question_shown(app):
    return app.screen.query_one("#role-bones-question").display


def _bones(app):
    checklist = app.screen.query_one("#role-bones", SelectionList)
    return [
        checklist.get_option_at_index(i).value for i in range(checklist.option_count)
    ]


def _selected(app):
    return app.screen.query_one("#role-bones", SelectionList).selected


def _preview(app):
    return str(app.screen.query_one("#role-preview", Static).render())


async def _check(pilot, app, *bones):
    checklist = app.screen.query_one("#role-bones", SelectionList)
    for bone in bones:
        checklist.select(bone)
    await pilot.pause()


async def _confirm(pilot, app, regex="^m$", count="1"):
    if regex is not None:
        app.screen.query_one("#role-regex", Input).value = regex
    if count is not None:
        app.screen.query_one("#role-count", Input).value = count
    app.screen.query_one("#confirm-role").focus()
    await pilot.pause()
    while app.screen.focused.has_class("-active"):  # Button ignores repeat presses
        await pilot.pause(0.05)
    await pilot.press("enter")
    await pilot.pause()


def _lines(app):
    return [str(row.render()) for row in app.screen.query("#role-list .field-list-row")]


def _marked(app):
    rows = app.screen.query("#role-list .field-list-row")
    return [str(row.render()) for row in rows if row.has_class("field-list-marked")]


async def test_form_opens_read_only_on_the_role_list(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(pilot, app, path)
        assert _focused_id(app) == "role-list"
        assert app.screen.query_one("#role-list .field-list-empty")
        assert not app.screen.query_one("#role-editor").display

        await pilot.press("enter")  # nothing to edit on an empty list, so Enter adds
        await pilot.pause()
        assert app.screen.query_one("#role-editor").display
        assert not _question_shown(app)
        assert _focused_id(app) == "role-name"


async def test_lists_existing_roles_with_their_vtx_grp(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    specs_store.add_mesh_role(path, "body", "body", "^m$", 1)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["mesh_roles"]["glass"] = {}
    path.write_text(json.dumps(document), encoding="utf-8")
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(pilot, app, path)
        assert _lines(app) == [
            "body",
            "mesh_regex: ^m$",
            "vtx_grp: body",
            "count: 1",
            "texture_maps: none",
            "glass",
            "mesh_regex: not set",
            "count: not set",
            "texture_maps: none",
        ]
        children = app.screen.query("#role-list .field-list-child")
        assert [str(row.render()) for row in children] == [
            "mesh_regex: ^m$",
            "vtx_grp: body",
            "count: 1",
            "texture_maps: none",
            "mesh_regex: not set",
            "count: not set",
            "texture_maps: none",
        ]
        assert _marked(app) == ["mesh_regex: not set", "count: not set"]


async def test_lists_each_roles_texture_maps(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    specs_store.add_mesh_role(path, "body", "body", "^m$", 1)
    specs_store.update_mesh_role(
        path, "body", "body", texture_maps=["albedo", "albedo_tex"]
    )
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(pilot, app, path)
        assert _lines(app) == [
            "body",
            "mesh_regex: ^m$",
            "vtx_grp: body",
            "count: 1",
            "texture_maps: albedo, albedo_tex",
        ]
        assert _marked(app) == []


async def test_no_required_bones_opens_nothing(tmp_path, monkeypatch):
    path = _spec(tmp_path, bones=[])
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(pilot, app, path)
        await _start_add(pilot)
        assert not app.screen.query_one("#role-editor").display
        assert _focused_id(app) == "role-list"
        assert _status(app) == "Add required bones first."


async def test_roles_are_added_one_after_another(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _start_add(pilot)

        await _type(pilot, "  susarm_upper  ")
        assert _question_shown(app)
        assert _focused_id(app) == "role-bones"
        label = app.screen.query_one("#role-bones-label", Static)
        assert str(label.render()) == "Bones for 'susarm_upper'"
        assert _bones(app) == BONES
        assert _preview(app) == ""

        await _check(pilot, app, "susarm.front.top.R", "susarm.front.top.L")
        assert _preview(app) == "vtx_grp: susarm.front.top.{1}"
        await _confirm(pilot, app, f"  {SUSARM_REGEX}  ", " 2 ")
        assert _roles(path) == {
            "susarm_upper": {
                "mesh_regex": SUSARM_REGEX,
                "vtx_grp": "susarm.front.top.{1}",
                "count": 2,
            }
        }
        assert _status(app) == "Mesh role 'susarm_upper' added."
        assert not _question_shown(app)
        assert _focused_id(app) == "role-name"
        assert app.screen.query_one("#role-name", Input).value == ""
        assert app.screen.query_one("#role-regex", Input).value == ""
        assert app.screen.query_one("#role-count", Input).value == ""

        await _type(pilot, "body")
        await pilot.press("space")
        await pilot.pause()
        assert _preview(app) == "vtx_grp: body"
        await _confirm(pilot, app, "^body$")
        assert list(_roles(path)) == ["susarm_upper", "body"]
        assert _lines(app) == [
            "susarm_upper",
            f"mesh_regex: {SUSARM_REGEX}",
            "vtx_grp: susarm.front.top.{1}",
            "count: 2",
            "texture_maps: none",
            "body",
            "mesh_regex: ^body$",
            "vtx_grp: body",
            "count: 1",
            "texture_maps: none",
        ]
        assert _marked(app) == []


async def test_bad_role_names_are_rejected(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    specs_store.add_mesh_role(path, "body", "body", "^m$", 1)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(pilot, app, path)
        await _start_add(pilot)

        await _type(pilot, "   ")
        assert _status(app) == "Enter a role name."
        assert not _question_shown(app)

        await pilot.press("ctrl+u")
        await _type(pilot, "body")
        assert _status(app) == "'body' is already a mesh role."
        assert not _question_shown(app)
        assert app.screen.query_one("#role-name", Input).value == "body"


async def test_bad_selections_are_rejected_and_nothing_written(tmp_path, monkeypatch):
    path = _spec(tmp_path, bones=[*BONES, "susarm.rear.top.L"])
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _start_add(pilot)
        await _type(pilot, "wheel")

        cases = [
            ((), "Check at least one bone."),
            (
                ("body", "susarm.front.top.L"),
                "'body' and 'susarm.front.top.L' can't share one pattern.",
            ),
            (
                ("susarm.front.top.R", "susarm.rear.top.L"),
                "'susarm.{1}.top.{2}' would also match susarm.front.top.L.",
            ),
        ]
        for checked, message in cases:
            app.screen.query_one("#role-bones", SelectionList).deselect_all()
            await _check(pilot, app, *checked)
            if checked:
                assert _preview(app) == message
            await _confirm(pilot, app)
            assert _status(app) == message
            assert _selected(app) == list(checked)
            assert _question_shown(app)
        assert _roles(path) == {}


async def test_bad_regexes_are_rejected_and_nothing_written(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _start_add(pilot)
        await _type(pilot, "body")
        await _check(pilot, app, "body")

        cases = [
            ("   ", "Enter a mesh regex."),
            (
                "(?i)^sus(",
                "Not a valid regex: missing ), unterminated subpattern at position 8.",
            ),
        ]
        for regex, message in cases:
            await _confirm(pilot, app, regex)
            assert _status(app) == message
            assert _focused_id(app) == "role-regex"
            assert app.screen.query_one("#role-regex", Input).value == regex
            assert _selected(app) == ["body"]
            assert _question_shown(app)
        assert _roles(path) == {}


async def test_bad_counts_are_rejected_and_nothing_written(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _start_add(pilot)
        await _type(pilot, "body")
        await _check(pilot, app, "body")

        cases = [
            ("  ", "Enter a count."),
            ("0", "The count must be at least 1."),
            ("4.0", "The count must be a whole number."),
        ]
        for count, message in cases:
            await _confirm(pilot, app, "^body$", count)
            assert _status(app) == message
            assert _focused_id(app) == "role-count"
            assert app.screen.query_one("#role-count", Input).value == count
            assert app.screen.query_one("#role-regex", Input).value == "^body$"
            assert _selected(app) == ["body"]
            assert _question_shown(app)
        assert _roles(path) == {}


async def test_enter_in_the_regex_with_no_count_asks_for_one(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _start_add(pilot)
        await _type(pilot, "body")
        await _check(pilot, app, "body")
        app.screen.query_one("#role-regex", Input).focus()
        await _type(pilot, "^body$")
        assert _status(app) == "Enter a count."
        assert _focused_id(app) == "role-count"
        assert _roles(path) == {}


async def test_enter_in_the_count_adds(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _start_add(pilot)
        await _type(pilot, "body")
        await _check(pilot, app, "body")
        app.screen.query_one("#role-regex", Input).value = "^body$"
        app.screen.query_one("#role-count", Input).focus()
        await _type(pilot, "1")
        assert _roles(path) == {
            "body": {"mesh_regex": "^body$", "vtx_grp": "body", "count": 1}
        }
        assert _status(app) == "Mesh role 'body' added."
        assert _focused_id(app) == "role-name"


async def test_role_taken_in_between_is_reported(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _start_add(pilot)
        await _type(pilot, "body")
        specs_store.add_mesh_role(path, "body", "body", "^m$", 1)

        await _check(pilot, app, "body")
        await _confirm(pilot, app)
        assert (
            _status(app) == "Could not write the spec: 'body' is already a mesh role."
        )
        assert _roles(path) == {
            "body": {"mesh_regex": "^m$", "vtx_grp": "body", "count": 1}
        }
        assert _selected(app) == ["body"]


async def test_escape_semantics(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(pilot, app, path)
        await _start_add(pilot)
        await _type(pilot, "body")
        await _check(pilot, app, "body")

        await pilot.press("escape")
        assert not _question_shown(app)
        assert _focused_id(app) == "role-name"
        assert app.screen.query_one("#role-name", Input).value == "body"

        await _type(pilot, "")
        assert _selected(app) == []
        assert _preview(app) == ""
        await pilot.press("escape")
        assert _focused_id(app) == "role-name"

        await pilot.press("escape")
        assert app.screen.query_one("#role-name", Input).value == ""
        assert app.screen.query_one("#role-editor").display

        await pilot.press("escape")
        assert not app.screen.query_one("#role-editor").display
        assert _focused_id(app) == "role-list"

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))
        assert _roles(path) == {}


async def test_q_does_not_quit(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(pilot, app, path)
        await pilot.press("q")
        await pilot.pause()
        assert app.is_running
        assert isinstance(app.screen, MeshRolesFormScreen)


async def test_markup_looking_text_renders_literally(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _start_add(pilot)
        await _type(pilot, "[b]arm")
        label = app.screen.query_one("#role-bones-label", Static)
        assert str(label.render()) == "Bones for '[b]arm'"

        await _check(pilot, app, "arm[L]")
        assert _preview(app) == "vtx_grp: arm[L]"
        await _confirm(pilot, app)
        assert _lines(app) == [
            "[b]arm",
            "mesh_regex: ^m$",
            "vtx_grp: arm[L]",
            "count: 1",
            "texture_maps: none",
        ]
        assert _status(app) == "Mesh role '[b]arm' added."


async def test_clicking_the_list_opens_or_refocuses_the_editor(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await pilot.click("#role-list")
        await pilot.pause()
        assert app.screen.query_one("#role-editor").display
        assert _focused_id(app) == "role-name"

        await _type(pilot, "body")
        await pilot.click("#role-list")
        await pilot.pause()
        assert _focused_id(app) == "role-bones"


# --- opening a role --------------------------------------------------------


def _with_roles(tmp_path, bones=BONES):
    path = _spec(tmp_path, bones)
    specs_store.add_mesh_role(path, "body", "body", "^m$", 1)
    specs_store.add_mesh_role(path, "susarm", "susarm.front.top.{1}", "^m$", 1)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["mesh_roles"]["glass"] = {"weight": 1.0}
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


async def _open_role(pilot, app, index):
    role_list = app.screen.query_one("#role-list", FieldList)
    role_list.focus()
    role_list.highlighted = index
    await pilot.press("enter")
    await pilot.pause()


def _cursor(app):
    return app.screen.query_one("#role-list", FieldList).highlighted


async def _back_to_list(pilot, app):
    await pilot.press("escape")
    assert await _wait_for(pilot, lambda: isinstance(app.screen, MeshRolesFormScreen))
    await pilot.pause()


async def test_enter_on_a_role_pushes_its_own_view(tmp_path, monkeypatch):
    path = _with_roles(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _open_role(pilot, app, 1)
        assert await _wait_for(
            pilot, lambda: isinstance(app.screen, MeshRoleFormScreen)
        )
        assert app.screen.role == "susarm"

        await _back_to_list(pilot, app)
        assert _cursor(app) == 1
        assert _focused_id(app) == "role-list"


async def test_return_after_a_rename_follows_the_role(tmp_path, monkeypatch):
    path = _with_roles(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _open_role(pilot, app, 0)
        assert await _wait_for(
            pilot, lambda: isinstance(app.screen, MeshRoleFormScreen)
        )
        app.screen.query_one("#role-name-view").focus()
        await pilot.press("enter")
        app.screen.query_one("#role-name", Input).value = "zbody"
        await pilot.press("enter")
        await pilot.pause()
        assert list(_roles(path)) == ["zbody", "susarm", "glass"]

        await pilot.press("escape")  # leaves: the name editor already closed
        assert await _wait_for(
            pilot, lambda: isinstance(app.screen, MeshRolesFormScreen)
        )
        assert await _wait_for(pilot, lambda: _lines(app)[0] == "zbody")
        assert _cursor(app) == 0


async def test_clicking_a_role_opens_it(tmp_path, monkeypatch):
    path = _with_roles(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        child = app.screen.query("#role-list .field-list-child")[4]
        await pilot.click(child)
        assert await _wait_for(
            pilot, lambda: isinstance(app.screen, MeshRoleFormScreen)
        )
        assert app.screen.role == "susarm"


async def test_opening_a_role_discards_an_add(tmp_path, monkeypatch):
    path = _with_roles(tmp_path)
    before = path.read_bytes()
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _start_add(pilot)
        await _type(pilot, "wheel")
        assert _question_shown(app)

        await _open_role(pilot, app, 0)
        assert await _wait_for(
            pilot, lambda: isinstance(app.screen, MeshRoleFormScreen)
        )
        await _back_to_list(pilot, app)
        assert not app.screen.query_one("#role-editor").display
        assert app.screen.query_one("#role-name", Input).value == ""
        assert path.read_bytes() == before


async def test_a_role_opens_without_required_bones(tmp_path, monkeypatch):
    path = _spec(tmp_path, bones=[])
    document = json.loads(path.read_text(encoding="utf-8"))
    document["mesh_roles"]["glass"] = {}
    path.write_text(json.dumps(document), encoding="utf-8")
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _open_role(pilot, app, 0)
        assert await _wait_for(
            pilot, lambda: isinstance(app.screen, MeshRoleFormScreen)
        )


async def test_a_role_removed_by_hand_is_reported(tmp_path, monkeypatch):
    path = _with_roles(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        document = json.loads(path.read_text(encoding="utf-8"))
        del document["mesh_roles"]["body"]
        path.write_text(json.dumps(document), encoding="utf-8")

        await _open_role(pilot, app, 0)  # the list is stale until it refreshes
        assert isinstance(app.screen, MeshRolesFormScreen)
        assert _status(app) == "'body' is no longer a mesh role."
        assert _lines(app)[0] == "susarm"


# --- deleting a role ---------------------------------------------------------


async def _delete(pilot, app, index, *keys):
    """Highlight role `index`, press `x`, then `keys` in the dialog."""
    role_list = app.screen.query_one("#role-list", FieldList)
    role_list.focus()
    role_list.highlighted = index
    await pilot.press("x")
    assert await _wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
    await pilot.pause()
    if keys:
        await pilot.press(*keys)
    assert await _wait_for(pilot, lambda: isinstance(app.screen, MeshRolesFormScreen))
    await pilot.pause()


def _listed(app):
    rows = app.screen.query("#role-list .field-list-row")
    return [str(row.render()) for row in rows if not row.has_class("field-list-child")]


def _bindings(app):
    return {b.binding.key for b in app.screen.active_bindings.values()}


async def test_x_deletes_from_a_non_empty_role_list_only(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    specs_store.add_mesh_role(path, "body", "body", "^m$", 1)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        assert "x" in _bindings(app)

        await _start_add(pilot)
        assert _focused_id(app) == "role-name"
        assert "x" not in _bindings(app)
        await pilot.press("escape")
        await pilot.pause()

        await _delete(pilot, app, 0, "right", "enter")
        assert _roles(path) == {}
        assert _cursor(app) is None
        assert "x" not in _bindings(app)
        await pilot.press("x")
        await pilot.pause()
        assert isinstance(app.screen, MeshRolesFormScreen)

        await pilot.press("enter")  # an empty list still opens Add
        await pilot.pause()
        assert _focused_id(app) == "role-name"


async def test_dialog_asks_about_the_highlighted_role(tmp_path, monkeypatch):
    path = _with_roles(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        app.screen.query_one("#role-list", FieldList).highlighted = 1
        await pilot.press("x")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        await pilot.pause()
        question = app.screen.query_one("#confirm-question", Static)
        assert str(question.render()) == "Delete mesh role 'susarm'?"
        assert _focused_id(app) == "confirm-no"


async def test_no_and_escape_cancel_and_write_nothing(tmp_path, monkeypatch):
    path = _with_roles(tmp_path)
    before = path.read_bytes()
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        for keys in (("enter",), ("escape",)):
            await _delete(pilot, app, 1, *keys)
            assert path.read_bytes() == before
            assert _focused_id(app) == "role-list"
            assert _cursor(app) == 1
            assert _status(app) == ""


async def test_yes_deletes_only_that_role(tmp_path, monkeypatch):
    path = _with_roles(tmp_path)
    specs_store.update_armature(path, add_parenting={"body": ["arm[L]"]})
    before = json.loads(path.read_text(encoding="utf-8"))
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _delete(pilot, app, 1, "right", "enter")

        after = json.loads(path.read_text(encoding="utf-8"))
        del before["mesh_roles"]["susarm"]
        assert after == before  # armature and the other roles untouched
        assert _listed(app) == ["body", "glass"]
        assert _marked(app) == ["mesh_regex: not set", "count: not set"]  # glass
        assert _focused_id(app) == "role-list"
        assert _cursor(app) == 1  # the role that moved up
        assert _status(app) == "Mesh role 'susarm' deleted."

        await _delete(pilot, app, 1, "right", "enter")
        assert _listed(app) == ["body"]
        assert _cursor(app) == 0  # clamped to the new last role
        assert _status(app) == "Mesh role 'glass' deleted."


async def test_yes_discards_an_open_add_and_no_keeps_it(tmp_path, monkeypatch):
    path = _with_roles(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _start_add(pilot)
        await _type(pilot, "wheel")
        assert _question_shown(app)

        await _delete(pilot, app, 0, "enter")
        assert app.screen.query_one("#role-editor").display
        assert _question_shown(app)
        assert app.screen.query_one("#role-name", Input).value == "wheel"

        await _delete(pilot, app, 0, "right", "enter")
        assert not app.screen.query_one("#role-editor").display
        assert app.screen.query_one("#role-name", Input).value == ""
        assert list(_roles(path)) == ["susarm", "glass"]
        assert _focused_id(app) == "role-list"


async def test_a_role_gone_by_hand_reports_and_refreshes(tmp_path, monkeypatch):
    path = _with_roles(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        app.screen.query_one("#role-list", FieldList).highlighted = 1
        await pilot.press("x")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        await pilot.pause()
        specs_store.delete_mesh_role(path, "susarm")
        await pilot.press("right", "enter")
        assert await _wait_for(
            pilot, lambda: isinstance(app.screen, MeshRolesFormScreen)
        )
        await pilot.pause()

        assert _status(app) == (
            "Could not write the spec: 'susarm' is no longer a mesh role."
        )
        assert _listed(app) == ["body", "glass"]
        assert _focused_id(app) == "role-list"


async def test_q_does_not_quit_from_the_dialog(tmp_path, monkeypatch):
    path = _with_roles(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _delete(pilot, app, 0, "q", "escape")
        assert app.is_running
        assert len(_roles(path)) == 3
