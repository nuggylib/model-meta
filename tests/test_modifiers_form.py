"""Modifiers form tests: the spec's modifier lists, pushed over a dashboard-booted app."""

import json

from textual.widgets import SelectionList, Static

from model_meta.app import ModelMetaApp
from model_meta.config import store as config_store
from model_meta.config.settings import Settings
from model_meta.core.godot_connection import GodotConnection
from model_meta.specs import schema
from model_meta.specs import store as specs_store
from model_meta.tui.screens.dashboard import DashboardScreen
from model_meta.tui.screens.modifiers_form import ModifiersFormScreen


async def _wait_for(pilot, predicate, tries=100):
    for _ in range(tries):
        if predicate():
            return True
        await pilot.pause()
    return False


def _app(tmp_path, monkeypatch):
    monkeypatch.setattr(GodotConnection, "find_projects", lambda self, max_depth=4: [])
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


def _spec(tmp_path, **lists):
    path = specs_store.create(tmp_path / "specs", "vehicle")
    document = json.loads(path.read_text(encoding="utf-8"))
    document["mesh_roles"] = {"body": {"vtx_grp": "body"}}
    for key, value in lists.items():
        if key == "skinned_meshes":
            document["modifiers"]["required"]["skinned_meshes"] = value
        else:
            document["modifiers"][key] = value
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _document(path):
    return json.loads(path.read_text(encoding="utf-8"))


async def _open(pilot, app, path):
    await pilot.pause()
    app.push_screen(ModifiersFormScreen(path))
    assert await _wait_for(pilot, lambda: isinstance(app.screen, ModifiersFormScreen))
    await pilot.pause()


def _focused_id(app):
    return app.screen.focused.id if app.screen.focused else None


def _status(app):
    return str(app.screen.query_one("#modifiers-status", Static).render())


def _lines(app):
    return [
        str(row.render())
        for row in app.screen.query("#modifier-fields .field-list-row")
    ]


def _checklist(app):
    return app.screen.query_one("#modifier-choices", SelectionList)


def _prompts(app):
    checklist = _checklist(app)
    return {
        checklist.get_option_at_index(i).value: str(
            checklist.get_option_at_index(i).prompt
        )
        for i in range(checklist.option_count)
    }


async def _select(pilot, app, index):
    fields = app.screen.query_one("#modifier-fields")
    fields.focus()
    fields.highlighted = index
    await pilot.press("enter")
    await pilot.pause()


async def _save(pilot, app):
    if _focused_id(app) == "modifier-choices":
        await pilot.press("tab")
    assert _focused_id(app) == "save-modifiers"
    while app.screen.focused.has_class("-active"):  # Button ignores repeat presses
        await pilot.pause(0.05)
    await pilot.press("enter")
    await pilot.pause()


async def test_lists_each_key_with_its_description(tmp_path, monkeypatch):
    path = _spec(tmp_path, allowed=["TRIANGULATE", "WEIGHTED_NORMAL"], fail=["BOOLEAN"])
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        assert _lines(app) == [
            "required.skinned_meshes: ARMATURE",
            "must be on every skinned mesh",
            "allowed: TRIANGULATE, WEIGHTED_NORMAL",
            "allowed anywhere: safe in Godot or harmless",
            "warn: []",
            "warns on export: apply it to reach Godot",
            "fail: BOOLEAN",
            "fails validation: breaks geometry when applied",
        ]
        assert _focused_id(app) == "modifier-fields"
        assert str(app.screen.query_one("#modifiers-title", Static).render()) == (
            "Modifiers"
        )


async def test_enter_opens_a_prechecked_tagged_checklist(tmp_path, monkeypatch):
    path = _spec(tmp_path, allowed=["NODES"], warn=["MIRROR"], fail=["BOOLEAN"])
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _select(pilot, app, 3)

        assert app.screen.query_one("#modifiers-editor").display
        assert _focused_id(app) == "modifier-choices"
        label = app.screen.query_one("#modifiers-label", Static)
        assert str(label.render()) == "fail modifiers"
        prompts = _prompts(app)
        assert list(prompts) == [*schema.MODIFIERS, "NODES"]
        assert prompts["ARMATURE"] == "ARMATURE (required)"
        assert prompts["MIRROR"] == "MIRROR (in warn)"
        assert prompts["BOOLEAN"] == "BOOLEAN"
        assert prompts["NODES"] == "NODES (not a listed modifier) (in allowed)"
        assert prompts["WELD"] == "WELD"
        assert _checklist(app).selected == ["BOOLEAN"]


async def test_a_hand_written_overlap_is_tagged_with_both_lists(tmp_path, monkeypatch):
    path = _spec(tmp_path, warn=["MIRROR"], fail=["MIRROR"])
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _select(pilot, app, 1)
        assert _prompts(app)["MIRROR"] == "MIRROR (in warn, fail)"


async def test_save_writes_in_choices_order_and_keeps_the_cursor(tmp_path, monkeypatch):
    path = _spec(tmp_path, allowed=["WELD", "WELD"])
    before = _document(path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _select(pilot, app, 1)
        _checklist(app).select("BEVEL")
        await pilot.pause()
        await _save(pilot, app)

        after = _document(path)
        assert after["modifiers"]["allowed"] == ["BEVEL", "WELD"]
        assert {**after, "modifiers": None} == {**before, "modifiers": None}
        assert _status(app) == "Modifiers saved."
        assert not app.screen.query_one("#modifiers-editor").display
        assert "allowed: BEVEL, WELD" in _lines(app)
        assert _focused_id(app) == "modifier-fields"
        assert app.screen.query_one("#modifier-fields").highlighted == 1


async def test_save_moves_names_out_of_conflicting_lists(tmp_path, monkeypatch):
    path = _spec(tmp_path, warn=["MIRROR", "SUBSURF"], fail=["BOOLEAN"])
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _select(pilot, app, 1)
        for name in ("BOOLEAN", "MIRROR", "SUBSURF"):
            _checklist(app).select(name)
        await pilot.pause()
        await _save(pilot, app)

        modifiers = _document(path)["modifiers"]
        assert modifiers["allowed"] == ["BOOLEAN", "MIRROR", "SUBSURF"]
        assert modifiers["warn"] == []
        assert modifiers["fail"] == []
        assert _status(app) == (
            "Modifiers saved. Moved MIRROR, SUBSURF out of warn; BOOLEAN out of fail."
        )

        await _select(pilot, app, 3)
        _checklist(app).select("BOOLEAN")
        await pilot.pause()
        await _save(pilot, app)
        modifiers = _document(path)["modifiers"]
        assert modifiers["allowed"] == ["MIRROR", "SUBSURF"]
        assert modifiers["fail"] == ["BOOLEAN"]
        assert _status(app) == "Modifiers saved. Moved BOOLEAN out of allowed."


async def test_save_moves_between_fail_and_skinned_meshes(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _select(pilot, app, 3)
        _checklist(app).select("ARMATURE")
        await pilot.pause()
        await _save(pilot, app)
        modifiers = _document(path)["modifiers"]
        assert modifiers["required"]["skinned_meshes"] == []
        assert modifiers["fail"] == ["ARMATURE"]
        assert _status(app) == (
            "Modifiers saved. Moved ARMATURE out of required.skinned_meshes."
        )

        await _select(pilot, app, 0)
        _checklist(app).select("ARMATURE")
        await pilot.pause()
        await _save(pilot, app)
        modifiers = _document(path)["modifiers"]
        assert modifiers["required"]["skinned_meshes"] == ["ARMATURE"]
        assert modifiers["fail"] == []
        assert _status(app) == "Modifiers saved. Moved ARMATURE out of fail."


async def test_unchecking_everything_writes_empty(tmp_path, monkeypatch):
    path = _spec(tmp_path, warn=["MIRROR"])
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _select(pilot, app, 0)
        _checklist(app).deselect_all()
        await pilot.pause()
        await _save(pilot, app)

        modifiers = _document(path)["modifiers"]
        assert modifiers["required"]["skinned_meshes"] == []
        assert modifiers["warn"] == ["MIRROR"]
        assert "required.skinned_meshes: []" in _lines(app)
        assert _status(app) == "Modifiers saved."


async def test_escape_closes_the_checklist_then_leaves_and_q_does_nothing(
    tmp_path, monkeypatch
):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        before = path.read_bytes()
        await pilot.press("q")
        await pilot.pause()
        assert app.is_running
        assert isinstance(app.screen, ModifiersFormScreen)

        await _select(pilot, app, 2)
        _checklist(app).select("MIRROR")
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ModifiersFormScreen)
        assert not app.screen.query_one("#modifiers-editor").display
        assert _focused_id(app) == "modifier-fields"

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))
        assert path.read_bytes() == before


async def test_opening_another_list_discards_the_first(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        before = path.read_bytes()
        await _select(pilot, app, 2)
        _checklist(app).select("MIRROR")
        await pilot.pause()

        await _select(pilot, app, 1)
        label = app.screen.query_one("#modifiers-label", Static)
        assert str(label.render()) == "allowed modifiers"
        assert _checklist(app).selected == []
        assert path.read_bytes() == before

        await _select(pilot, app, 2)
        assert _checklist(app).selected == []


async def test_extras_are_listed_but_not_editable(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    document = _document(path)
    document["modifiers"]["required"]["static_meshes"] = ["WELD"]
    document["modifiers"]["notes"] = "apply MIRROR first"
    path.write_text(json.dumps(document), encoding="utf-8")
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        assert _lines(app)[-2:] == [
            "required.static_meshes: WELD",
            "notes: apply MIRROR first",
        ]

        await _select(pilot, app, 4)
        assert _status(app) == "'required.static_meshes' can't be edited here yet."
        assert not app.screen.query_one("#modifiers-editor").display

        await _select(pilot, app, 2)
        _checklist(app).select("MIRROR")
        await pilot.pause()
        await _save(pilot, app)
        after = _document(path)["modifiers"]
        assert after["required"]["static_meshes"] == ["WELD"]
        assert after["notes"] == "apply MIRROR first"


async def test_a_read_error_is_reported(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    path.write_text('{"modifiers": {"warn": "MIRROR"}}', encoding="utf-8")
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        assert _status(app) == (
            "Could not read the spec: `modifiers.warn` is not a list of strings."
        )


async def test_a_spec_broken_while_open_writes_nothing(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _select(pilot, app, 2)
        _checklist(app).select("MIRROR")
        await pilot.pause()
        path.write_text("{not json", encoding="utf-8")

        await _save(pilot, app)
        assert _status(app).startswith("Could not write the spec: ")
        assert app.screen.query_one("#modifiers-editor").display
        assert _checklist(app).selected == ["MIRROR"]
        assert path.read_text(encoding="utf-8") == "{not json"
