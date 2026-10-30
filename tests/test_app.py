"""Boot-routing and first-time-setup integration tests.

Drive the app through Textual's headless ``run_test()`` pilot (no TTY). Config is
always seeded/pointed through an injected ``config_path`` so tests never touch
the developer's real ``platformdirs`` directory. Textual 8.x applies a ~50ms
screen-switch delay, so we ``await pilot.pause()`` before asserting the screen.

The wizard's slow steps (``BlenderConnection.probe`` / ``find_projects``) are
patched to pure functions here — the subprocess and filesystem-walk behavior is
unit-tested in ``test_blender_connection.py`` / ``test_godot_connection.py``; these tests
exercise the wiring.
Windows-path serialization round-tripping is covered in ``test_config.py``.
"""

from textual.widgets import Button, ContentSwitcher, Input, Label, ListView

from model_meta.app import ModelMetaApp
from model_meta.config import store
from model_meta.config.settings import Settings
from model_meta.core.blender_connection import (
    BlenderConnection,
    ProbeOutcome,
    ProbeResult,
)
from model_meta.core.godot_connection import GodotConnection
from model_meta.tui.screens.dashboard import DashboardScreen


def _seed_valid_config(path):
    store.save(
        path,
        Settings(
            blender_executable="blender",
            blender_version="4.5.0",
            models_directories=(str(path.parent),),
            godot_projects_root=str(path.parent),
        ),
    )


async def _wait_for(pilot, predicate, tries=100):
    """Pump the event loop until ``predicate()`` is true (or we give up)."""
    for _ in range(tries):
        if predicate():
            return True
        await pilot.pause()
    return False


def _patch_wizard_probes(monkeypatch):
    monkeypatch.setattr(
        BlenderConnection,
        "probe",
        lambda self, timeout=10.0: ProbeResult(ProbeOutcome.OK, version="4.5.0"),
    )
    monkeypatch.setattr(GodotConnection, "find_projects", lambda self, max_depth=4: [])


async def _advance_to_models_step(pilot, wizard):
    # press(), not pilot.click: a second quick click on the same button is
    # swallowed by its 0.2s `-active` guard.
    wizard.query_one("#blender-path", Input).value = "/fake/blender"
    wizard.query_one("#next", Button).press()
    switcher = wizard.query_one(ContentSwitcher)
    return await _wait_for(pilot, lambda: switcher.current == "step-models")


def _listed_models(wizard):
    """The directory shown on each row of step 2's list, in displayed order."""
    return [
        str(item.query_one(Label).render())
        for item in wizard.query_one("#models-list", ListView).children
    ]


async def _add_models_dir(pilot, wizard, directory):
    """Type a path into step 2 and press Add, waiting for the list to grow."""
    listing = wizard.query_one("#models-list", ListView)
    before = len(listing)
    wizard.query_one("#models-dir", Input).value = str(directory)
    wizard.query_one("#add-models", Button).press()
    return await _wait_for(pilot, lambda: len(listing) == before + 1)


async def test_valid_config_boots_dashboard(tmp_path):
    """Scenario 4 — a valid config boots straight to the dashboard."""
    cfg = tmp_path / "config.toml"
    _seed_valid_config(cfg)
    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        await pilot.press("q")
    assert app.return_code == 0


async def test_v1_config_boots_dashboard_and_is_upgraded(tmp_path, monkeypatch):
    """A pre-v2 config upgrades with no visible disruption: the app boots the
    dashboard (not the wizard, not a recovery notice), the dashboard shows the
    migrated directory, and the file is v2 afterwards.

    Nothing in the config chain is mocked here — the point is that boot → load →
    migration → render works end to end on a real file.
    """
    monkeypatch.setattr(GodotConnection, "find_projects", lambda self, max_depth=4: [])
    cfg = tmp_path / "config.toml"
    models = tmp_path / "models"
    models.mkdir()
    cfg.write_text(
        "schema_version = 1\n"
        '[blender]\nexecutable = "blender"\nversion = "4.5.0"\n'
        f'[models]\ndirectory = "{models}"\n'
        f'[godot]\nprojects_root = "{tmp_path}"\n'
    )

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        assert app.settings.models_directories == (str(models),)
        rows = [str(row.render()) for row in app.screen.query(".models-value")]
        assert rows == [f"{models}  ✓ found"]

    state, settings = store.load(cfg)
    assert state == store.VALID  # upgraded on disk, so the second load is a no-op
    assert settings.models_directories == (str(models),)
    assert "schema_version = 2" in cfg.read_text()


async def test_specs_dir_is_app_level_state_in_every_config_state(tmp_path):
    """Screens read `self.app.specs_dir`, never `paths` directly. It comes off
    the config *path*, so it resolves for a corrupt config too — which is what
    lets the Specs page work without any settings at all."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is not valid toml {{{")
    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.settings is None
        assert app.specs_dir == tmp_path / "specs"
        assert app.results_dir == tmp_path / "results"


async def test_absent_config_shows_wizard(tmp_path):
    """Scenario 1 (part 1) — no config lands on the wizard, not the dashboard."""
    app = ModelMetaApp(config_path=tmp_path / "config.toml")
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.__class__.__name__ == "SetupWizard"
        await pilot.press("escape")


async def test_first_run_completes_and_writes_config(tmp_path, monkeypatch):
    """Scenario 1 (part 2) — walking all 3 steps writes a valid config, then the
    dashboard shows. Blender probe and Godot scan are patched to pure functions."""
    _patch_wizard_probes(monkeypatch)
    cfg = tmp_path / "config.toml"
    models = tmp_path / "models"
    models.mkdir()
    godot = tmp_path / "godot"
    godot.mkdir()

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = app.screen
        switcher = wizard.query_one(ContentSwitcher)

        assert await _advance_to_models_step(pilot, wizard)

        assert await _add_models_dir(pilot, wizard, models)
        wizard.query_one("#next", Button).press()
        assert await _wait_for(pilot, lambda: switcher.current == "step-godot")

        wizard.query_one("#godot-root", Input).value = str(godot)
        wizard.query_one("#next", Button).press()  # Finish
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))

    state, settings = store.load(cfg)
    assert state == store.VALID
    assert settings.blender_version == "4.5.0"
    assert settings.models_directories == (str(models),)
    assert settings.godot_projects_root == str(godot)


async def test_missing_models_dir_offers_creation(tmp_path, monkeypatch):
    """Step 2 — Adding a missing directory reveals a Create button that makes it
    and adds it to the list."""
    _patch_wizard_probes(monkeypatch)
    new_models = tmp_path / "does-not-exist-yet"

    app = ModelMetaApp(config_path=tmp_path / "config.toml")
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = app.screen
        switcher = wizard.query_one(ContentSwitcher)
        create_button = wizard.query_one("#create-models", Button)

        assert await _advance_to_models_step(pilot, wizard)

        listing = wizard.query_one("#models-list", ListView)
        assert "hidden" in create_button.classes  # not offered until we try
        wizard.query_one("#models-dir", Input).value = str(new_models)
        wizard.query_one("#add-models", Button).press()
        assert await _wait_for(pilot, lambda: "hidden" not in create_button.classes)
        assert not new_models.exists()
        assert len(listing) == 0  # the failed Add added nothing

        create_button.press()
        assert await _wait_for(pilot, lambda: len(listing) == 1)
        assert new_models.is_dir()  # created on demand

        wizard.query_one("#next", Button).press()
        assert await _wait_for(pilot, lambda: switcher.current == "step-godot")


async def test_models_step_add_dedup_remove_and_gating(tmp_path, monkeypatch):
    """Step 2's list contract, through to what gets persisted: Enter adds,
    duplicates are a no-op, a file is rejected, Remove deletes the highlighted
    entry, Next is gated on the list — blocked both when it is empty and when
    text sits unadded — and finishing writes exactly the surviving entries."""
    _patch_wizard_probes(monkeypatch)
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    props = tmp_path / "props"
    props.mkdir()
    a_file = tmp_path / "notes.txt"
    a_file.write_text("not a directory")

    cfg = tmp_path / "config.toml"
    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = app.screen
        switcher = wizard.query_one(ContentSwitcher)

        assert await _advance_to_models_step(pilot, wizard)

        models_input = wizard.query_one("#models-dir", Input)
        listing = wizard.query_one("#models-list", ListView)

        # Next on an empty list is blocked.
        wizard.query_one("#next", Button).press()
        await pilot.pause()
        assert switcher.current == "step-models"

        # Enter in the box adds (and must not advance the wizard).
        models_input.value = str(vehicles)
        models_input.focus()
        await pilot.pause()
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: len(listing) == 1)
        assert switcher.current == "step-models"
        assert models_input.value == ""  # box cleared, ready for the next path

        # A duplicate is a no-op.
        assert not await _add_models_dir(pilot, wizard, vehicles)
        assert len(listing) == 1

        # A file is rejected without touching the list.
        assert not await _add_models_dir(pilot, wizard, a_file)
        assert len(listing) == 1

        assert await _add_models_dir(pilot, wizard, props)
        assert len(listing) == 2

        # Text typed but never Added blocks Next rather than being dropped.
        models_input.value = "/typed/but/unadded"
        wizard.query_one("#next", Button).press()
        await pilot.pause()
        assert switcher.current == "step-models"
        models_input.value = ""

        # Remove takes out the highlighted entry.
        listing.index = 0
        wizard.query_one("#remove-models", Button).press()
        assert await _wait_for(pilot, lambda: len(listing) == 1)

        wizard.query_one("#next", Button).press()
        assert await _wait_for(pilot, lambda: switcher.current == "step-godot")
        assert _listed_models(wizard) == [str(props)]

        wizard.query_one("#godot-root", Input).value = str(tmp_path)
        wizard.query_one("#next", Button).press()  # Finish
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))

    state, settings = store.load(cfg)
    assert state == store.VALID
    # Only the surviving entry — not the duplicate, the file, or the unadded text.
    assert settings.models_directories == (str(props),)


async def test_removing_last_models_dir_blocks_next(tmp_path, monkeypatch):
    """Removing the last entry returns step 2 to its empty-gated state."""
    _patch_wizard_probes(monkeypatch)
    models = tmp_path / "models"
    models.mkdir()

    app = ModelMetaApp(config_path=tmp_path / "config.toml")
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = app.screen
        switcher = wizard.query_one(ContentSwitcher)

        assert await _advance_to_models_step(pilot, wizard)

        listing = wizard.query_one("#models-list", ListView)
        assert await _add_models_dir(pilot, wizard, models)

        listing.index = 0
        wizard.query_one("#remove-models", Button).press()
        assert await _wait_for(pilot, lambda: len(listing) == 0)
        assert listing.index is None

        wizard.query_one("#next", Button).press()
        await pilot.pause()
        assert switcher.current == "step-models"  # gated again
        assert _listed_models(wizard) == []


async def test_edit_mode_prepopulates_models_list_and_leaves_input_blank(tmp_path):
    """Edit mode must carry the existing locations into the list — and leave the
    box empty, so Next does not trip the unadded-text guard on a no-op edit."""
    cfg = tmp_path / "config.toml"
    store.save(
        cfg,
        Settings(
            blender_executable="blender",
            blender_version="4.5.0",
            models_directories=("/vehicles", "/props"),
            godot_projects_root=str(tmp_path),
        ),
    )
    app = ModelMetaApp(config_path=cfg, force_setup=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert await _wait_for(
            pilot, lambda: app.screen.__class__.__name__ == "SetupWizard"
        )
        wizard = app.screen
        assert _listed_models(wizard) == ["/vehicles", "/props"]
        assert wizard.query_one("#models-dir", Input).value == ""
        await pilot.press("escape")


async def test_quit_mid_wizard_writes_no_config(tmp_path):
    """Scenario 2 — cancelling mid-wizard writes no config and exits cleanly."""
    cfg = tmp_path / "config.toml"
    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.__class__.__name__ == "SetupWizard"
        await pilot.press("escape")  # cancel → first-run exits
        await pilot.pause()
    assert not cfg.exists()
    assert app.return_code == 0


async def test_corrupt_config_boots_dashboard_and_is_not_overwritten(tmp_path):
    """Scenario 3 — a corrupt config boots the dashboard (with a recovery notice)
    and is never auto-overwritten."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is not valid toml {{{")
    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
    assert cfg.read_text() == "this is not valid toml {{{"


async def test_dashboard_s_reopens_wizard_prefilled_and_cancel_preserves(tmp_path):
    """Re-run in edit mode: `s` opens the wizard pre-populated; cancel keeps the
    prior config unchanged."""
    cfg = tmp_path / "config.toml"
    _seed_valid_config(cfg)
    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, DashboardScreen)
        await pilot.press("s")
        assert await _wait_for(
            pilot, lambda: app.screen.__class__.__name__ == "SetupWizard"
        )
        assert app.screen.query_one("#blender-path", Input).value == "blender"
        await pilot.press("escape")  # cancel keeps prior config
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))

    state, settings = store.load(cfg)
    assert state == store.VALID
    assert settings.blender_executable == "blender"


async def test_typing_q_in_a_field_does_not_quit(tmp_path):
    """`q` typed into a focused path field is text input, not the quit binding."""
    app = ModelMetaApp(config_path=tmp_path / "config.toml")
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = app.screen
        assert wizard.__class__.__name__ == "SetupWizard"
        blender_input = wizard.query_one("#blender-path", Input)
        blender_input.value = ""
        blender_input.focus()
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert app.screen is wizard  # still on the wizard, app didn't quit
        assert "q" in blender_input.value


async def test_force_setup_opens_wizard_over_dashboard(tmp_path):
    """--setup opens the wizard even when a valid config exists, pre-populated."""
    cfg = tmp_path / "config.toml"
    _seed_valid_config(cfg)
    app = ModelMetaApp(config_path=cfg, force_setup=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert await _wait_for(
            pilot, lambda: app.screen.__class__.__name__ == "SetupWizard"
        )
        assert app.screen.query_one("#blender-path", Input).value == "blender"
        await pilot.press("escape")


async def test_q_on_a_focused_button_does_not_quit(tmp_path):
    """`q` while a Button (not an Input) holds focus is absorbed by the wizard's
    own binding, not routed to the app's global quit."""
    app = ModelMetaApp(config_path=tmp_path / "config.toml")
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = app.screen
        assert wizard.__class__.__name__ == "SetupWizard"
        wizard.query_one("#next", Button).focus()
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert app.screen is wizard  # still on the wizard, app didn't quit


async def test_setup_flag_with_absent_config_exits_on_cancel(tmp_path):
    """--setup with no config behaves like a first run: cancelling exits and
    writes nothing rather than stranding a config-less dashboard."""
    cfg = tmp_path / "config.toml"
    app = ModelMetaApp(config_path=cfg, force_setup=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.__class__.__name__ == "SetupWizard"
        await pilot.press("escape")
        await pilot.pause()
    assert not cfg.exists()
    assert app.return_code == 0


async def test_save_failure_still_shows_dashboard(tmp_path, monkeypatch):
    """A `store.save` OSError on the completion path is surfaced, not fatal: the
    dashboard still shows so the worker never dies mid-transition."""
    _patch_wizard_probes(monkeypatch)

    def _boom(path, settings):
        raise OSError("disk full")

    monkeypatch.setattr(store, "save", _boom)
    cfg = tmp_path / "config.toml"
    models = tmp_path / "models"
    models.mkdir()
    godot = tmp_path / "godot"
    godot.mkdir()

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        wizard = app.screen
        switcher = wizard.query_one(ContentSwitcher)

        assert await _advance_to_models_step(pilot, wizard)

        assert await _add_models_dir(pilot, wizard, models)
        wizard.query_one("#next", Button).press()
        assert await _wait_for(pilot, lambda: switcher.current == "step-godot")

        wizard.query_one("#godot-root", Input).value = str(godot)
        wizard.query_one("#next", Button).press()  # Finish → save raises
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))

    assert not cfg.exists()  # save failed, so no config was written
