"""Dashboard tests, driven through the headless `run_test()` pilot."""

from pathlib import Path

import pytest
from textual.widgets import Button, ContentSwitcher, Input, ListView, OptionList, Static

from model_meta.app import ModelMetaApp
from model_meta.config import store
from model_meta.config.settings import Settings
from model_meta.core.blender_connection import (
    BlenderConnection,
    ProbeOutcome,
    ProbeResult,
)
from model_meta.core.godot_connection import GodotConnection
from model_meta.specs import store as specs_store
from model_meta.tui.screens.dashboard import DashboardScreen
from model_meta.tui.widgets.option_list_container import OptionListContainer

# Selection and navigation wait on the pending OptionListContainer changes.
_PENDING = pytest.mark.skip(reason="pending OptionListContainer selection changes")


def _seed(cfg, models, godot, blender_exe="blender"):
    """Seed a valid config. `models` is one path or an iterable of them."""
    directories = (models,) if isinstance(models, str | Path) else tuple(models)
    store.save(
        cfg,
        Settings(
            blender_executable=blender_exe,
            blender_version="4.5.0",
            models_directories=tuple(str(d) for d in directories),
            godot_projects_root=str(godot),
        ),
    )


def _text(widget):
    return str(widget.render())


def _lists(screen):
    """Each OptionListContainer's heading and option labels, in rendered order."""
    lists = []
    for container in screen.query(OptionListContainer):
        options = container.query_one(OptionList)
        labels = [
            str(options.get_option_at_index(i).prompt)
            for i in range(options.option_count)
        ]
        lists.append((_text(container.query_one(".h2", Static)), labels))
    return lists


async def _wait_for(pilot, predicate, tries=100):
    for _ in range(tries):
        if predicate():
            return True
        await pilot.pause()
    return False


def _seeded_app(tmp_path, monkeypatch, directories=1):
    """A dashboard-booting app over a valid config with `directories` models dirs."""
    monkeypatch.setattr(GodotConnection, "find_projects", lambda self, max_depth=4: [])
    cfg = tmp_path / "config.toml"
    godot = tmp_path / "godot"
    godot.mkdir()
    models = []
    for index in range(directories):
        directory = tmp_path / f"models-{index}"
        directory.mkdir()
        models.append(directory)
    _seed(cfg, models, godot)
    return ModelMetaApp(config_path=cfg)


async def test_dashboard_shows_models_then_specs(tmp_path, monkeypatch):
    app = _seeded_app(tmp_path, monkeypatch)
    specs_store.create(tmp_path / "specs", "vehicle")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        assert _lists(app.screen) == [
            ("Model Directories", [str(tmp_path / "models-0")]),
            ("Specs", ["vehicle"]),
        ]


async def test_dashboard_lists_every_models_directory(tmp_path, monkeypatch):
    """One option per configured directory, in stored order, missing ones included."""
    monkeypatch.setattr(GodotConnection, "find_projects", lambda self, max_depth=4: [])
    cfg = tmp_path / "config.toml"
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    props = tmp_path / "props"
    characters = tmp_path / "characters"
    characters.mkdir()
    godot = tmp_path / "godot"
    godot.mkdir()
    _seed(cfg, [vehicles, props, characters], godot)

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        (models, _specs) = _lists(app.screen)
        assert models == (
            "Model Directories",
            [str(vehicles), str(props), str(characters)],
        )


async def test_dashboard_lists_specs_by_name(tmp_path, monkeypatch):
    app = _seeded_app(tmp_path, monkeypatch)
    for name in ("vehicle", "character", "prop"):
        specs_store.create(tmp_path / "specs", name)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _lists(app.screen)[-1] == ("Specs", ["character", "prop", "vehicle"])


async def test_dashboard_lists_no_specs_without_creating_the_directory(
    tmp_path, monkeypatch
):
    app = _seeded_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _lists(app.screen)[-1] == ("Specs", [])
        assert not (tmp_path / "specs").exists()


async def test_dashboard_lists_specs_without_a_valid_config(tmp_path):
    """Specs come off the config *path*, so they list even when its contents are corrupt."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is not valid toml {{{")
    specs_store.create(tmp_path / "specs", "vehicle")

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.settings is None
        assert _lists(app.screen) == [("Specs", ["vehicle"])]


async def test_dashboard_shows_setup_prompt_when_corrupt(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is not valid toml {{{")

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DashboardScreen)
        assert app.settings is None
        prompt = screen.query_one("#setup-prompt", Static)
        assert "setup" in _text(prompt).lower()
        assert [heading for heading, _labels in _lists(screen)] == ["Specs"]
        assert [node.id for node in screen.query("#setup-prompt, #config-panel")] == [
            "setup-prompt",
            "config-panel",
        ]


async def test_dashboard_refreshes_after_edit(tmp_path, monkeypatch):
    """Editing config via `--setup` updates the dashboard without a restart."""
    monkeypatch.setattr(
        BlenderConnection,
        "probe",
        lambda self, timeout=10.0: ProbeResult(ProbeOutcome.OK, version="4.5.0"),
    )
    monkeypatch.setattr(GodotConnection, "find_projects", lambda self, max_depth=4: [])
    cfg = tmp_path / "config.toml"
    models = tmp_path / "models"
    models.mkdir()
    new_models = tmp_path / "new-models"
    new_models.mkdir()
    godot = tmp_path / "godot"
    godot.mkdir()
    _seed(cfg, models, godot)

    app = ModelMetaApp(config_path=cfg, force_setup=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _lists(app.get_screen("dashboard"))[0] == (
            "Model Directories",
            [str(models)],
        )

        assert await _wait_for(
            pilot, lambda: app.screen.__class__.__name__ == "SetupWizard"
        )
        wizard = app.screen
        switcher = wizard.query_one(ContentSwitcher)

        wizard.query_one("#next", Button).press()  # Blender prefilled → advance
        assert await _wait_for(pilot, lambda: switcher.current == "step-models")

        # Edit mode pre-populates the list; swap the one entry for a new one.
        listing = wizard.query_one("#models-list", ListView)
        assert len(listing) == 1
        listing.index = 0
        wizard.query_one("#remove-models", Button).press()
        assert await _wait_for(pilot, lambda: len(listing) == 0)

        wizard.query_one("#models-dir", Input).value = str(new_models)
        wizard.query_one("#add-models", Button).press()
        assert await _wait_for(pilot, lambda: len(listing) == 1)

        wizard.query_one("#next", Button).press()
        assert await _wait_for(pilot, lambda: switcher.current == "step-godot")

        wizard.query_one("#godot-root", Input).value = str(godot)
        wizard.query_one("#next", Button).press()  # Finish
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))

        assert await _wait_for(
            pilot,
            lambda: _lists(app.screen)[0] == ("Model Directories", [str(new_models)]),
        )


async def test_dashboard_focus_chain_is_each_list_then_its_buttons(
    tmp_path, monkeypatch
):
    app = _seeded_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        chain = app.screen.focus_chain
        assert [type(widget) for widget in chain] == [
            OptionList,
            Button,
            Button,
            OptionList,
            Button,
            Button,
        ]
        assert app.screen.focused is chain[0]


async def test_dashboard_quit_still_works_from_a_focused_list(tmp_path, monkeypatch):
    """`q` must reach the app's global quit; the wizard's `q`-shadowing doesn't belong here."""
    app = _seeded_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen.focused, OptionList)
        await pilot.press("q")
        assert await _wait_for(pilot, lambda: not app.is_running)


@_PENDING
async def test_dashboard_specs_refresh_on_screen_resume():
    """A spec created on the Specs page shows on the dashboard after `escape`."""


@_PENDING
async def test_dashboard_focus_wraps_backwards():
    """`up` from the first stop wraps to the last, rather than losing focus."""


@_PENDING
async def test_dashboard_vim_keys_move_focus():
    """`j`/`k` are bound alongside the arrows."""


@_PENDING
async def test_dashboard_enter_opens_each_detail_screen():
    """Each list opens its own detail screen, `escape` comes back, and focus stays put."""


@_PENDING
async def test_dashboard_restores_focus_after_settings_change():
    """A config change recomposes the screen; the focused stop must not move."""


@_PENDING
async def test_dashboard_restores_focus_to_first_when_target_is_gone():
    """Focus falls back to the first stop rather than nowhere."""


@_PENDING
async def test_dashboard_navigation_without_a_valid_config():
    """With only Specs shown, the movement keys stay put and `enter` opens its screen."""


@_PENDING
async def test_dashboard_footer_advertises_the_navigation_keys():
    """`↑↓ Move` once, `enter Open` and `q Quit`, read from the active bindings."""


@_PENDING
async def test_dashboard_footer_keeps_open_without_a_valid_config():
    """With no valid config, Specs is still there to open, so `Open` is advertised."""
