"""Link-spec modal tests: the spec picker shown for a model with no results file."""

from textual.app import App
from textual.widgets import OptionList, Static

from model_meta.tui.screens.link_spec_modal import LinkSpecModal


class _Host(App):
    def __init__(self, specs):
        super().__init__()
        self.specs = specs
        self.result = "unset"

    def on_mount(self):
        self.push_screen(LinkSpecModal("car.blend", self.specs), self._done)

    def _done(self, result):
        self.result = result


async def test_lists_the_specs_and_enter_picks_the_highlighted_one():
    app = _Host(["truck", "vehicle"])
    async with app.run_test() as pilot:
        await pilot.pause()
        options = app.screen.query_one("#spec-options", OptionList)
        assert [
            str(options.get_option_at_index(i).prompt)
            for i in range(options.option_count)
        ] == ["truck", "vehicle"]
        assert app.screen.focused is options

        await pilot.press("down", "enter")
        await pilot.pause()
        assert app.result == "vehicle"


async def test_no_specs_shows_a_note_and_escape_returns_none():
    app = _Host([])
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not app.screen.query("#spec-options")
        assert app.screen.query_one("#no-specs", Static).display

        await pilot.press("escape")
        await pilot.pause()
        assert app.result is None


async def test_escape_returns_none():
    app = _Host(["vehicle"])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.result is None


async def test_q_does_not_quit():
    app = _Host(["vehicle"])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert app.is_running
        assert isinstance(app.screen, LinkSpecModal)
