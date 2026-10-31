import threading

from textual.app import App
from textual.widgets import Static

from model_meta.core.blender_connection import BlenderConnection
from model_meta.tui.screens.model_dashboard import ModelDashboardScreen


class _Host(App):
    def __init__(self, screen):
        super().__init__()
        self._screen = screen

    def on_mount(self):
        self.push_screen(self._screen)


def _text(widget):
    return str(widget.render())


async def _wait_for(pilot, predicate, tries=100):
    for _ in range(tries):
        if predicate():
            return True
        await pilot.pause()
    return False


def _fake_running(monkeypatch, *answers):
    """Each check returns the next answer; an `Event` blocks until it is set."""
    calls = []

    def is_running(cls, timeout=5.0):
        answer = answers[min(len(calls), len(answers) - 1)]
        calls.append(answer)
        if isinstance(answer, threading.Event):
            answer.wait(5)
            return True
        return answer

    monkeypatch.setattr(BlenderConnection, "is_running", classmethod(is_running))
    return calls


def _screen(tmp_path):
    return ModelDashboardScreen("sedan", tmp_path / "vehicle.json")


def _status(screen):
    return _text(screen.query_one("#connection-status", Static))


def _rows(screen):
    return [_text(row) for row in screen.query(".model-item-depth-0")]


async def test_running_blender_shows_manual_mode(tmp_path, monkeypatch):
    _fake_running(monkeypatch, True)
    screen = _screen(tmp_path)
    async with _Host(screen).run_test() as pilot:
        assert await _wait_for(pilot, lambda: _status(screen) == "Manual Mode")
        assert not screen.query_one("#connection-hint").display


async def test_no_blender_shows_inactive_and_hint(tmp_path, monkeypatch):
    _fake_running(monkeypatch, False)
    screen = _screen(tmp_path)
    async with _Host(screen).run_test() as pilot:
        assert await _wait_for(pilot, lambda: _status(screen) == "Inactive")
        hint = screen.query_one("#connection-hint", Static)
        assert hint.display
        assert _text(hint) == "Start Blender, then press r to refresh."


async def test_rows_show_refreshing_emoji_until_the_check_returns(
    tmp_path, monkeypatch
):
    release = threading.Event()
    _fake_running(monkeypatch, release)
    screen = _screen(tmp_path)
    async with _Host(screen).run_test() as pilot:
        assert await _wait_for(pilot, lambda: screen.is_refreshing)
        assert all(row.startswith("🔄 ") for row in _rows(screen))
        release.set()
        assert await _wait_for(pilot, lambda: not screen.is_refreshing)
        assert all(row.startswith("🟡 ") for row in _rows(screen))
        assert _status(screen) == "Manual Mode"


async def test_r_checks_again(tmp_path, monkeypatch):
    calls = _fake_running(monkeypatch, False, True)
    screen = _screen(tmp_path)
    async with _Host(screen).run_test() as pilot:
        assert await _wait_for(pilot, lambda: _status(screen) == "Inactive")
        await pilot.press("r")
        assert await _wait_for(pilot, lambda: _status(screen) == "Manual Mode")
        assert len(calls) == 2
        assert not screen.query_one("#connection-hint").display
