"""Mesh role form tests: one role, pushed directly over a dashboard-booted app."""

import json

from textual.widgets import Input, SelectionList, Static

from model_meta.app import ModelMetaApp
from model_meta.config import store as config_store
from model_meta.config.settings import Settings
from model_meta.core.spec import MeshRole
from model_meta.godot import discovery
from model_meta.specs import schema
from model_meta.specs import store as specs_store
from model_meta.specs.store import ArmaturePatch
from model_meta.tui.screens.dashboard import DashboardScreen
from model_meta.tui.screens.mesh_role_form import MeshRoleFormScreen

BONES = ["body", "wheel.L", "wheel.R", "arm[L]"]


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
    if bones:
        specs_store.update_armature(path, ArmaturePatch(add_bones=bones))
    specs_store.add_mesh_role(path, "body", _role("body"))
    specs_store.add_mesh_role(path, "wheel", _role("wheel.{1}"))
    return path


def _role(vtx_grp):
    return MeshRole(vtx_grp=vtx_grp, mesh_regex="^m$", count=1, weight=1.0)


def _set_role(path, name, role):
    document = json.loads(path.read_text(encoding="utf-8"))
    document["mesh_roles"][name] = role
    path.write_text(json.dumps(document), encoding="utf-8")


def _roles(path):
    return json.loads(path.read_text(encoding="utf-8"))["mesh_roles"]


async def _open(pilot, app, path, name, results=None):
    await pilot.pause()
    app.push_screen(
        MeshRoleFormScreen(path, name),
        None if results is None else results.append,
    )
    assert await _wait_for(pilot, lambda: isinstance(app.screen, MeshRoleFormScreen))
    await pilot.pause()


def _focused_id(app):
    return app.screen.focused.id if app.screen.focused else None


def _text(app, selector):
    return str(app.screen.query_one(selector, Static).render())


def _status(app):
    return _text(app, "#role-status")


def _lines(app, list_id):
    return [
        str(row.render()) for row in app.screen.query(f"#{list_id} .field-list-row")
    ]


async def _select(pilot, app, list_id, index=None):
    field_list = app.screen.query_one(f"#{list_id}")
    field_list.focus()
    if index is not None:
        field_list.highlighted = index
    await pilot.press("enter")
    await pilot.pause()


async def _rename(pilot, app, text):
    await _select(pilot, app, "role-name-view")
    app.screen.query_one("#role-name", Input).value = text
    await pilot.press("enter")
    await pilot.pause()


def _selected(app):
    return app.screen.query_one("#role-bones", SelectionList).selected


async def _save(pilot, app):
    if _focused_id(app) == "role-bones":
        await pilot.press("tab")
    assert _focused_id(app) == "save-vtx-grp"
    while app.screen.focused.has_class("-active"):  # Button ignores repeat presses
        await pilot.pause(0.05)
    await pilot.press("enter")
    await pilot.pause()


def _textures(app):
    return app.screen.query_one("#role-textures", SelectionList)


async def _save_textures(pilot, app):
    if _focused_id(app) == "role-textures":
        await pilot.press("tab")
    assert _focused_id(app) == "save-texture-maps"
    while app.screen.focused.has_class("-active"):
        await pilot.pause(0.05)
    await pilot.press("enter")
    await pilot.pause()


async def test_shows_only_the_role_with_focus_on_its_fields(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")

        assert _text(app, "#role-title") == "Mesh role — wheel"
        assert _lines(app, "role-name-view") == ["wheel"]
        assert _lines(app, "role-fields") == [
            "mesh_regex: ^m$",
            "vtx_grp: wheel.{1}",
            "matches wheel.L, wheel.R",
            "count: 1",
            "weight: 1.0",
            "texture_maps: none",
        ]
        description = app.screen.query("#role-fields .field-list-row")[2]
        assert description.has_class("field-list-child")
        assert _focused_id(app) == "role-fields"
        assert not app.screen.query_one("#role-name").display
        assert not app.screen.query_one("#vtx-grp-editor").display


async def test_hand_written_fields_are_listed_but_not_editable(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    role = {
        "mesh_regex": "^w",
        "count": 2,
        "texture_maps": ["albedo", "normal"],
        "x": [],
    }
    _set_role(path, "wheel", role)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        assert _lines(app, "role-fields") == [
            "mesh_regex: ^w",
            "vtx_grp: not set",
            "count: 2",
            "weight: not set",
            "required: the weight its meshes carry on vtx_grp",
            "texture_maps: albedo, normal",
            "x: (empty)",
        ]

        before = path.read_bytes()
        await _select(pilot, app, "role-fields", 5)
        assert _status(app) == "'x' can't be edited here yet."
        assert not app.screen.query_one("#texture-maps-editor").display
        assert not app.screen.query_one("#vtx-grp-editor").display
        assert path.read_bytes() == before


async def test_rename_writes_the_name_alone(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    _set_role(path, "wheel", {"vtx_grp": "wheel.{1}", "weight": 1.0})
    results = []
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel", results)
        await _select(pilot, app, "role-name-view")
        role_name = app.screen.query_one("#role-name", Input)
        assert role_name.display
        assert not app.screen.query_one("#role-name-view").display
        assert role_name.value == "wheel"
        assert _focused_id(app) == "role-name"

        role_name.value = "  tire "
        await pilot.press("enter")
        await pilot.pause()

        assert _roles(path) == {
            "body": {
                "mesh_regex": "^m$",
                "vtx_grp": "body",
                "count": 1,
                "weight": 1.0,
            },
            "tire": {"vtx_grp": "wheel.{1}", "weight": 1.0},
        }
        assert _status(app) == "Mesh role 'tire' saved."
        assert _text(app, "#role-title") == "Mesh role — tire"
        assert _lines(app, "role-name-view") == ["tire"]
        assert not role_name.display
        assert _focused_id(app) == "role-name-view"

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))
        assert results == ["tire"]


async def test_rename_follows_the_name_rules(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        before = path.read_bytes()

        await _rename(pilot, app, "body")
        assert _status(app) == "'body' is already a mesh role."
        await _rename(pilot, app, "   ")
        assert _status(app) == "Enter a role name."
        assert app.screen.query_one("#role-name", Input).display
        assert path.read_bytes() == before

        await _rename(pilot, app, "wheel")
        assert _status(app) == "Mesh role 'wheel' saved."
        assert list(_roles(path)) == ["body", "wheel"]


async def test_escape_closes_the_name_editor_unsaved(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        before = path.read_bytes()
        await _select(pilot, app, "role-name-view")
        app.screen.query_one("#role-name", Input).value = "tire"
        await pilot.press("escape")
        await pilot.pause()

        assert isinstance(app.screen, MeshRoleFormScreen)
        assert not app.screen.query_one("#role-name").display
        assert _lines(app, "role-name-view") == ["wheel"]
        assert _focused_id(app) == "role-name-view"
        assert path.read_bytes() == before


async def test_vtx_grp_editor_prefills_and_saves_the_pattern_alone(
    tmp_path, monkeypatch
):
    path = _spec(tmp_path)
    _set_role(path, "wheel", {"vtx_grp": "wheel.{1}", "weight": 1.0})
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        await _select(pilot, app, "role-fields", 1)

        assert app.screen.query_one("#vtx-grp-editor").display
        assert _text(app, "#role-bones-label") == "Bones for 'wheel'"
        assert _selected(app) == ["wheel.L", "wheel.R"]
        assert _text(app, "#role-preview") == "vtx_grp: wheel.{1}"
        assert _focused_id(app) == "role-bones"

        app.screen.query_one("#role-bones", SelectionList).deselect("wheel.R")
        await pilot.pause()
        assert _text(app, "#role-preview") == "vtx_grp: wheel.L"
        await _save(pilot, app)

        assert _roles(path)["wheel"] == {"vtx_grp": "wheel.L", "weight": 1.0}
        assert _status(app) == "Mesh role 'wheel' saved."
        assert not app.screen.query_one("#vtx-grp-editor").display
        assert _lines(app, "role-fields") == [
            "mesh_regex: not set",
            "required: the meshes in this role",
            "vtx_grp: wheel.L",
            "matches wheel.L",
            "count: not set",
            "required: how many meshes mesh_regex matches",
            "weight: 1.0",
            "texture_maps: none",
        ]
        assert _focused_id(app) == "role-fields"
        assert app.screen.query_one("#role-fields").highlighted == 1


async def test_a_rejected_selection_keeps_the_editor_open(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        before = path.read_bytes()
        await _select(pilot, app, "role-fields", 1)
        app.screen.query_one("#role-bones", SelectionList).deselect_all()
        await pilot.pause()
        await _save(pilot, app)

        assert _status(app) == "Check at least one bone."
        assert app.screen.query_one("#vtx-grp-editor").display
        assert path.read_bytes() == before

        await pilot.press("escape")
        await pilot.pause()
        assert not app.screen.query_one("#vtx-grp-editor").display
        assert _focused_id(app) == "role-fields"
        assert path.read_bytes() == before


async def test_vtx_grp_needs_required_bones(tmp_path, monkeypatch):
    path = _spec(tmp_path, bones=[])
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        assert _lines(app, "role-fields") == [
            "mesh_regex: ^m$",
            "vtx_grp: wheel.{1}",
            "matches no required bone",
            "count: 1",
            "weight: 1.0",
            "texture_maps: none",
        ]
        await _select(pilot, app, "role-fields", 1)
        assert _status(app) == "Add required bones first."
        assert not app.screen.query_one("#vtx-grp-editor").display


async def test_a_pattern_matching_no_bone_says_so(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    _set_role(path, "wheel", {"vtx_grp": "tire.{1}"})
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        await _select(pilot, app, "role-fields", 1)
        assert _selected(app) == []
        assert _status(app) == "Its vtx_grp 'tire.{1}' matches no required bone."


async def test_a_role_without_vtx_grp_gets_one_on_save(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    _set_role(path, "wheel", {"weight": 1.0})
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        await _select(pilot, app, "role-fields", 1)
        app.screen.query_one("#role-bones", SelectionList).select("body")
        await pilot.pause()
        await _save(pilot, app)
        assert _roles(path)["wheel"] == {"weight": 1.0, "vtx_grp": "body"}


# --- mesh_regex ------------------------------------------------------------


SUSARM_REGEX = r"(?i)^sus\.?arm\.(?P<pos>front|rear)\.top\.(?P<side>[LR])$"


def _marked(app):
    rows = app.screen.query("#role-fields .field-list-row")
    return [str(row.render()) for row in rows if row.has_class("field-list-marked")]


async def test_a_role_without_a_mesh_regex_is_marked(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    _set_role(path, "wheel", {"vtx_grp": "wheel.{1}", "count": 4, "weight": 1.0})
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        assert _marked(app) == [
            "mesh_regex: not set",
            "required: the meshes in this role",
        ]

        await _select(pilot, app, "role-fields", 0)
        mesh_regex = app.screen.query_one("#mesh-regex", Input)
        assert mesh_regex.display
        assert mesh_regex.value == ""
        mesh_regex.value = "^wheel"
        await pilot.press("enter")
        await pilot.pause()
        assert _marked(app) == []
        assert _roles(path)["wheel"] == {
            "vtx_grp": "wheel.{1}",
            "count": 4,
            "weight": 1.0,
            "mesh_regex": "^wheel",
        }


async def test_mesh_regex_editor_prefills_and_saves_it_alone(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    _set_role(
        path, "wheel", {"mesh_regex": "^w", "vtx_grp": "wheel.{1}", "weight": 1.0}
    )
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        await _select(pilot, app, "role-fields", 0)
        mesh_regex = app.screen.query_one("#mesh-regex", Input)
        assert mesh_regex.display
        assert mesh_regex.value == "^w"
        assert _focused_id(app) == "mesh-regex"

        mesh_regex.value = f"  {SUSARM_REGEX} "
        await pilot.press("enter")
        await pilot.pause()

        assert list(_roles(path)) == ["body", "wheel"]
        assert _roles(path)["wheel"] == {
            "mesh_regex": SUSARM_REGEX,
            "vtx_grp": "wheel.{1}",
            "weight": 1.0,
        }
        assert _status(app) == "Mesh role 'wheel' saved."
        assert not mesh_regex.display
        assert _lines(app, "role-fields")[0] == f"mesh_regex: {SUSARM_REGEX}"
        assert _focused_id(app) == "role-fields"
        assert app.screen.query_one("#role-fields").highlighted == 0


async def test_a_bad_mesh_regex_is_rejected(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        before = path.read_bytes()
        await _select(pilot, app, "role-fields", 0)
        mesh_regex = app.screen.query_one("#mesh-regex", Input)

        cases = [
            ("  ", "Enter a mesh regex."),
            (
                "^a(?i)b",
                "Not a valid regex: global flags not at the start of the expression"
                " at position 2.",
            ),
        ]
        for regex, message in cases:
            mesh_regex.value = regex
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert _status(app) == message
            assert mesh_regex.display
            assert mesh_regex.value == regex
        assert path.read_bytes() == before

        await pilot.press("x")
        await pilot.pause()
        assert _status(app) == ""

        await pilot.press("escape")
        await pilot.pause()
        assert not mesh_regex.display
        assert _focused_id(app) == "role-fields"
        assert isinstance(app.screen, MeshRoleFormScreen)
        assert path.read_bytes() == before


async def test_opening_another_editor_discards_the_mesh_regex(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        before = path.read_bytes()
        await _select(pilot, app, "role-fields", 0)
        app.screen.query_one("#mesh-regex", Input).value = "^tire"

        await _select(pilot, app, "role-fields", 1)
        assert not app.screen.query_one("#mesh-regex").display
        assert app.screen.query_one("#vtx-grp-editor").display

        await _select(pilot, app, "role-fields", 0)
        await _select(pilot, app, "role-name-view")
        assert not app.screen.query_one("#mesh-regex").display
        assert app.screen.query_one("#role-name").display
        assert path.read_bytes() == before


# --- count -----------------------------------------------------------------


async def test_a_role_without_a_count_is_marked(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    role = {"mesh_regex": "^w", "vtx_grp": "wheel.{1}", "weight": 1.0}
    _set_role(path, "wheel", role)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        assert _marked(app) == [
            "count: not set",
            "required: how many meshes mesh_regex matches",
        ]

        await _select(pilot, app, "role-fields", 2)
        count = app.screen.query_one("#count", Input)
        assert count.display
        assert count.value == ""
        assert _focused_id(app) == "count"
        count.value = " 004 "
        await pilot.press("enter")
        await pilot.pause()
        assert _marked(app) == []
        assert _roles(path)["wheel"] == {
            "mesh_regex": "^w",
            "vtx_grp": "wheel.{1}",
            "weight": 1.0,
            "count": 4,
        }


async def test_a_role_missing_every_input_field_marks_each(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    _set_role(path, "wheel", {"vtx_grp": "wheel.{1}"})
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        assert _marked(app) == [
            "mesh_regex: not set",
            "required: the meshes in this role",
            "count: not set",
            "required: how many meshes mesh_regex matches",
            "weight: not set",
            "required: the weight its meshes carry on vtx_grp",
        ]


async def test_count_editor_prefills_and_saves_it_alone(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    _set_role(
        path,
        "wheel",
        {"mesh_regex": "^w", "vtx_grp": "wheel.{1}", "weight": 1.0, "count": 2},
    )
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        await _select(pilot, app, "role-fields", 2)
        count = app.screen.query_one("#count", Input)
        assert count.value == "2"

        count.value = "4"
        await pilot.press("enter")
        await pilot.pause()

        assert list(_roles(path)) == ["body", "wheel"]
        assert _roles(path)["wheel"] == {
            "mesh_regex": "^w",
            "vtx_grp": "wheel.{1}",
            "weight": 1.0,
            "count": 4,
        }
        assert _status(app) == "Mesh role 'wheel' saved."
        assert not count.display
        assert "count: 4" in _lines(app, "role-fields")
        assert _focused_id(app) == "role-fields"
        assert app.screen.query_one("#role-fields").highlighted == 2


async def test_a_bad_count_is_rejected(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    role = {"mesh_regex": "^w", "vtx_grp": "wheel.{1}", "count": 0, "weight": 1.0}
    _set_role(path, "wheel", role)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        assert "count: 0" in _lines(app, "role-fields")
        assert _marked(app) == []
        before = path.read_bytes()
        await _select(pilot, app, "role-fields", 2)
        count = app.screen.query_one("#count", Input)
        assert count.value == "0"

        cases = [
            ("0", "The count must be at least 1."),
            ("  ", "Enter a count."),
            ("-1", "The count must be a whole number."),
            ("4.0", "The count must be a whole number."),
        ]
        for text, message in cases:
            count.value = text
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert _status(app) == message
            assert count.display
            assert count.value == text
        assert path.read_bytes() == before

        await pilot.press("1")
        await pilot.pause()
        assert _status(app) == ""

        await pilot.press("escape")
        await pilot.pause()
        assert not count.display
        assert _focused_id(app) == "role-fields"
        assert isinstance(app.screen, MeshRoleFormScreen)
        assert path.read_bytes() == before


async def test_opening_another_editor_discards_the_count(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        before = path.read_bytes()
        await _select(pilot, app, "role-fields", 2)
        app.screen.query_one("#count", Input).value = "9"

        await _select(pilot, app, "role-fields", 0)
        assert not app.screen.query_one("#count").display
        assert app.screen.query_one("#mesh-regex").display

        await _select(pilot, app, "role-fields", 2)
        assert app.screen.query_one("#count", Input).value == "1"
        assert not app.screen.query_one("#mesh-regex").display
        assert path.read_bytes() == before


# --- weight ----------------------------------------------------------------


async def test_a_role_without_a_weight_is_marked(tmp_path, monkeypatch):
    role = {"mesh_regex": "^w", "vtx_grp": "wheel.{1}", "count": 2}
    path = _spec(tmp_path)
    _set_role(path, "wheel", role)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        assert _marked(app) == [
            "weight: not set",
            "required: the weight its meshes carry on vtx_grp",
        ]

        await _select(pilot, app, "role-fields", 3)
        weight = app.screen.query_one("#weight", Input)
        assert weight.display
        assert weight.value == ""
        assert _focused_id(app) == "weight"
        weight.value = " 0 "
        await pilot.press("enter")
        await pilot.pause()
        assert _marked(app) == []
        assert _roles(path)["wheel"] == {**role, "weight": 0.0}
        assert "weight: 0.0" in _lines(app, "role-fields")


async def test_a_zero_weight_is_set_not_missing(tmp_path, monkeypatch):
    role = {"mesh_regex": "^w", "vtx_grp": "wheel.{1}", "count": 2, "weight": 0.0}
    path = _spec(tmp_path)
    _set_role(path, "wheel", role)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        assert "weight: 0.0" in _lines(app, "role-fields")
        assert _marked(app) == []
        await _select(pilot, app, "role-fields", 3)
        assert app.screen.query_one("#weight", Input).value == "0.0"


async def test_weight_editor_prefills_and_saves_it_alone(tmp_path, monkeypatch):
    role = {"mesh_regex": "^w", "vtx_grp": "wheel.{1}", "count": 2, "weight": 1e-07}
    path = _spec(tmp_path)
    _set_role(path, "wheel", role)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        assert "weight: 0.0000001" in _lines(app, "role-fields")
        await _select(pilot, app, "role-fields", 3)
        weight = app.screen.query_one("#weight", Input)
        assert weight.value == "0.0000001"

        await pilot.press("enter")  # an unchanged re-save round-trips
        await pilot.pause()
        assert _roles(path)["wheel"] == role

        await _select(pilot, app, "role-fields", 3)
        weight.value = ".25"
        await pilot.press("enter")
        await pilot.pause()

        assert list(_roles(path)) == ["body", "wheel"]
        assert _roles(path)["wheel"] == {**role, "weight": 0.25}
        assert list(_roles(path)["wheel"]) == list(role)
        assert _status(app) == "Mesh role 'wheel' saved."
        assert not weight.display
        assert "weight: 0.25" in _lines(app, "role-fields")
        assert _focused_id(app) == "role-fields"
        assert app.screen.query_one("#role-fields").highlighted == 3


async def test_a_bad_weight_is_rejected(tmp_path, monkeypatch):
    role = {"mesh_regex": "^w", "vtx_grp": "wheel.{1}", "count": 2, "weight": 1.5}
    path = _spec(tmp_path)
    _set_role(path, "wheel", role)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        assert "weight: 1.5" in _lines(app, "role-fields")
        assert _marked(app) == []
        before = path.read_bytes()
        await _select(pilot, app, "role-fields", 3)
        weight = app.screen.query_one("#weight", Input)
        assert weight.value == "1.5"

        cases = [
            ("1.5", "The weight must be between 0 and 1."),
            ("  ", "Enter a weight."),
            ("-0.1", "The weight must be a decimal number."),
            ("1e-1", "The weight must be a decimal number."),
        ]
        for text, message in cases:
            weight.value = text
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert _status(app) == message
            assert weight.display
            assert weight.value == text
        assert path.read_bytes() == before

        await pilot.press("1")
        await pilot.pause()
        assert _status(app) == ""

        await pilot.press("escape")
        await pilot.pause()
        assert not weight.display
        assert _focused_id(app) == "role-fields"
        assert isinstance(app.screen, MeshRoleFormScreen)
        assert path.read_bytes() == before


async def test_opening_another_editor_discards_the_weight(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        before = path.read_bytes()
        await _select(pilot, app, "role-fields", 3)
        app.screen.query_one("#weight", Input).value = "0.5"

        await _select(pilot, app, "role-fields", 2)
        assert not app.screen.query_one("#weight").display
        assert app.screen.query_one("#count").display

        await _select(pilot, app, "role-fields", 3)
        assert app.screen.query_one("#weight", Input).value == "1.0"
        assert not app.screen.query_one("#count").display
        assert path.read_bytes() == before


async def test_one_editor_at_a_time_and_escape_steps_out(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    results = []
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel", results)
        before = path.read_bytes()
        await _select(pilot, app, "role-fields", 1)
        await _select(pilot, app, "role-name-view")
        assert not app.screen.query_one("#vtx-grp-editor").display
        assert app.screen.query_one("#role-name").display

        await _select(pilot, app, "role-fields", 1)
        assert not app.screen.query_one("#role-name").display
        assert app.screen.query_one("#role-name-view").display
        assert app.screen.query_one("#vtx-grp-editor").display

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, MeshRoleFormScreen)
        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))
        assert results == ["wheel"]
        assert path.read_bytes() == before


async def test_a_role_removed_by_hand_is_reported(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        document = json.loads(path.read_text(encoding="utf-8"))
        del document["mesh_roles"]["wheel"]
        path.write_text(json.dumps(document), encoding="utf-8")

        await _rename(pilot, app, "tire")
        assert _status(app) == (
            "Could not write the spec: 'wheel' is no longer a mesh role."
        )
        assert list(_roles(path)) == ["body"]

        await pilot.press("escape")
        await pilot.pause()
        await _select(pilot, app, "role-fields", 1)
        assert _status(app) == "'wheel' is no longer a mesh role."
        assert not app.screen.query_one("#vtx-grp-editor").display


async def test_texture_maps_editor_prefills_with_extras_after_the_schema(
    tmp_path, monkeypatch
):
    path = _spec(tmp_path)
    _set_role(path, "wheel", {"vtx_grp": "wheel.{1}", "texture_maps": ["zzz", "orm"]})
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        assert "texture_maps: zzz, orm" in _lines(app, "role-fields")
        await _select(pilot, app, "role-fields", 4)

        checklist = _textures(app)
        assert app.screen.query_one("#texture-maps-editor").display
        assert _focused_id(app) == "role-textures"
        assert _text(app, "#role-textures-label") == "Texture maps for 'wheel'"
        values = [
            checklist.get_option_at_index(i).value
            for i in range(checklist.option_count)
        ]
        assert values == [*schema.TEXTURE_MAPS, "zzz"]
        assert str(checklist.get_option_at_index(19).prompt) == "zzz (not a Godot map)"
        assert sorted(checklist.selected) == ["orm", "zzz"]


async def test_texture_maps_save_writes_schema_order_alone(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    _set_role(path, "wheel", {"vtx_grp": "wheel.{1}", "weight": 1.0})
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        await _select(pilot, app, "role-fields", 4)
        _textures(app).select("orm")
        _textures(app).select("albedo")
        await pilot.pause()
        await _save_textures(pilot, app)

        assert _roles(path)["wheel"] == {
            "vtx_grp": "wheel.{1}",
            "weight": 1.0,
            "texture_maps": ["albedo", "orm"],
        }
        assert list(_roles(path)) == ["body", "wheel"]
        assert _status(app) == "Mesh role 'wheel' saved."
        assert not app.screen.query_one("#texture-maps-editor").display
        assert "texture_maps: albedo, orm" in _lines(app, "role-fields")
        assert _focused_id(app) == "role-fields"
        assert app.screen.query_one("#role-fields").highlighted == 4


async def test_texture_maps_unchecking_everything_writes_empty(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    _set_role(path, "wheel", {"vtx_grp": "wheel.{1}", "texture_maps": ["albedo"]})
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        await _select(pilot, app, "role-fields", 4)
        _textures(app).deselect_all()
        await pilot.pause()
        await _save_textures(pilot, app)

        assert _roles(path)["wheel"]["texture_maps"] == []
        assert "texture_maps: none" in _lines(app, "role-fields")


async def test_texture_maps_escape_and_other_editors_discard(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        before = path.read_bytes()
        await _select(pilot, app, "role-fields", 4)
        _textures(app).select("albedo")
        await pilot.press("escape")
        await pilot.pause()
        assert not app.screen.query_one("#texture-maps-editor").display
        assert _focused_id(app) == "role-fields"
        assert isinstance(app.screen, MeshRoleFormScreen)

        await _select(pilot, app, "role-fields", 4)
        assert _textures(app).selected == []
        _textures(app).select("albedo")
        await _select(pilot, app, "role-fields", 1)
        assert not app.screen.query_one("#texture-maps-editor").display
        assert app.screen.query_one("#vtx-grp-editor").display
        assert path.read_bytes() == before


async def test_texture_maps_on_a_role_removed_by_hand(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        await _select(pilot, app, "role-fields", 4)
        document = json.loads(path.read_text(encoding="utf-8"))
        del document["mesh_roles"]["wheel"]
        path.write_text(json.dumps(document), encoding="utf-8")

        await _save_textures(pilot, app)
        assert _status(app) == (
            "Could not write the spec: 'wheel' is no longer a mesh role."
        )
        assert app.screen.query_one("#texture-maps-editor").display
        assert list(_roles(path)) == ["body"]


# --- material_slots --------------------------------------------------------

ROLE = {"mesh_regex": "^w", "vtx_grp": "wheel.{1}", "count": 2, "weight": 1.0}


async def test_unset_material_slots_are_hidden(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    _set_role(path, "wheel", {**ROLE, "material_slots": []})
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        assert not any("material_slots" in line for line in _lines(app, "role-fields"))
        assert _marked(app) == []


async def test_set_material_slots_follow_texture_maps(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    _set_role(path, "wheel", {"x": 1, **ROLE, "material_slots": ["paint", "trim"]})
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        assert _lines(app, "role-fields")[-3:] == [
            "texture_maps: none",
            "material_slots: paint, trim",
            "x: 1",
        ]
        assert _marked(app) == []

        await _select(pilot, app, "role-fields", 5)
        editor = app.screen.query_one("#material-slots", Input)
        assert editor.display
        assert editor.value == "paint, trim"


async def test_m_adds_material_slots_to_an_unset_role(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    _set_role(path, "wheel", ROLE)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        await pilot.press("m")
        await pilot.pause()
        editor = app.screen.query_one("#material-slots", Input)
        assert editor.display
        assert editor.value == ""
        assert _focused_id(app) == "material-slots"

        await pilot.press("m")  # typed, not the binding
        await pilot.pause()
        assert editor.value == "m"

        editor.value = " paint ,trim, Paint "
        await pilot.press("enter")
        await pilot.pause()

        assert _roles(path)["wheel"] == {
            **ROLE,
            "material_slots": ["paint", "trim", "Paint"],
        }
        assert not editor.display
        assert _status(app) == "Mesh role 'wheel' saved."
        assert "material_slots: paint, trim, Paint" in _lines(app, "role-fields")
        assert _focused_id(app) == "role-fields"
        assert app.screen.query_one("#role-fields").highlighted == 5


async def test_saving_blank_material_slots_removes_them(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    _set_role(path, "wheel", {**ROLE, "material_slots": ["paint"], "x": 1})
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        await pilot.press("m")
        await pilot.pause()
        editor = app.screen.query_one("#material-slots", Input)
        assert editor.value == "paint"
        editor.value = "  "
        await pilot.press("enter")
        await pilot.pause()

        assert _roles(path)["wheel"] == {**ROLE, "x": 1}
        assert not any("material_slots" in line for line in _lines(app, "role-fields"))
        assert app.screen.query_one("#role-fields").highlighted == 4


async def test_bad_material_slots_are_rejected(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    _set_role(path, "wheel", {**ROLE, "material_slots": ["a", "a"]})
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        before = path.read_bytes()
        await pilot.press("m")
        await pilot.pause()
        editor = app.screen.query_one("#material-slots", Input)
        assert editor.value == "a, a"

        cases = [
            ("a, a", "'a' is listed twice."),
            ("a,,b", "A material slot name is blank."),
            ("a,", "A material slot name is blank."),
        ]
        for text, message in cases:
            editor.value = text
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert _status(app) == message
            assert editor.display
            assert editor.value == text
        assert path.read_bytes() == before

        await pilot.press("escape")
        await pilot.pause()
        assert not editor.display
        assert _focused_id(app) == "role-fields"
        assert path.read_bytes() == before


async def test_m_closes_another_editor(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        await _select(pilot, app, "role-fields", 4)
        assert app.screen.query_one("#texture-maps-editor").display
        await pilot.press("m")
        await pilot.pause()
        assert not app.screen.query_one("#texture-maps-editor").display
        assert app.screen.query_one("#material-slots").display


async def test_material_slots_on_a_role_removed_by_hand(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        await pilot.press("m")
        await pilot.pause()
        document = json.loads(path.read_text(encoding="utf-8"))
        del document["mesh_roles"]["wheel"]
        path.write_text(json.dumps(document), encoding="utf-8")

        app.screen.query_one("#material-slots", Input).value = "paint"
        await pilot.press("enter")
        await pilot.pause()
        assert _status(app) == (
            "Could not write the spec: 'wheel' is no longer a mesh role."
        )
        assert list(_roles(path)) == ["body"]


async def test_q_does_not_quit(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "wheel")
        await pilot.press("q")
        await pilot.pause()
        assert isinstance(app.screen, MeshRoleFormScreen)


async def test_markup_looking_text_renders_literally(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    specs_store.add_mesh_role(path, "arm[L]", _role("arm[L]"))
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path, "arm[L]")
        assert _text(app, "#role-title") == "Mesh role — arm[L]"
        assert _lines(app, "role-name-view") == ["arm[L]"]
        assert _lines(app, "role-fields") == [
            "mesh_regex: ^m$",
            "vtx_grp: arm[L]",
            "matches arm[L]",
            "count: 1",
            "weight: 1.0",
            "texture_maps: none",
        ]
        await _select(pilot, app, "role-fields", 1)
        assert _text(app, "#role-bones-label") == "Bones for 'arm[L]'"
