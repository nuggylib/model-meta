"""Confirm modal tests: the Yes/No question asked before a delete."""

from textual.app import App
from textual.widgets import Static

from model_meta.tui.screens.confirm_modal import ConfirmModal


class _Host(App):
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, question="Delete 'arm.L'?"):
        super().__init__()
        self.question = question
        self.result = "unset"

    def on_mount(self):
        self.push_screen(ConfirmModal(self.question), self._done)

    def _done(self, result):
        self.result = result


async def test_question_renders_literally_and_no_is_focused():
    app = _Host("Delete 'arm[L]'?")
    async with app.run_test() as pilot:
        await pilot.pause()
        question = app.screen.query_one("#confirm-question", Static)
        assert str(question.render()) == "Delete 'arm[L]'?"
        assert app.screen.focused.id == "confirm-no"


async def test_enter_on_no_returns_false():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.result is False


async def test_clicking_yes_returns_true():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await pilot.pause()
        assert app.result is True


async def test_right_then_enter_returns_true_and_left_goes_back():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("right")
        assert app.screen.focused.id == "confirm-yes"
        await pilot.press("left")
        assert app.screen.focused.id == "confirm-no"
        await pilot.press("right", "enter")
        await pilot.pause()
        assert app.result is True


async def test_escape_returns_false():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.result is False


async def test_q_does_not_quit():
    app = _Host()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert app.is_running
        assert isinstance(app.screen, ConfirmModal)
