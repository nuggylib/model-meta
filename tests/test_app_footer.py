from pathlib import Path

import pytest
from textual import events

from model_meta.app import ModelMetaApp
from model_meta.config import store
from model_meta.config.settings import Settings
from model_meta.core.blender_connection import (
    BlenderConnection,
    ProbeOutcome,
    ProbeResult,
)
from model_meta.core.godot_connection import GodotConnection
from model_meta.tui.widgets.app_footer import (
    BlenderStatus,
    BlenderStatusLabel,
    blender_label,
)


class _FakeBlender:
    def probe(self, timeout=10.0):
        return ProbeResult(ProbeOutcome.OK, version="4.5.0")


def _settings(blender_executable="blender"):
    return Settings(
        blender_executable=blender_executable,
        blender_version="4.5.0",
        models_directories=(),
        godot_projects_root="",
    )


def _app(tmp_path, monkeypatch, *, detected=True, running=None):
    """`running` is a one-item list the test flips to change what `ps` reports."""
    monkeypatch.setattr(GodotConnection, "find_projects", lambda self, max_depth=4: [])
    if detected:
        monkeypatch.setattr(
            ModelMetaApp, "_find_blender", lambda self, settings: _FakeBlender()
        )
    running = running if running is not None else [False]
    calls = []

    def is_running(cls, timeout=5.0):
        calls.append(True)
        return running[0]

    monkeypatch.setattr(BlenderConnection, "is_running", classmethod(is_running))
    cfg = tmp_path / "config.toml"
    store.save(cfg, _settings())
    return ModelMetaApp(config_path=cfg), calls


def _label(app):
    return app.screen.query_one(BlenderStatusLabel).content


async def _wait_for(pilot, predicate, attempts=50):
    for _ in range(attempts):
        if predicate():
            return True
        await pilot.pause(0.02)
    return predicate()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, "[$text-muted]○ Blender[/]"),
        (BlenderStatus(version=None), "[$error]✗[/] Blender"),
        (BlenderStatus("4.5.0", running=False), "[$text-muted]●[/] Blender 4.5.0"),
        (BlenderStatus("4.5.0", running=True), "[$success]●[/] Blender 4.5.0"),
    ],
)
def test_blender_label(status, expected):
    assert blender_label(status) == expected


async def test_footer_shows_blender_not_detected(tmp_path, monkeypatch):
    app, _calls = _app(tmp_path, monkeypatch, detected=False)
    async with app.run_test() as pilot:
        assert await _wait_for(pilot, lambda: _label(app) == "[$error]✗[/] Blender")


@pytest.mark.parametrize(
    ("running", "dot"), [(False, "[$text-muted]●[/]"), (True, "[$success]●[/]")]
)
async def test_footer_shows_detected_blender(tmp_path, monkeypatch, running, dot):
    app, _calls = _app(tmp_path, monkeypatch, running=[running])
    async with app.run_test() as pilot:
        assert await _wait_for(pilot, lambda: _label(app) == f"{dot} Blender 4.5.0")


async def test_not_detected_blender_is_never_polled(tmp_path, monkeypatch):
    monkeypatch.setattr(ModelMetaApp, "BLENDER_POLL_SECONDS", 0.02)
    app, calls = _app(tmp_path, monkeypatch, detected=False)
    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        assert calls == []


async def test_poll_picks_up_blender_starting(tmp_path, monkeypatch):
    monkeypatch.setattr(ModelMetaApp, "BLENDER_POLL_SECONDS", 0.02)
    running = [False]
    app, _calls = _app(tmp_path, monkeypatch, running=running)
    async with app.run_test() as pilot:
        assert await _wait_for(pilot, lambda: "text-muted]●" in _label(app))
        running[0] = True
        assert await _wait_for(pilot, lambda: "success]●" in _label(app))


async def test_blur_pauses_polling_and_focus_checks_at_once(tmp_path, monkeypatch):
    monkeypatch.setattr(ModelMetaApp, "BLENDER_POLL_SECONDS", 0.02)
    running = [False]
    app, calls = _app(tmp_path, monkeypatch, running=running)
    async with app.run_test() as pilot:
        assert await _wait_for(pilot, lambda: app.blender_status is not None)
        app.post_message(events.AppBlur())
        await pilot.pause(0.05)
        paused_at = len(calls)
        running[0] = True
        await pilot.pause(0.2)
        assert len(calls) == paused_at
        assert "text-muted]●" in _label(app)

        app.post_message(events.AppFocus())
        assert await _wait_for(pilot, lambda: "success]●" in _label(app))


def test_configured_blender_overrides_the_standard_location(tmp_path, monkeypatch):
    monkeypatch.undo()  # the real `_find_blender`, not the conftest stub
    standard = BlenderConnection(Path("/standard/blender"))
    monkeypatch.setattr(
        BlenderConnection, "candidates", classmethod(lambda cls: [standard])
    )
    app = ModelMetaApp(config_path=tmp_path / "config.toml")

    custom = app._find_blender(_settings("/custom/blender"))
    assert custom.path == Path("/custom/blender")
    assert app._find_blender(None) == standard
    assert app._find_blender(_settings("")) == standard


def test_no_blender_found_without_a_configured_one(tmp_path, monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(BlenderConnection, "candidates", classmethod(lambda cls: []))
    app = ModelMetaApp(config_path=tmp_path / "config.toml")

    assert app._find_blender(None) is None
