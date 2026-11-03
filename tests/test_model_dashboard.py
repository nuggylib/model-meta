import asyncio
import json
import threading

import pytest
from textual.app import App
from textual.widgets import Static

from model_meta.core.blender_bridge import BridgeError
from model_meta.core.blender_connection import BlenderConnection
from model_meta.tui.screens import model_dashboard
from model_meta.tui.screens.model_dashboard import ModelDashboardScreen

_DROP = object()


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


def _fake_bridge(monkeypatch, *, reachable=True):
    """Each put is yielded to the screen; `_DROP` closes the connection."""
    pushes = asyncio.Queue()

    async def subscribe_armatures(port=7417, timeout=2.0):
        if not reachable:
            raise BridgeError("The Blender add-on isn't reachable.")
        while (armatures := await pushes.get()) is not _DROP:
            yield armatures
        raise BridgeError("The Blender add-on closed the connection.")

    monkeypatch.setattr(model_dashboard, "subscribe_armatures", subscribe_armatures)
    return pushes


@pytest.fixture(autouse=True)
def _no_bridge(monkeypatch):
    _fake_bridge(monkeypatch, reachable=False)


def _screen(tmp_path, armature=None):
    path = tmp_path / "vehicle.json"
    if armature is not None:
        path.write_text(json.dumps({"armature": {"object_name": armature}}))
    return ModelDashboardScreen("sedan", path)


def _status(screen):
    return _text(screen.query_one("#connection-status", Static))


def _hint(screen):
    return _text(screen.query_one("#connection-hint", Static))


def _rows(screen):
    return [_text(row) for row in screen.query(".model-item-depth-0")]


async def test_running_blender_shows_manual_mode(tmp_path, monkeypatch):
    _fake_running(monkeypatch, True)
    screen = _screen(tmp_path)
    async with _Host(screen).run_test() as pilot:
        assert await _wait_for(pilot, lambda: _status(screen) == "Manual Mode")
        assert _hint(screen) == "Press r to refresh."


async def test_no_blender_shows_inactive_and_hint(tmp_path, monkeypatch):
    _fake_running(monkeypatch, False)
    screen = _screen(tmp_path)
    async with _Host(screen).run_test() as pilot:
        assert await _wait_for(pilot, lambda: _status(screen) == "Inactive")
        assert _hint(screen) == "Start Blender, then press r to refresh."


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
        assert _hint(screen) == "Press r to refresh."


async def test_reachable_add_on_shows_live_mode(tmp_path, monkeypatch):
    calls = _fake_running(monkeypatch, True)
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(["Rig"])
        assert await _wait_for(pilot, lambda: _status(screen) == "Live Mode")
        assert (
            _hint(screen)
            == "Results update when you load a file, or save one, in Blender."
        )
        assert calls == []


async def test_armature_in_scene_passes(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(["Other", "Rig"])
        assert await _wait_for(pilot, lambda: _rows(screen)[0] == "✅ Armature: Rig")
        assert all(row.startswith("🟡 ") for row in _rows(screen)[1:])


async def test_armature_missing_from_scene_fails(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(["Other"])
        assert await _wait_for(pilot, lambda: _rows(screen)[0] == "❌ Armature: Rig")


async def test_unnamed_armature_fails(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(["Rig"])
        assert await _wait_for(
            pilot, lambda: _rows(screen)[0] == "❌ Armature: not found"
        )


async def test_pushed_change_updates_the_armature_row(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(["Other"])
        assert await _wait_for(pilot, lambda: _rows(screen)[0].startswith("❌ "))
        pushes.put_nowait(["Rig"])
        assert await _wait_for(pilot, lambda: _rows(screen)[0].startswith("✅ "))


async def test_busy_keeps_the_last_result(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(["Rig"])
        assert await _wait_for(pilot, lambda: _rows(screen)[0].startswith("✅ "))
        pushes.put_nowait(None)
        await pilot.pause()
        assert _rows(screen)[0].startswith("✅ ")
        assert _status(screen) == "Live Mode"


async def test_busy_before_a_result_is_pending(tmp_path, monkeypatch):
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(None)
        assert await _wait_for(pilot, lambda: _status(screen) == "Live Mode")
        assert _rows(screen)[0] == "🟡 Armature: Rig"


async def test_dropped_connection_falls_back_to_manual_mode(tmp_path, monkeypatch):
    _fake_running(monkeypatch, True)
    pushes = _fake_bridge(monkeypatch)
    screen = _screen(tmp_path, "Rig")
    async with _Host(screen).run_test() as pilot:
        pushes.put_nowait(["Rig"])
        assert await _wait_for(pilot, lambda: _status(screen) == "Live Mode")
        pushes.put_nowait(_DROP)
        assert await _wait_for(pilot, lambda: _status(screen) == "Manual Mode")
        assert _rows(screen)[0] == "🟡 Armature: Rig"
        assert _hint(screen) == "Press r to refresh."
