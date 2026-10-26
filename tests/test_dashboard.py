"""Dashboard config-display and section-navigation tests.

Drive the app through Textual's headless ``run_test()`` pilot (no TTY), pointing
at an injected ``config_path`` so tests never touch the real ``platformdirs``
location. Textual 8.x applies a ~50ms screen-switch delay, so we ``await
pilot.pause()`` before asserting.

The Godot scan (``find_projects``) is patched to a pure function here — the
filesystem-walk behavior is unit-tested in ``test_discovery.py``; these tests
exercise the wiring (worker → count) and the live existence markers.
"""

from pathlib import Path

import pytest
from textual.widgets import Button, ContentSwitcher, Input, ListView, Static

from model_meta.app import ModelMetaApp
from model_meta.config import store
from model_meta.config.settings import Settings
from model_meta.core.blender_connection import (
    BlenderConnection,
    ProbeOutcome,
    ProbeResult,
)
from model_meta.godot import discovery
from model_meta.specs import store as specs_store
from model_meta.tui.screens.blender_detail import BlenderDetailScreen
from model_meta.tui.screens.dashboard import DashboardScreen
from model_meta.tui.screens.godot_detail import GodotDetailScreen
from model_meta.tui.screens.models import ModelsScreen
from model_meta.tui.screens.new_spec_modal import NewSpecModal
from model_meta.tui.screens.spec_detail import SpecDetailScreen
from model_meta.tui.screens.specs import SpecsScreen
from model_meta.tui.widgets.section_card import SectionCard


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
    """The plain rendered text of a Static, markup applied/stripped."""
    return str(widget.render())


def _models_rows(screen):
    """The rendered text of every Models row (one per configured directory)."""
    return [_text(row) for row in screen.query(".models-value")]


async def _wait_for(pilot, predicate, tries=100):
    for _ in range(tries):
        if predicate():
            return True
        await pilot.pause()
    return False


async def test_dashboard_shows_four_sections_in_order(tmp_path, monkeypatch):
    """Scenario 1 — a valid config renders Blender → Specs → Models → Godot."""
    monkeypatch.setattr(discovery, "find_projects", lambda root, max_depth=4: [])
    cfg = tmp_path / "config.toml"
    models = tmp_path / "models"
    models.mkdir()
    godot = tmp_path / "godot"
    godot.mkdir()
    _seed(cfg, models, godot)

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, DashboardScreen)

        order = [section.id for section in screen.query(".section")]
        assert order == [
            "section-blender",
            "section-specs",
            "section-models",
            "section-godot",
        ]

        assert _models_rows(screen) == [f"{models}  ✓ found"]
        assert str(godot) in _text(screen.query_one("#godot-value", Static))


async def test_dashboard_marks_missing_models_dir(tmp_path, monkeypatch):
    """Scenario 2 — a deleted models directory shows a 'not found' marker and the
    app does not crash."""
    monkeypatch.setattr(discovery, "find_projects", lambda root, max_depth=4: [])
    cfg = tmp_path / "config.toml"
    missing = tmp_path / "gone"  # never created
    godot = tmp_path / "godot"
    godot.mkdir()
    _seed(cfg, missing, godot)

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        (value,) = _models_rows(app.screen)
        assert str(missing) in value
        assert "✗" in value


async def test_dashboard_lists_every_models_directory(tmp_path, monkeypatch):
    """Multi-location display — one row per configured directory, in stored
    order, each with its own independent existence indicator."""
    monkeypatch.setattr(discovery, "find_projects", lambda root, max_depth=4: [])
    cfg = tmp_path / "config.toml"
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    props = tmp_path / "props"  # never created → its own "missing" marker
    characters = tmp_path / "characters"
    characters.mkdir()
    godot = tmp_path / "godot"
    godot.mkdir()
    _seed(cfg, [vehicles, props, characters], godot)

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _models_rows(app.screen) == [
            f"{vehicles}  ✓ found",
            f"{props}  ✗ not found",
            f"{characters}  ✓ found",
        ]


async def test_dashboard_specs_card_carries_no_status_marker(tmp_path, monkeypatch):
    """Specs has no configured location to stat, so a ✓/✗ would be theater — it
    gets a muted live count instead."""
    monkeypatch.setattr(discovery, "find_projects", lambda root, max_depth=4: [])
    cfg = tmp_path / "config.toml"
    models = tmp_path / "models"
    models.mkdir()
    godot = tmp_path / "godot"
    godot.mkdir()
    _seed(cfg, models, godot)
    specs_store.create(tmp_path / "specs", "vehicle")

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        card = app.screen.query_one("#section-specs", SectionCard)
        assert _text(card.query_one(".section-title", Static)) == "Specs"
        value = card.query_one("#specs-value", Static)
        assert _text(value) == "1 spec"
        assert "✓" not in _text(value)
        assert "✗" not in _text(value)


async def test_dashboard_specs_card_counts_the_specs(tmp_path, monkeypatch):
    """A live count, so the card is not stale the moment a spec exists."""
    monkeypatch.setattr(discovery, "find_projects", lambda root, max_depth=4: [])
    cfg = tmp_path / "config.toml"
    models = tmp_path / "models"
    models.mkdir()
    godot = tmp_path / "godot"
    godot.mkdir()
    _seed(cfg, models, godot)
    for name in ("vehicle", "character", "prop"):
        specs_store.create(tmp_path / "specs", name)

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _text(app.screen.query_one("#specs-value", Static)) == "3 specs"


async def test_dashboard_specs_card_says_none_with_no_specs(tmp_path, monkeypatch):
    """An absent specs directory counts as zero, and is not created by counting."""
    monkeypatch.setattr(discovery, "find_projects", lambda root, max_depth=4: [])
    cfg = tmp_path / "config.toml"
    models = tmp_path / "models"
    models.mkdir()
    godot = tmp_path / "godot"
    godot.mkdir()
    _seed(cfg, models, godot)

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "No specs yet" in _text(app.screen.query_one("#specs-value", Static))
        assert not (tmp_path / "specs").exists()


async def test_dashboard_specs_count_refreshes_on_screen_resume(tmp_path, monkeypatch):
    """The regression this guards: creating a spec on the Specs page and pressing
    `escape` left a stale count behind, because a pop does not recompose.

    No unit test sees this path — it only exists between two screens.
    """
    monkeypatch.setattr(discovery, "find_projects", lambda root, max_depth=4: [])
    cfg = tmp_path / "config.toml"
    models = tmp_path / "models"
    models.mkdir()
    godot = tmp_path / "godot"
    godot.mkdir()
    _seed(cfg, models, godot)

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "No specs yet" in _text(app.screen.query_one("#specs-value", Static))

        await pilot.press("down", "enter")  # Blender → Specs → open
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))

        await pilot.press("n")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, NewSpecModal))
        app.screen.query_one("#spec-name", Input).value = "vehicle"
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))
        assert await _wait_for(
            pilot,
            lambda: _text(app.screen.query_one("#specs-value", Static)) == "1 spec",
        )


async def test_dashboard_specs_count_renders_without_a_valid_config(tmp_path):
    """The Specs card is the only one shown in that state, and its count comes
    off the config *path*, so it still works."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is not valid toml {{{")
    specs_store.create(tmp_path / "specs", "vehicle")

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.settings is None
        assert _text(app.screen.query_one("#specs-value", Static)) == "1 spec"


async def test_dashboard_shows_setup_prompt_when_corrupt(tmp_path):
    """Corrupt/None state — the 'run setup' prompt rather than empty section
    shells for the configured anchors. Specs reads no config, so it is the one
    section that still renders, and the prompt comes first."""
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
        assert [section.id for section in screen.query(".section")] == ["section-specs"]
        assert [node.id for node in screen.query("#setup-prompt, #config-panel")] == [
            "setup-prompt",
            "config-panel",
        ]


async def test_dashboard_godot_count_from_worker(tmp_path, monkeypatch):
    """Godot count — computed in a worker and rendered (zero is a valid 0)."""
    projects = [tmp_path / "a", tmp_path / "b"]
    monkeypatch.setattr(discovery, "find_projects", lambda root, max_depth=4: projects)
    cfg = tmp_path / "config.toml"
    models = tmp_path / "models"
    models.mkdir()
    godot = tmp_path / "godot"
    godot.mkdir()
    _seed(cfg, models, godot)

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        count = app.screen.query_one("#godot-count", Static)
        assert await _wait_for(pilot, lambda: "2" in _text(count))


async def test_dashboard_refreshes_after_edit(tmp_path, monkeypatch):
    """Scenario 3 — editing config via `s` and saving updates the dashboard's
    displayed value without an app restart."""
    monkeypatch.setattr(
        BlenderConnection,
        "probe",
        lambda self, timeout=10.0: ProbeResult(ProbeOutcome.OK, version="4.5.0"),
    )
    monkeypatch.setattr(discovery, "find_projects", lambda root, max_depth=4: [])
    cfg = tmp_path / "config.toml"
    models = tmp_path / "models"
    models.mkdir()
    new_models = tmp_path / "new-models"
    new_models.mkdir()
    godot = tmp_path / "godot"
    godot.mkdir()
    _seed(cfg, models, godot)

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert _models_rows(app.screen) == [f"{models}  ✓ found"]

        await pilot.press("s")
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
            pilot, lambda: _models_rows(app.screen) == [f"{new_models}  ✓ found"]
        )


# -- section navigation ----------------------------------------------------


def _seeded_app(tmp_path, monkeypatch, directories=1):
    """A dashboard-booting app over a valid config with `directories` models dirs."""
    monkeypatch.setattr(discovery, "find_projects", lambda root, max_depth=4: [])
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


async def test_dashboard_focuses_first_section_on_mount(tmp_path, monkeypatch):
    """Initial focus is deterministic — the first (top) section, not nothing."""
    app = _seeded_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        focused = app.screen.focused
        assert isinstance(focused, SectionCard)
        assert focused.id == "section-blender"


async def test_dashboard_focus_chain_is_exactly_the_sections(tmp_path, monkeypatch):
    """`down` steps through the four section cards and nothing else.

    Guards the navigation contract: a focusable widget sneaking onto the screen
    (a Button in a card, a scrolling wrapper) would add a stop the user has to
    arrow past to reach the next section. The wrap back to the top is what
    proves there is no fifth stop.
    """
    app = _seeded_app(tmp_path, monkeypatch, directories=3)
    async with app.run_test() as pilot:
        await pilot.pause()
        visited = [app.screen.focused]
        for _ in range(4):
            await pilot.press("down")
            visited.append(app.screen.focused)

        assert all(isinstance(widget, SectionCard) for widget in visited)
        assert [widget.id for widget in visited] == [
            "section-blender",
            "section-specs",
            "section-models",
            "section-godot",
            "section-blender",
        ]


async def test_dashboard_focus_wraps_backwards(tmp_path, monkeypatch):
    """`up` from the first section wraps to the last, rather than losing focus."""
    app = _seeded_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("up")
        assert app.screen.focused.id == "section-godot"


async def test_dashboard_vim_keys_move_focus(tmp_path, monkeypatch):
    """`j`/`k` are bound alongside the arrows."""
    app = _seeded_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("j")
        assert app.screen.focused.id == "section-specs"
        await pilot.press("k")
        assert app.screen.focused.id == "section-blender"


async def test_dashboard_enter_opens_each_sections_detail_screen(tmp_path, monkeypatch):
    """Each section opens its own detail screen, and `escape` comes back.

    Walks all four in one app so the full round trip — push, pop, and the focus
    still being where it was left — is exercised, not just a single hop.
    """
    app = _seeded_app(tmp_path, monkeypatch)
    expected = [
        ("section-blender", BlenderDetailScreen),
        ("section-specs", SpecsScreen),
        ("section-models", ModelsScreen),
        ("section-godot", GodotDetailScreen),
    ]
    async with app.run_test() as pilot:
        await pilot.pause()
        for section_id, screen_class in expected:
            assert app.screen.focused.id == section_id
            await pilot.press("enter")
            # `cls=` binds this iteration's class — a bare closure over the loop
            # variable would read whatever it held when the lambda finally ran.
            assert await _wait_for(
                pilot, lambda cls=screen_class: isinstance(app.screen, cls)
            )

            await pilot.press("escape")
            assert await _wait_for(
                pilot, lambda: isinstance(app.screen, DashboardScreen)
            )
            assert app.screen.focused.id == section_id
            await pilot.press("down")


@pytest.mark.parametrize(
    "screen",
    ["blender-detail", "specs", "models", "godot-detail", "spec-detail"],
)
async def test_setup_key_is_unbound_off_the_dashboard(tmp_path, monkeypatch, screen):
    """Setup is reachable from the dashboard only; `s` does nothing elsewhere."""
    app = _seeded_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(
            SpecDetailScreen("vehicle", tmp_path / "specs" / "vehicle.json")
            if screen == "spec-detail"
            else screen
        )
        await pilot.pause()
        pushed = app.screen
        assert "s" not in pushed.active_bindings

        await pilot.press("s")
        await pilot.pause()
        assert app.screen is pushed


async def test_dashboard_restores_focus_after_settings_change(tmp_path, monkeypatch):
    """A config change recomposes the screen — the highlight must not move.

    `recompose()` destroys every widget, so without an explicit restore the
    user's highlight silently jumps back to the top after saving an edit.
    """
    app = _seeded_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down", "down")  # focus Models
        assert app.screen.focused.id == "section-models"

        replacement = tmp_path / "replacement"
        replacement.mkdir()
        app.settings = Settings(
            blender_executable=app.settings.blender_executable,
            blender_version=app.settings.blender_version,
            models_directories=(str(replacement),),
            godot_projects_root=app.settings.godot_projects_root,
        )

        assert await _wait_for(
            pilot, lambda: _models_rows(app.screen) == [f"{replacement}  ✓ found"]
        )
        assert app.screen.focused.id == "section-models"


async def test_dashboard_restores_focus_to_first_when_section_is_gone(
    tmp_path, monkeypatch
):
    """Falling back to the first section beats leaving focus nowhere.

    Sections are fixed today, so this drives the fallback by asking for an id
    that was never rendered — the same path a removed section would take.
    """
    app = _seeded_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.screen._focus_section("section-does-not-exist")
        assert app.screen.focused.id == "section-blender"


async def test_dashboard_navigation_without_a_valid_config_acts_on_the_one_card(
    tmp_path,
):
    """A corrupt config leaves Specs as the only card, so the navigation keys
    are no longer no-ops: focus lands on it, the movement keys stay put rather
    than raising, and `enter` opens its screen."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is not valid toml {{{")

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.focused.id == "section-specs"

        await pilot.press("down", "up", "j", "k")
        await pilot.pause()
        assert app.screen.focused.id == "section-specs"

        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))


async def test_dashboard_quit_still_works_from_a_focused_section(tmp_path, monkeypatch):
    """`q` must reach the app's global quit from a focused card.

    Unlike the wizard, these screens hold no Input, so the wizard's
    `q`-shadowing must not be copied onto them.
    """
    app = _seeded_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen.focused, SectionCard)
        await pilot.press("q")
        assert await _wait_for(pilot, lambda: not app.is_running)


async def test_dashboard_footer_advertises_the_navigation_keys(tmp_path, monkeypatch):
    """The footer is the only place these keys are discoverable, so assert on
    what it draws from: the screen's active bindings, including the focused
    card's. `↑↓ Move` appears once, not as two separate rows."""
    app = _seeded_app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await pilot.pause()
        shown = [
            (binding.key_display or binding.key, binding.description)
            for _node, binding, enabled, _tooltip in app.screen.active_bindings.values()
            if binding.show and enabled
        ]
        assert ("↑↓", "Move") in shown
        assert [entry for entry in shown if entry[1] == "Move"] == [("↑↓", "Move")]
        assert ("enter", "Open") in shown
        assert ("s", "Setup") in shown
        assert ("q", "Quit") in shown


async def test_dashboard_footer_keeps_open_without_a_valid_config(tmp_path):
    """The `enter` hint tracks the thing it acts on rather than lingering as a
    dead key — and with no valid config the Specs card is still there to open,
    so `Open` is advertised."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is not valid toml {{{")

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        descriptions = {
            binding.description
            for _node, binding, enabled, _tooltip in app.screen.active_bindings.values()
            if binding.show and enabled
        }
        assert "Open" in descriptions
        assert "Setup" in descriptions
