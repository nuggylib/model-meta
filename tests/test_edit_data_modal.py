"""Edit-data modal tests: the root-field picker opened by `e` on a spec."""

from textual.app import App
from textual.widgets import OptionList

from model_meta.specs import schema
from model_meta.tui.screens.edit_data_modal import FIELDS, EditDataModal


class _Host(App):
    def __init__(self):
        super().__init__()
        self.result = "unset"

    def on_mount(self):
        self.push_screen(EditDataModal(), self._done)

    def _done(self, result):
        self.result = result


def test_field_keys_are_skeleton_root_keys():
    assert {key for key, _ in FIELDS} <= set(schema.skeleton("x"))


async def test_options_are_armature_mesh_roles_modifiers_and_enter_picks():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        options = app.screen.query_one("#data-fields", OptionList)
        assert [
            str(options.get_option_at_index(i).prompt)
            for i in range(options.option_count)
        ] == ["Armature", "Mesh roles", "Modifiers"]
        assert app.screen.focused is options

        await pilot.press("enter")
        await pilot.pause()
        assert app.result == "armature"


async def test_mesh_roles_returns_its_key():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down", "enter")
        await pilot.pause()
        assert app.result == "mesh_roles"


async def test_modifiers_returns_its_key():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        assert app.result == "modifiers"


async def test_escape_returns_none():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.result is None


async def test_q_does_not_quit():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert app.is_running
        assert isinstance(app.screen, EditDataModal)
