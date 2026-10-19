"""Armature form tests, pushed directly over a dashboard-booted app."""

import json

from textual.widgets import Input, SelectionList, Static

from model_meta.app import ModelMetaApp
from model_meta.config import store as config_store
from model_meta.config.settings import Settings
from model_meta.godot import discovery
from model_meta.specs import store as specs_store
from model_meta.tui.screens.armature_form import ArmatureFormScreen
from model_meta.tui.screens.confirm_modal import ConfirmModal
from model_meta.tui.screens.dashboard import DashboardScreen

FRONT_REAR = {".front": ".rear", ".rear": ".front"}


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


def _spec(tmp_path):
    return specs_store.create(tmp_path / "specs", "vehicle")


def _armature(path):
    return json.loads(path.read_text(encoding="utf-8"))["armature"]


async def _open(pilot, app, path):
    await pilot.pause()
    app.push_screen(ArmatureFormScreen(path))
    assert await _wait_for(pilot, lambda: isinstance(app.screen, ArmatureFormScreen))
    await pilot.pause()


async def _type(pilot, text):
    if text:
        await pilot.press(*text)
    await pilot.press("enter")
    await pilot.pause()


async def _edit(pilot, app, view_id):
    app.screen.query_one(f"#{view_id}").focus()
    await pilot.press("enter")
    await pilot.pause()


async def _add_mode(pilot, app):
    app.screen.query_one("#bone-list").focus()
    await pilot.press("a")
    await pilot.pause()


def _focused_id(app):
    return app.screen.focused.id if app.screen.focused else None


def _status(app):
    return str(app.screen.query_one("#bone-status", Static).render())


def _rows(app, list_id):
    return app.screen.query(f"#{list_id} .field-list-row")


def _listed(app):
    return [str(row.render()) for row in _rows(app, "bone-list")]


def _variants(app):
    (checklist,) = app.screen.query("#bone-variants")
    return [
        checklist.get_option_at_index(i).value for i in range(checklist.option_count)
    ]


def _inverse_label(app):
    return str(app.screen.query_one("#bone-inverse-label", Static).render())


async def test_form_opens_read_only_on_the_bone_list(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(pilot, app, path)
        assert _focused_id(app) == "bone-list"
        assert app.screen.query_one("#bone-list .field-list-empty")
        assert not app.screen.query_one("#bone-editor").display
        assert not app.screen.query_one("#parenting-editor").display

        await pilot.press("enter")
        assert app.screen.query_one("#bone-editor").display
        assert _focused_id(app) == "bone-name"


async def test_form_lists_every_bone_already_in_the_spec(tmp_path, monkeypatch):
    """The full list lives here — the detail page only shows a count."""
    path = _spec(tmp_path)
    bones = [f"bone{i}" for i in range(40)]
    specs_store.update_armature(path, add_bones=bones)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(80, 24)) as pilot:
        await _open(pilot, app, path)
        assert await _wait_for(pilot, lambda: _listed(app) == bones)


def _armature_name(app):
    return app.screen.query_one("#armature-name", Input)


def _name_view(app):
    return [str(row.render()) for row in _rows(app, "armature-name-view")]


async def test_armature_name_is_read_only_and_one_shift_tab_away(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    specs_store.update_armature(path, object_name="Rig")
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(pilot, app, path)
        assert _name_view(app) == ["Rig"]
        assert not _armature_name(app).display
        await pilot.press("shift+tab")
        assert _focused_id(app) == "armature-name-view"

        await pilot.press("enter")
        assert _armature_name(app).display
        assert not app.screen.query_one("#armature-name-view").display
        assert _armature_name(app).value == "Rig"
        assert _focused_id(app) == "armature-name"


async def test_unset_armature_name_reads_not_set(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(pilot, app, path)
        view = app.screen.query_one("#armature-name-view .field-list-empty")
        assert str(view.render()) == "not set"


async def test_armature_name_is_saved_on_enter_and_closes(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    specs_store.update_armature(path, add_bones=["body"])
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(pilot, app, path)
        await _edit(pilot, app, "armature-name-view")
        await _type(pilot, "  Rig[L] ")

        assert _armature(path)["object_name"] == "Rig[L]"
        assert _armature(path)["required_bones"] == ["body"]
        assert _status(app) == "Armature name saved."
        assert not _armature_name(app).display
        assert _name_view(app) == ["Rig[L]"]
        assert _focused_id(app) == "armature-name-view"


async def test_blank_armature_name_clears_it(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    specs_store.update_armature(path, object_name="Rig")
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(pilot, app, path)
        await _edit(pilot, app, "armature-name-view")
        _armature_name(app).value = ""
        await _type(pilot, "")

        assert _armature(path)["object_name"] == ""
        assert _status(app) == "Armature name cleared."
        assert _name_view(app) == []


async def test_over_long_armature_name_is_rejected(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    before = path.read_bytes()
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(pilot, app, path)
        await _edit(pilot, app, "armature-name-view")
        _armature_name(app).value = "a" * 64
        await _type(pilot, "")

        assert path.read_bytes() == before
        assert _armature_name(app).value == "a" * 64
        assert "63 bytes" in _status(app)
        assert _focused_id(app) == "armature-name"


async def test_escape_closes_the_name_editor_unsaved_then_leaves(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    specs_store.update_armature(path, object_name="Rig")
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(pilot, app, path)
        await _edit(pilot, app, "armature-name-view")
        await pilot.press("end", "2")
        assert _armature_name(app).value == "Rig2"

        await pilot.press("escape")
        await pilot.pause()
        assert not _armature_name(app).display
        assert _name_view(app) == ["Rig"]
        assert _focused_id(app) == "armature-name-view"
        assert _armature(path)["object_name"] == "Rig"

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))


async def test_plain_name_is_written_listed_and_cleared(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open(pilot, app, path)
        await _edit(pilot, app, "bone-list")
        await _type(pilot, "body")

        assert _armature(path)["required_bones"] == ["body"]
        assert _listed(app) == ["body"]
        assert app.screen.query_one("#bone-name", Input).value == ""
        assert _focused_id(app) == "bone-name"


async def test_wheel_front_left_end_to_end(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(80, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit(pilot, app, "bone-list")
        await _type(pilot, "wheel.front.L")

        assert "Inverse of `.front`" in _inverse_label(app)
        assert "leave blank" in _inverse_label(app)
        assert _focused_id(app) == "bone-inverse"

        await _type(pilot, ".rear")
        assert _armature(path)["bone_name_inverses"] == FRONT_REAR
        assert _variants(app) == ["wheel.front.R", "wheel.rear.L", "wheel.rear.R"]
        assert _focused_id(app) == "add-bones"

        await pilot.press("enter")
        await pilot.pause()
        assert _armature(path)["required_bones"] == [
            "wheel.front.L",
            "wheel.front.R",
            "wheel.rear.L",
            "wheel.rear.R",
        ]
        assert not app.screen.query("#bone-variants")
        assert _focused_id(app) == "bone-name"


async def test_full_chain_first_with_two_unmapped_segments(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(80, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit(pilot, app, "bone-list")
        before = path.read_bytes()

        await _type(pilot, "susarm.front.top.L")
        assert "`.front`" in _inverse_label(app)
        await _type(pilot, "rear")  # leading dot added

        assert path.read_bytes() == before
        assert not app.screen.query("#bone-variants")
        assert "`.top`" in _inverse_label(app)

        await _type(pilot, ".bottom")
        assert _armature(path)["bone_name_inverses"] == {
            **FRONT_REAR,
            ".top": ".bottom",
            ".bottom": ".top",
        }
        assert len(_variants(app)) == 7

        await pilot.press("enter")
        await pilot.pause()
        assert len(_armature(path)["required_bones"]) == 8


async def test_several_bones_in_one_visit_and_builtin_only_skips_questions(
    tmp_path, monkeypatch
):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(80, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit(pilot, app, "bone-list")
        await _type(pilot, "body")
        await _type(pilot, "arm.L")

        assert not app.screen.query("#bone-inverse")
        assert _variants(app) == ["arm.R"]
        await pilot.press("enter")
        await pilot.pause()

        await _type(pilot, "head")
        assert _armature(path)["required_bones"] == ["body", "arm.L", "arm.R", "head"]
        assert _listed(app) == ["body", "arm.L", "arm.R", "head"]


async def test_unchecking_a_variant_leaves_it_out(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(80, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit(pilot, app, "bone-list")
        await _type(pilot, "wheel.front.L")
        await _type(pilot, ".rear")

        checklist = app.screen.query_one("#bone-variants", SelectionList)
        checklist.deselect("wheel.rear.L")
        await pilot.pause()
        await pilot.press("enter")  # focus is still on Add
        await pilot.pause()

        assert _armature(path)["required_bones"] == [
            "wheel.front.L",
            "wheel.front.R",
            "wheel.rear.R",
        ]


async def test_blank_inverse_is_saved_as_a_self_mapping(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(80, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit(pilot, app, "bone-list")
        await _type(pilot, "finger.tip")
        await _type(pilot, "")

        # Nothing to choose: written directly, no checklist.
        assert _armature(path)["bone_name_inverses"] == {".tip": ".tip"}
        assert _armature(path)["required_bones"] == ["finger.tip"]
        assert not app.screen.query("#bone-variants")

        await _type(pilot, "toe.tip")
        assert not app.screen.query("#bone-inverse")
        assert _armature(path)["required_bones"] == ["finger.tip", "toe.tip"]


async def test_checklist_skipped_when_every_variant_is_required(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    specs_store.update_armature(path, add_bones=["arm.R"])
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(80, 40)) as pilot:
        await _open(pilot, app, path)
        await _add_mode(pilot, app)
        await _type(pilot, "arm.L")

        assert not app.screen.query("#bone-variants")
        assert _armature(path)["required_bones"] == ["arm.R", "arm.L"]


async def test_back_from_checklist_rewrites_the_mapping(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(80, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit(pilot, app, "bone-list")
        await _type(pilot, "wheel.front.L")
        await _type(pilot, ".rear")
        assert _armature(path)["bone_name_inverses"] == FRONT_REAR

        await pilot.press("escape")
        await pilot.pause()
        assert not app.screen.query("#bone-variants")
        inverse = app.screen.query_one("#bone-inverse", Input)
        assert inverse.value == ".rear"  # pre-filled with the earlier answer

        inverse.value = ""
        await _type(pilot, ".back")
        assert _armature(path)["bone_name_inverses"] == {
            ".front": ".back",
            ".back": ".front",
        }
        assert _variants(app) == ["wheel.front.R", "wheel.back.L", "wheel.back.R"]


async def test_escape_semantics(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(80, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit(pilot, app, "bone-list")
        await _type(pilot, "wheel.front.L")

        await pilot.press("escape")  # inverse question → name field
        await pilot.pause()
        assert not app.screen.query("#bone-inverse")
        name = app.screen.query_one("#bone-name", Input)
        assert name.value == "wheel.front.L"
        assert _focused_id(app) == "bone-name"

        await pilot.press("escape")  # idle with text → cleared
        await pilot.pause()
        assert name.value == ""
        assert isinstance(app.screen, ArmatureFormScreen)

        await pilot.press("escape")  # idle and empty → closes the editor
        await pilot.pause()
        assert not app.screen.query_one("#bone-editor").display
        assert _focused_id(app) == "bone-list"
        assert isinstance(app.screen, ArmatureFormScreen)

        await pilot.press("escape")  # nothing open → leaves
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))
        assert _armature(path)["required_bones"] == []


async def test_failures_keep_text_and_write_nothing(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    specs_store.update_armature(
        path, add_bones=["body"], set_inverses={".top": ".bottom", ".bottom": ".top"}
    )
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(80, 40)) as pilot:
        await _open(pilot, app, path)
        await _add_mode(pilot, app)
        before = path.read_bytes()

        await _type(pilot, "body")
        assert "already required" in _status(app)
        assert app.screen.query_one("#bone-name", Input).value == "body"

        app.screen.query_one("#bone-name", Input).value = ""
        await _type(pilot, "a..b")
        assert "empty segment" in _status(app)

        app.screen.query_one("#bone-name", Input).value = ""
        await _type(pilot, "wheel.front.L")
        await _type(pilot, ".bottom")
        assert "already paired with '.top'" in _status(app)
        assert app.screen.query_one("#bone-inverse", Input).value == ".bottom"

        assert path.read_bytes() == before


async def test_unwritable_spec_reports_and_keeps_the_name(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)

    def refuse(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    async with app.run_test(size=(80, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit(pilot, app, "bone-list")
        monkeypatch.setattr(specs_store, "update_armature", refuse)
        await _type(pilot, "body")

        assert "Permission denied" in _status(app)
        assert app.screen.query_one("#bone-name", Input).value == "body"
        assert _armature(path)["required_bones"] == []


async def test_q_does_not_quit_from_the_add_button(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(80, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit(pilot, app, "bone-list")
        await _type(pilot, "arm.L")
        assert _focused_id(app) == "add-bones"

        await pilot.press("q")
        await pilot.pause()
        assert app.is_running


# --- parenting -------------------------------------------------------------

CORNERS = ["front.L", "front.R", "rear.L", "rear.R"]
RIG = [
    "root",
    *(f"axle.{c}" for c in CORNERS),
    *(f"wheel.{c}" for c in CORNERS),
    *(f"shockmount.body.{c}" for c in CORNERS),
    *(f"shockmount.wheel.{c}" for c in CORNERS),
]
RIG_INVERSES = {**FRONT_REAR, ".body": ".wheel", ".wheel": ".body"}


def _rig(tmp_path, parenting=None):
    path = _spec(tmp_path)
    specs_store.update_armature(
        path, add_bones=RIG, set_inverses=RIG_INVERSES, add_parenting=parenting
    )
    return path


async def _choose(pilot, app, parents):
    await _edit(pilot, app, "parenting-list")
    assert _focused_id(app) == "parent-bones"
    checklist = app.screen.query_one("#parent-bones", SelectionList)
    for parent in parents:
        checklist.select(parent)
    await pilot.press("tab")
    assert _focused_id(app) == "choose-children"
    await pilot.press("enter")
    await pilot.pause()


def _corners(base):
    return [f"{base}.{c}" for c in CORNERS]


def _children(app):
    (checklist,) = app.screen.query("#child-bones")
    return [
        checklist.get_option_at_index(i).value for i in range(checklist.option_count)
    ]


def _parenting_rows(app):
    return [
        ("  " if row.has_class("field-list-child") else "") + str(row.render())
        for row in _rows(app, "parenting-list")
    ]


async def test_parenting_section_empty_states(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        assert app.screen.query_one("#parenting-list .field-list-empty")
        await _edit(pilot, app, "parenting-list")
        assert _status(app) == "Add required bones first."
        assert not app.screen.query_one("#parenting-editor").display
        assert _focused_id(app) == "parenting-list"


async def test_checked_parents_end_to_end(tmp_path, monkeypatch):
    path = _rig(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 50)) as pilot:
        await _open(pilot, app, path)
        await _choose(pilot, app, _corners("axle"))
        assert _focused_id(app) == "child-bones"
        assert not app.screen.query_one("#parent-picker").display

        checklist = app.screen.query_one("#child-bones", SelectionList)
        for child in [*_corners("wheel"), *_corners("shockmount.wheel")]:
            checklist.select(child)
        await pilot.pause()
        preview = str(app.screen.query_one("#parenting-preview", Static).render())
        assert preview.startswith(
            "axle.{1}.{2}\n  wheel.{1}.{2}\n  shockmount.wheel.{1}.{2}\n"
        )
        assert "8 pairs" in preview

        app.screen.query_one("#add-children").press()
        assert await _wait_for(pilot, lambda: _status(app) == "Parenting saved.")
        assert _armature(path)["parenting"] == {
            "axle.{1}.{2}": ["wheel.{1}.{2}", "shockmount.wheel.{1}.{2}"]
        }
        assert _focused_id(app) == "parent-bones"
        assert app.screen.query_one("#parent-bones", SelectionList).selected == []
        assert not app.screen.query("#child-bones")
        assert _parenting_rows(app) == [
            "axle.{1}.{2}",
            "  wheel.{1}.{2}",
            "  shockmount.wheel.{1}.{2}",
        ]


async def test_children_exclude_parents_parented_bones_and_ancestors(
    tmp_path, monkeypatch
):
    path = _rig(tmp_path, {"root": ["axle.{1}.{2}"]})
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 50)) as pilot:
        await _open(pilot, app, path)
        await _choose(pilot, app, ["axle.front.L", "wheel.front.L"])
        children = _children(app)
        assert "root" not in children
        assert "wheel.front.L" not in children
        assert not any(name.startswith("axle.") for name in children)
        assert "wheel.front.R" in children


async def test_choose_with_no_parents_checked_shows_a_status(tmp_path, monkeypatch):
    path = _rig(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 50)) as pilot:
        await _open(pilot, app, path)
        await _choose(pilot, app, [])
        assert _status(app) == "Check at least one parent."
        assert not app.screen.query("#child-bones")


async def test_add_with_nothing_checked_writes_nothing(tmp_path, monkeypatch):
    path = _rig(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 50)) as pilot:
        await _open(pilot, app, path)
        before = path.read_bytes()
        await _choose(pilot, app, ["root"])
        app.screen.query_one("#add-children").press()
        await pilot.pause()
        assert _status(app) == "Check at least one child."
        assert path.read_bytes() == before


async def test_unpairable_child_is_reported_and_not_written(tmp_path, monkeypatch):
    path = _rig(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 50)) as pilot:
        await _open(pilot, app, path)
        before = path.read_bytes()
        await _choose(pilot, app, _corners("wheel"))
        app.screen.query_one("#child-bones", SelectionList).select("root")
        await pilot.pause()
        preview = str(app.screen.query_one("#parenting-preview", Static).render())
        assert "'root' matches no checked parent." in preview

        app.screen.query_one("#add-children").press()
        await pilot.pause()
        assert _status(app) == "'root' matches no checked parent."
        assert path.read_bytes() == before


async def test_no_eligible_children_shows_a_status(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    specs_store.update_armature(
        path, add_bones=["root", "body"], add_parenting={"root": ["body"]}
    )
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _choose(pilot, app, ["root"])
        assert _status(app) == "Every other bone already has a parent."
        assert not app.screen.query("#child-bones")


async def test_parenting_escape_steps_back_then_clears_then_leaves(
    tmp_path, monkeypatch
):
    path = _rig(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 50)) as pilot:
        await _open(pilot, app, path)
        before = path.read_bytes()
        await _choose(pilot, app, ["root"])
        app.screen.query_one("#child-bones", SelectionList).select("axle.front.L")
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()
        parents = app.screen.query_one("#parent-bones", SelectionList)
        assert not app.screen.query("#child-bones")
        assert app.screen.query_one("#parent-picker").display
        assert _focused_id(app) == "parent-bones"
        assert parents.selected == ["root"]

        await pilot.press("escape")
        await pilot.pause()
        assert parents.selected == []
        assert app.screen.query_one("#parenting-editor").display

        await pilot.press("escape")
        await pilot.pause()
        assert not app.screen.query_one("#parenting-editor").display
        assert _focused_id(app) == "parenting-list"
        assert path.read_bytes() == before

        await pilot.press("escape")
        assert await _wait_for(
            pilot, lambda: not isinstance(app.screen, ArmatureFormScreen)
        )


async def test_new_bone_refreshes_the_parent_list(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit(pilot, app, "bone-list")
        await _type(pilot, "body")
        assert app.screen._parents == ["body"]
        assert app.screen.query_one("#parent-picker").display


async def test_opening_a_field_closes_the_other_unwritten(tmp_path, monkeypatch):
    path = _rig(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 50)) as pilot:
        await _open(pilot, app, path)
        before = path.read_bytes()
        await _add_mode(pilot, app)
        await _type(pilot, "arm.top")
        assert app.screen.query("#bone-inverse")

        await _choose(pilot, app, ["root"])
        assert not app.screen.query_one("#bone-editor").display
        assert not app.screen.query("#bone-inverse")
        assert app.screen.query_one("#bone-name", Input).value == ""
        assert _focused_id(app) == "child-bones"

        await _add_mode(pilot, app)
        assert not app.screen.query_one("#parenting-editor").display
        assert not app.screen.query("#child-bones")
        assert app.screen.query_one("#parent-bones", SelectionList).selected == []
        assert _focused_id(app) == "bone-name"
        assert path.read_bytes() == before


async def test_clicking_a_field_opens_its_editor(tmp_path, monkeypatch):
    path = _rig(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 50)) as pilot:
        await _open(pilot, app, path)
        await pilot.click("#parenting-list")
        await pilot.pause()
        assert app.screen.query_one("#parenting-editor").display
        assert _focused_id(app) == "parent-bones"


# --- the bone list cursor and `a` ---------------------------------------------


def _highlighted(app):
    return app.screen.query_one("#bone-list").highlighted


def _bindings(app):
    return {b.binding.key for b in app.screen.active_bindings.values()}


async def test_bone_list_cursor_moves_without_wrapping(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    specs_store.update_armature(path, add_bones=["root", "body", "head"])
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        assert _focused_id(app) == "bone-list"
        assert _highlighted(app) == 0

        await pilot.press("up")
        assert _highlighted(app) == 0
        await pilot.press("down", "down", "down")
        assert _highlighted(app) == 2
        await pilot.pause()
        highlighted = _rows(app, "bone-list")[2]
        assert highlighted.has_class("field-list-highlighted")


async def test_a_adds_from_the_bone_list_only(tmp_path, monkeypatch):
    path = _rig(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 50)) as pilot:
        await _open(pilot, app, path)
        assert "a" in _bindings(app)

        app.screen.query_one("#parenting-list").focus()
        await pilot.pause()
        assert "a" not in _bindings(app)
        await pilot.press("a")
        await pilot.pause()
        assert not app.screen.query_one("#bone-editor").display

        await _add_mode(pilot, app)
        assert app.screen.query_one("#bone-editor").display
        assert _focused_id(app) == "bone-name"
        await _type(pilot, "tail")
        assert _armature(path)["required_bones"][-1] == "tail"
        assert _focused_id(app) == "bone-name"


# --- renaming a bone ---------------------------------------------------------


def _arms(tmp_path):
    path = _spec(tmp_path)
    specs_store.update_armature(
        path, add_bones=["root", "arm.L", "arm.R"], add_parenting={"root": ["arm.{1}"]}
    )
    specs_store.add_mesh_role(path, "arm", "arm.{1}", "^m$", 1)
    specs_store.add_mesh_role(path, "base", "root", "^m$", 1)
    return path


async def _edit_bone(pilot, app, index):
    bone_list = app.screen.query_one("#bone-list")
    bone_list.focus()
    bone_list.highlighted = index
    await pilot.press("enter")
    await pilot.pause()


async def _retype(pilot, app, text):
    app.screen.query_one("#bone-name", Input).value = text
    await pilot.press("enter")
    await pilot.pause()


def _label(app):
    return str(app.screen.query_one("#bone-name-label", Static).render())


def _marked(app):
    return [
        str(row.render())
        for row in _rows(app, "parenting-list")
        if row.has_class("field-list-marked")
    ]


async def test_enter_on_a_bone_opens_it_for_renaming(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit_bone(pilot, app, 1)

        assert app.screen.query_one("#bone-editor").display
        assert app.screen.query_one("#bone-name", Input).value == "arm.L"
        assert _label(app) == "Rename 'arm.L'"
        assert _focused_id(app) == "bone-name"


async def test_rename_writes_in_place_closes_and_warns(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit_bone(pilot, app, 1)
        await _retype(pilot, app, "upperarm.L")

        assert _armature(path)["required_bones"] == ["root", "upperarm.L", "arm.R"]
        assert _armature(path)["parenting"] == {"root": ["arm.{1}"]}
        assert not app.screen.query_one("#bone-editor").display
        assert _label(app) == "Bone name"
        assert _focused_id(app) == "bone-list"
        assert _highlighted(app) == 1
        assert _listed(app) == ["root", "upperarm.L", "arm.R"]
        assert _status(app) == (
            "Bone 'upperarm.L' saved. 'arm.L' was matched by parenting 'root' "
            "and mesh role 'arm' — update them."
        )
        assert _marked(app) == ["arm.{1}"]  # the child line, not its key

        await pilot.press("up")
        await pilot.pause()
        assert _marked(app) == ["arm.{1}"]

        await pilot.press("a")
        await pilot.pause()
        assert _status(app) == ""
        assert _marked(app) == []


async def test_rename_asks_new_inverses_and_adds_no_variants(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit_bone(pilot, app, 1)
        await _retype(pilot, app, "arm.L.upper")
        assert _inverse_label(app).startswith("Inverse of `.upper`")
        assert _armature(path)["required_bones"] == ["root", "arm.L", "arm.R"]

        await _type(pilot, "lower")
        assert not app.screen.query("#bone-variants")
        armature = _armature(path)
        assert armature["required_bones"] == ["root", "arm.L.upper", "arm.R"]
        assert armature["bone_name_inverses"] == {
            ".upper": ".lower",
            ".lower": ".upper",
        }
        assert _status(app) == (
            "Bone 'arm.L.upper' saved. 'arm.L' was matched by parenting 'root' "
            "and mesh role 'arm' — update them."
        )


async def test_rename_a_pattern_still_covers_has_no_warning(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit_bone(pilot, app, 1)
        await _retype(pilot, app, "arm.C")
        await _type(pilot, "")  # `.C` has no inverse

        assert _armature(path)["required_bones"] == ["root", "arm.C", "arm.R"]
        assert _armature(path)["bone_name_inverses"] == {".C": ".C"}
        assert _status(app) == "Bone 'arm.C' saved."
        assert _marked(app) == []


async def test_rename_warns_with_one_reference(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit_bone(pilot, app, 0)
        await _retype(pilot, app, "base")

        assert _status(app) == (
            "Bone 'base' saved. 'root' was matched by parenting 'root' "
            "and mesh role 'base' — update them."
        )
        assert _marked(app) == ["root"]

        await _edit_bone(pilot, app, 1)
        assert _status(app) == ""
        assert _marked(app) == []


async def test_rename_onto_another_bone_is_rejected(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        before = path.read_bytes()
        await _edit_bone(pilot, app, 1)
        await _retype(pilot, app, "arm.R")

        assert _status(app) == "'arm.R' is already required."
        assert app.screen.query_one("#bone-editor").display
        assert app.screen.query_one("#bone-name", Input).value == "arm.R"
        assert path.read_bytes() == before

        await _retype(pilot, app, "")
        assert _status(app) == "Enter a bone name."
        assert path.read_bytes() == before


async def test_rename_to_its_own_name_is_accepted(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit_bone(pilot, app, 2)
        await pilot.press("enter")
        await pilot.pause()

        assert _armature(path)["required_bones"] == ["root", "arm.L", "arm.R"]
        assert _status(app) == "Bone 'arm.R' saved."
        assert not app.screen.query_one("#bone-editor").display


async def test_rename_escape_steps_back_then_closes_unsaved(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        before = path.read_bytes()
        await _edit_bone(pilot, app, 1)
        await _retype(pilot, app, "arm.L.upper")
        assert app.screen.query("#bone-inverse")

        await pilot.press("escape")  # question → name, text kept
        await pilot.pause()
        assert not app.screen.query("#bone-inverse")
        assert app.screen.query_one("#bone-name", Input).value == "arm.L.upper"

        await pilot.press("escape")  # closes unsaved, no clearing step
        await pilot.pause()
        assert not app.screen.query_one("#bone-editor").display
        assert _focused_id(app) == "bone-list"
        assert _highlighted(app) == 1
        assert isinstance(app.screen, ArmatureFormScreen)
        assert path.read_bytes() == before


async def test_switching_between_add_and_rename(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        before = path.read_bytes()
        await _edit_bone(pilot, app, 1)
        app.screen.query_one("#bone-name", Input).value = "typed"

        await _edit_bone(pilot, app, 1)  # the same bone: nothing resets
        assert app.screen.query_one("#bone-name", Input).value == "typed"
        assert _focused_id(app) == "bone-name"

        await _add_mode(pilot, app)  # rename → add, discarded
        assert app.screen.query_one("#bone-name", Input).value == ""
        assert _label(app) == "Bone name"
        app.screen.query_one("#bone-name", Input).value = "tail"

        await _edit_bone(pilot, app, 2)  # add → rename, discarded
        assert app.screen.query_one("#bone-name", Input).value == "arm.R"
        assert _label(app) == "Rename 'arm.R'"

        await _edit(pilot, app, "parenting-list")  # rename → another field
        assert not app.screen.query_one("#bone-editor").display
        assert app.screen._original is None
        assert path.read_bytes() == before


async def test_clicking_a_bone_renames_it(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await pilot.click(_rows(app, "bone-list")[2])
        await pilot.pause()

        assert app.screen.query_one("#bone-name", Input).value == "arm.R"
        assert _highlighted(app) == 2


async def test_renaming_a_bone_removed_by_hand(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit_bone(pilot, app, 1)
        document = json.loads(path.read_text(encoding="utf-8"))
        document["armature"]["required_bones"] = ["root", "arm.R"]
        path.write_text(json.dumps(document), encoding="utf-8")
        before = path.read_bytes()

        await _retype(pilot, app, "upperarm.L")
        assert _status(app) == "'arm.L' is no longer a required bone."
        assert path.read_bytes() == before

        await pilot.press("escape")
        await pilot.pause()
        await _edit_bone(pilot, app, 0)
        await pilot.press("escape")
        await pilot.pause()
        await _edit_bone(pilot, app, 1)
        assert _listed(app) == ["root", "arm.R"]


# --- deleting a bone ---------------------------------------------------------


async def _delete(pilot, app, index, *keys):
    """Highlight bone `index`, press `x`, then `keys` in the dialog."""
    bone_list = app.screen.query_one("#bone-list")
    bone_list.focus()
    bone_list.highlighted = index
    await pilot.press("x")
    assert await _wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
    await pilot.pause()
    if keys:
        await pilot.press(*keys)
    assert await _wait_for(pilot, lambda: isinstance(app.screen, ArmatureFormScreen))
    await pilot.pause()


async def test_x_deletes_from_a_non_empty_bone_list_only(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    specs_store.update_armature(path, add_bones=["root"])
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        assert "x" in _bindings(app)

        app.screen.query_one("#parenting-list").focus()
        await pilot.pause()
        assert "x" not in _bindings(app)
        await pilot.press("x")
        await pilot.pause()
        assert isinstance(app.screen, ArmatureFormScreen)

        await _delete(pilot, app, 0, "right", "enter")
        assert _armature(path)["required_bones"] == []
        assert _highlighted(app) is None
        assert "x" not in _bindings(app)

        await pilot.press("enter")  # an empty list still opens Add
        await pilot.pause()
        assert _focused_id(app) == "bone-name"


async def test_dialog_asks_about_the_highlighted_bone(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        app.screen.query_one("#bone-list").highlighted = 1
        await pilot.press("x")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        await pilot.pause()
        question = app.screen.query_one("#confirm-question", Static)
        assert str(question.render()) == "Delete 'arm.L'?"
        assert _focused_id(app) == "confirm-no"


async def test_no_and_escape_cancel_and_write_nothing(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    before = path.read_bytes()
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        for keys in (("enter",), ("escape",)):
            await _delete(pilot, app, 1, *keys)
            assert path.read_bytes() == before
            assert _focused_id(app) == "bone-list"
            assert _highlighted(app) == 1
            assert _status(app) == ""


async def test_yes_deletes_only_that_bone(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    before = json.loads(path.read_text(encoding="utf-8"))
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _delete(pilot, app, 1, "right", "enter")

        after = json.loads(path.read_text(encoding="utf-8"))
        before["armature"]["required_bones"] = ["root", "arm.R"]
        assert after == before  # parenting and mesh roles untouched
        assert _listed(app) == ["root", "arm.R"]
        assert _focused_id(app) == "bone-list"
        assert _highlighted(app) == 1  # the bone that moved up
        assert _status(app) == "Bone 'arm.L' deleted."
        assert _marked(app) == []

        await _delete(pilot, app, 1, "right", "enter")
        assert _listed(app) == ["root"]
        assert _highlighted(app) == 0  # clamped to the new last bone


async def test_deleting_the_last_match_warns_and_marks(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _delete(pilot, app, 1, "right", "enter")
        assert _status(app) == "Bone 'arm.L' deleted."  # `arm.{1}` still has arm.R
        assert _marked(app) == []

        await _delete(pilot, app, 1, "right", "enter")
        assert _status(app) == (
            "Bone 'arm.R' deleted. Parenting 'root' and mesh role 'arm' "
            "now match no bone — update them."
        )
        assert _marked(app) == ["arm.{1}"]  # the child line, not its key
        assert _armature(path)["parenting"] == {"root": ["arm.{1}"]}

        await pilot.press("up")
        await pilot.pause()
        assert _marked(app) == ["arm.{1}"]

        await pilot.press("a")
        await pilot.pause()
        assert _status(app) == ""
        assert _marked(app) == []


async def test_deleting_a_parent_marks_its_key(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _delete(pilot, app, 0, "right", "enter")

        assert _status(app) == (
            "Bone 'root' deleted. Parenting 'root' and mesh role 'base' "
            "now match no bone — update them."
        )
        assert _marked(app) == ["root"]


async def test_deleting_with_one_reference_says_it(tmp_path, monkeypatch):
    path = _spec(tmp_path)
    specs_store.update_armature(
        path, add_bones=["root", "spine"], add_parenting={"root": ["spine"]}
    )
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _delete(pilot, app, 1, "right", "enter")

        assert _status(app) == (
            "Bone 'spine' deleted. Parenting 'root' now matches no bone — update it."
        )
        assert _marked(app) == ["spine"]


async def test_yes_closes_an_open_rename_and_no_keeps_it(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        await _edit_bone(pilot, app, 1)
        app.screen.query_one("#bone-name", Input).value = "upperarm.L"

        await _delete(pilot, app, 1, "enter")
        assert app.screen.query_one("#bone-editor").display
        assert app.screen.query_one("#bone-name", Input).value == "upperarm.L"

        await _delete(pilot, app, 1, "right", "enter")
        assert not app.screen.query_one("#bone-editor").display
        assert _label(app) == "Bone name"
        assert _armature(path)["required_bones"] == ["root", "arm.R"]
        assert _focused_id(app) == "bone-list"


async def test_a_bone_gone_by_hand_reports_and_refreshes(tmp_path, monkeypatch):
    path = _arms(tmp_path)
    app = _app(tmp_path, monkeypatch)
    async with app.run_test(size=(100, 40)) as pilot:
        await _open(pilot, app, path)
        app.screen.query_one("#bone-list").highlighted = 1
        await pilot.press("x")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, ConfirmModal))
        await pilot.pause()
        specs_store.delete_bone(path, "arm.L")
        await pilot.press("right", "enter")
        assert await _wait_for(
            pilot, lambda: isinstance(app.screen, ArmatureFormScreen)
        )
        await pilot.pause()

        assert _status(app) == (
            "Could not write the spec: 'arm.L' is no longer a required bone."
        )
        assert _listed(app) == ["root", "arm.R"]
