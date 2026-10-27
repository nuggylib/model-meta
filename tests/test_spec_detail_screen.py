"""Spec detail screen tests.

Driven through the pilot from the Specs page, because `enter` on a row is the
only way in — the screen is pushed as an instance and is not in `SCREENS`.

It reads the spec to summarize the armature (name and bone count) and the mesh
roles (a count); a malformed spec shows an unreadable line in place of the
summaries, with `e` disabled.
"""

import json

from textual.widgets import Static

from model_meta.app import ModelMetaApp
from model_meta.config import store as config_store
from model_meta.config.settings import Settings
from model_meta.core.godot_connection import GodotConnection
from model_meta.core.spec import MeshRole
from model_meta.specs import schema
from model_meta.specs import store as specs_store
from model_meta.specs.store import ArmaturePatch
from model_meta.tui.screens.armature_form import ArmatureFormScreen
from model_meta.tui.screens.edit_data_modal import EditDataModal
from model_meta.tui.screens.mesh_roles_form import MeshRolesFormScreen
from model_meta.tui.screens.modifiers_form import ModifiersFormScreen
from model_meta.tui.screens.spec_detail import SpecDetailScreen
from model_meta.tui.screens.specs import SpecsScreen
from model_meta.tui.widgets.spec_row import SpecRow

_BODY_ROLE = MeshRole(vtx_grp="body", mesh_regex="^m$", count=1, weight=1.0)


def _text(widget):
    """The plain rendered text of a Static, markup applied/stripped."""
    return str(widget.render())


async def _wait_for(pilot, predicate, tries=100):
    for _ in range(tries):
        if predicate():
            return True
        await pilot.pause()
    return False


def _app(tmp_path, monkeypatch, specs=(), raw=()):
    """A dashboard-booting app over a valid config, with `specs` on disk.

    `raw` names spec files hand-written as text — the malformed and mismatched
    cases the screen must be indifferent to.
    """
    monkeypatch.setattr(GodotConnection, "find_projects", lambda self, max_depth=4: [])
    cfg = tmp_path / "config.toml"
    models = tmp_path / "models"
    models.mkdir()
    godot = tmp_path / "godot"
    godot.mkdir()
    config_store.save(
        cfg,
        Settings(
            blender_executable="blender",
            blender_version="4.5.0",
            models_directories=(str(models),),
            godot_projects_root=str(godot),
        ),
    )
    for name in specs:
        specs_store.create(tmp_path / "specs", name)
    for name, payload in raw:
        directory = tmp_path / "specs"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.json").write_text(payload, encoding="utf-8")
    return ModelMetaApp(config_path=cfg)


async def _open_specs(pilot, app):
    """Navigate the dashboard to the Specs screen."""
    await pilot.pause()
    await pilot.press("down")  # Blender → Specs
    await pilot.press("enter")
    assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))


async def _open_spec(pilot, app):
    """Navigate to the Specs screen and `enter` on its first row."""
    await _open_specs(pilot, app)
    assert await _wait_for(pilot, lambda: isinstance(app.screen.focused, SpecRow))
    await pilot.press("enter")
    assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecDetailScreen))


def _title(app):
    return _text(app.screen.query_one("#spec-title", Static))


async def test_spec_detail_opens_for_the_selected_row(tmp_path, monkeypatch):
    """The screen is named for the row that opened it, not for row one."""
    app = _app(tmp_path, monkeypatch, specs=("vehicle", "character"))
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        screen = app.screen
        assert await _wait_for(pilot, lambda: len(screen.query(SpecRow)) == 2)
        assert await _wait_for(pilot, lambda: isinstance(screen.focused, SpecRow))

        await pilot.press("down")  # character → vehicle
        assert screen.focused.model_type == "vehicle"
        await pilot.press("enter")

        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecDetailScreen))
        assert app.screen.model_type == "vehicle"
        assert "vehicle" in _title(app)


async def test_spec_detail_escapes_markup_in_a_spec_name(tmp_path, monkeypatch):
    """A name is user-supplied text rendered through Rich markup — `mech[v2]`
    would otherwise render with a chunk missing."""
    app = _app(
        tmp_path,
        monkeypatch,
        raw=(("mech[v2]", json.dumps(schema.skeleton("mech[v2]"))),),
    )
    async with app.run_test() as pilot:
        await _open_spec(pilot, app)
        assert app.screen.model_type == "mech[v2]"
        assert "mech[v2]" in _title(app)


async def test_spec_detail_is_headed_with_the_stem_not_the_files_model_type(
    tmp_path, monkeypatch
):
    """The filename stem is the identity and wins over a disagreeing file."""
    app = _app(
        tmp_path,
        monkeypatch,
        raw=(("vehicle", json.dumps(schema.skeleton("spaceship"))),),
    )
    async with app.run_test() as pilot:
        await _open_spec(pilot, app)

        assert app.screen.model_type == "vehicle"
        assert "vehicle" in _title(app)
        assert "spaceship" not in _title(app)


async def test_spec_detail_has_no_focusable_widgets(tmp_path, monkeypatch):
    """Nothing to arrow through on a page with nothing to interact with."""
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    async with app.run_test() as pilot:
        await _open_spec(pilot, app)
        assert app.screen.focus_chain == []


async def test_spec_detail_escape_returns_to_the_specs_screen(tmp_path, monkeypatch):
    """`escape` pops back to a Specs page with its rows still listed."""
    app = _app(tmp_path, monkeypatch, specs=("vehicle", "character"))
    async with app.run_test() as pilot:
        await _open_spec(pilot, app)

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))
        screen = app.screen
        assert await _wait_for(pilot, lambda: len(screen.query(SpecRow)) == 2)
        assert [row.model_type for row in screen.query(SpecRow)] == [
            "character",
            "vehicle",
        ]


async def test_spec_detail_quit_still_works(tmp_path, monkeypatch):
    """`q` must reach the app's global quit from the screen."""
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    async with app.run_test() as pilot:
        await _open_spec(pilot, app)

        await pilot.press("q")
        assert await _wait_for(pilot, lambda: not app.is_running)


async def test_spec_detail_opens_without_a_valid_config(tmp_path):
    """It reads no settings at all, so it opens with `settings is None`."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is not valid toml {{{")
    specs_store.create(tmp_path / "specs", "vehicle")

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.settings is None

        await pilot.press("enter")  # Specs is the only card there is
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))
        assert await _wait_for(pilot, lambda: isinstance(app.screen.focused, SpecRow))
        await pilot.press("enter")

        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecDetailScreen))
        assert "vehicle" in _title(app)


def _rows(app, summary="armature-summary"):
    return [
        _text(row) for row in app.screen.query_one(f"#{summary}").query(".field-row")
    ]


def _role_columns(app):
    summary = app.screen.query_one("#mesh-roles-summary")
    return [
        [_text(item) for item in column.query(".field-item")]
        for column in summary.query(".field-column")
    ]


def _enabled(app, action):
    return any(
        binding.action == action and enabled
        for (_, binding, enabled, _) in app.screen.active_bindings.values()
    )


async def test_spec_detail_summarizes_the_armature(tmp_path, monkeypatch):
    """A name and a count, never the bones themselves — those live on the form."""
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    specs_store.update_armature(
        tmp_path / "specs" / "vehicle.json", ArmaturePatch(add_bones=["body", "arm[L]"])
    )
    async with app.run_test() as pilot:
        await _open_spec(pilot, app)
        expected = ["Name: not set", "Bones: 2"]
        assert await _wait_for(pilot, lambda: _rows(app) == expected)
        assert app.screen.query_one("#armature-summary").border_title == "Armature"
        assert not app.screen.query(".bone-row")
        assert _enabled(app, "edit_data")


async def test_spec_detail_shows_zero_bones(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    async with app.run_test() as pilot:
        await _open_spec(pilot, app)
        expected = ["Name: not set", "Bones: 0"]
        assert await _wait_for(pilot, lambda: _rows(app) == expected)
        assert "Edit data" in [
            binding.description
            for (_, binding, _, _) in app.screen.active_bindings.values()
        ]


async def test_spec_detail_renders_the_armature_name_verbatim(tmp_path, monkeypatch):
    """The name is read from the file, so it renders without markup."""
    document = schema.skeleton("vehicle")
    document["armature"]["object_name"] = "rig[L]"
    app = _app(tmp_path, monkeypatch, raw=(("vehicle", json.dumps(document)),))
    async with app.run_test() as pilot:
        await _open_spec(pilot, app)
        expected = ["Name: rig[L]", "Bones: 0"]
        assert await _wait_for(pilot, lambda: _rows(app) == expected)


async def test_spec_detail_reports_an_unreadable_spec_and_disables_edit(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch, raw=(("broken", "{not json"),))
    async with app.run_test() as pilot:
        await _open_spec(pilot, app)
        assert "broken" in _title(app)
        unreadable = app.screen.query_one("#spec-unreadable", Static)
        assert await _wait_for(pilot, lambda: unreadable.display)
        assert not app.screen.query_one("#armature-summary").display
        assert not app.screen.query_one("#mesh-roles-summary").display
        assert not app.screen.query_one("#modifiers-summary").display
        assert not _enabled(app, "edit_data")

        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, SpecDetailScreen)


async def test_edit_data_opens_the_armature_form_and_refreshes_on_return(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    async with app.run_test(size=(80, 40)) as pilot:
        await _open_spec(pilot, app)
        assert await _wait_for(pilot, lambda: "Bones: 0" in _rows(app))

        await pilot.press("e")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, EditDataModal))
        await pilot.press("enter")
        assert await _wait_for(
            pilot, lambda: isinstance(app.screen, ArmatureFormScreen)
        )
        assert app.screen.path == tmp_path / "specs" / "vehicle.json"

        await pilot.press("enter", *"body", "enter")
        await pilot.pause()
        await pilot.press("escape", "escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecDetailScreen))
        assert await _wait_for(pilot, lambda: "Bones: 1" in _rows(app))


async def test_edit_data_escape_writes_nothing(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    spec = tmp_path / "specs" / "vehicle.json"
    before = spec.read_bytes()
    async with app.run_test() as pilot:
        await _open_spec(pilot, app)
        await pilot.press("e")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, EditDataModal))
        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecDetailScreen))

        assert spec.read_bytes() == before


async def test_armature_name_set_on_the_form_shows_on_return(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    async with app.run_test(size=(80, 40)) as pilot:
        await _open_spec(pilot, app)
        assert await _wait_for(pilot, lambda: "Name: not set" in _rows(app))

        await pilot.press("e")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, EditDataModal))
        await pilot.press("enter")
        assert await _wait_for(
            pilot, lambda: isinstance(app.screen, ArmatureFormScreen)
        )
        await pilot.press("shift+tab", "enter", *"Rig", "enter")
        await pilot.pause()
        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecDetailScreen))
        assert await _wait_for(pilot, lambda: "Name: Rig" in _rows(app))


async def test_spec_detail_lists_the_mesh_role_names(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    spec = tmp_path / "specs" / "vehicle.json"
    specs_store.add_mesh_role(spec, "body", _BODY_ROLE)
    specs_store.add_mesh_role(spec, "arm[L]", _BODY_ROLE)
    async with app.run_test() as pilot:
        await _open_spec(pilot, app)
        assert await _wait_for(
            pilot, lambda: _role_columns(app) == [["1). body", "2). arm[L]"]]
        )
        summary = app.screen.query_one("#mesh-roles-summary")
        assert summary.border_title == "Mesh roles"
        assert not summary.query(".field-row")


async def test_spec_detail_wraps_mesh_roles_into_columns_of_ten(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    spec = tmp_path / "specs" / "vehicle.json"
    names = [f"role{i:02}" for i in range(23)]
    for name in names:
        specs_store.add_mesh_role(spec, name, _BODY_ROLE)
    numbered = [f"{n:>2}). {name}" for n, name in enumerate(names, start=1)]
    async with app.run_test() as pilot:
        await _open_spec(pilot, app)
        assert await _wait_for(
            pilot,
            lambda: (
                _role_columns(app) == [numbered[:10], numbered[10:20], numbered[20:]]
            ),
        )


async def test_spec_detail_says_when_there_are_no_mesh_roles(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    async with app.run_test() as pilot:
        await _open_spec(pilot, app)
        summary = app.screen.query_one("#mesh-roles-summary")
        assert await _wait_for(pilot, lambda: bool(summary.query(".field-empty")))
        assert _text(summary.query_one(".field-empty")) == "No mesh roles yet."
        assert _role_columns(app) == []


async def test_edit_data_opens_the_mesh_roles_form_and_refreshes_on_return(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    spec = tmp_path / "specs" / "vehicle.json"
    specs_store.update_armature(spec, ArmaturePatch(add_bones=["body"]))
    async with app.run_test(size=(80, 40)) as pilot:
        await _open_spec(pilot, app)
        assert await _wait_for(pilot, lambda: _role_columns(app) == [])

        await pilot.press("e")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, EditDataModal))
        await pilot.press("down", "enter")
        assert await _wait_for(
            pilot, lambda: isinstance(app.screen, MeshRolesFormScreen)
        )
        assert app.screen.path == spec

        await pilot.press("enter", *"body", "enter")
        await pilot.pause()
        await pilot.press(
            "space", "tab", *"^body$", "enter", "1", "enter", "1", "enter"
        )
        await pilot.pause()
        await pilot.press("escape", "escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecDetailScreen))
        assert await _wait_for(pilot, lambda: _role_columns(app) == [["1). body"]])


async def test_spec_detail_lists_each_modifier_list(tmp_path, monkeypatch):
    document = schema.skeleton("vehicle")
    document["modifiers"]["allowed"] = ["TRIANGULATE", "WEIGHTED_NORMAL"]
    document["modifiers"]["fail"] = ["BOOLEAN"]
    app = _app(tmp_path, monkeypatch, raw=(("vehicle", json.dumps(document)),))
    async with app.run_test(size=(80, 40)) as pilot:
        await _open_spec(pilot, app)
        expected = [
            "Required on skinned meshes: ARMATURE",
            "Allowed: TRIANGULATE, WEIGHTED_NORMAL",
            "Warn: []",
            "Fail: BOOLEAN",
        ]
        assert await _wait_for(
            pilot, lambda: _rows(app, "modifiers-summary") == expected
        )
        assert app.screen.query_one("#modifiers-summary").border_title == "Modifiers"


async def test_edit_data_opens_the_modifiers_form_and_refreshes_on_return(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    spec = tmp_path / "specs" / "vehicle.json"
    async with app.run_test(size=(80, 40)) as pilot:
        await _open_spec(pilot, app)
        first = "Required on skinned meshes: ARMATURE"
        assert await _wait_for(pilot, lambda: first in _rows(app, "modifiers-summary"))

        await pilot.press("e")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, EditDataModal))
        await pilot.press("down", "down", "enter")
        assert await _wait_for(
            pilot, lambda: isinstance(app.screen, ModifiersFormScreen)
        )
        assert app.screen.path == spec

        await pilot.press("enter", "space", "tab", "enter")
        await pilot.pause()
        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecDetailScreen))
        emptied = "Required on skinned meshes: []"
        assert await _wait_for(
            pilot, lambda: emptied in _rows(app, "modifiers-summary")
        )
