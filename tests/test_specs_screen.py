"""Specs screen tests.

Drive the app through Textual's headless ``run_test()`` pilot, pointing at an
injected ``config_path`` — which is also what fixes ``app.specs_dir``, since the
specs directory is derived from the config *path*. The store's filesystem
behavior is unit-tested in ``test_specs_store.py``; these tests exercise the
wiring (worker → rows → fix steps) and the navigation.
"""

import asyncio
import json
import time

from textual.widgets import Button, Input, Static

from model_meta.app import ModelMetaApp
from model_meta.config import store as config_store
from model_meta.config.settings import Settings
from model_meta.core.godot_connection import GodotConnection
from model_meta.specs import schema
from model_meta.specs import store as specs_store
from model_meta.tui.screens.dashboard import DashboardScreen
from model_meta.tui.screens.new_spec_modal import NewSpecModal
from model_meta.tui.screens.spec_detail import SpecDetailScreen
from model_meta.tui.screens.specs import SpecsScreen
from model_meta.tui.widgets.spec_row import SpecRow


def _text(widget):
    """The plain rendered text of a Static, markup applied/stripped."""
    return str(widget.render())


async def _wait_for(pilot, predicate, tries=100):
    for _ in range(tries):
        if predicate():
            return True
        await pilot.pause()
    return False


async def _open_specs(pilot, app):
    """Navigate the dashboard to the Specs screen.

    Driven through the pilot rather than `app.push_screen`: pushing from the
    test's own thread races the new `Header`'s mount.
    """
    await pilot.pause()
    await pilot.press("down")  # Blender → Specs
    await pilot.press("enter")
    assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))


def _app(tmp_path, monkeypatch, specs=(), broken=()):
    """A dashboard-booting app over a valid config, with `specs` on disk.

    `broken` names spec files hand-written as raw text (the unreadable cases).
    """
    monkeypatch.setattr(GodotConnection, "find_projects", lambda self, max_depth=4: [])
    cfg = tmp_path / "config.toml"
    models = tmp_path / "models"
    models.mkdir()
    godot = tmp_path / "godot"
    godot.mkdir()
    config_store.save(
        cfg,
        Settings(
            blender_executable="blender",
            blender_version="4.5.0",
            models_directories=(str(models),),
            godot_projects_root=str(godot),
        ),
    )
    for name in specs:
        specs_store.create(tmp_path / "specs", name)
    for name, payload in broken:
        directory = tmp_path / "specs"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.json").write_text(payload, encoding="utf-8")
    return ModelMetaApp(config_path=cfg)


def _row_labels(screen):
    return [_text(row) for row in screen.query(SpecRow)]


def _fix_steps(screen):
    return [_text(step) for step in screen.query(".fix-step")]


async def test_specs_screen_lists_the_specs_on_disk(tmp_path, monkeypatch):
    """One focusable row per spec, sorted by name, with a count."""
    app = _app(tmp_path, monkeypatch, specs=("vehicle", "character", "prop"))
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        screen = app.screen

        assert await _wait_for(pilot, lambda: len(screen.query(SpecRow)) == 3)
        assert _row_labels(screen) == ["▸ character", "▸ prop", "▸ vehicle"]
        assert _text(screen.query_one("#specs-summary", Static)) == "3 specs"
        assert _fix_steps(screen) == []
        assert not screen.query("#specs-empty")


async def test_specs_screen_counts_one_spec_in_the_singular(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        summary = app.screen.query_one("#specs-summary", Static)
        assert await _wait_for(pilot, lambda: _text(summary) == "1 spec")


async def test_specs_screen_empty_state_is_a_note_not_a_problem(tmp_path, monkeypatch):
    """Zero specs is the normal state on a fresh install, so it gets a plain
    note and contributes no fix step — unlike a models directory with none."""
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        screen = app.screen

        assert await _wait_for(pilot, lambda: bool(screen.query("#specs-empty")))
        note = _text(screen.query_one("#specs-empty", Static))
        assert "No specs yet" in note
        assert "n" in note  # says how to make one
        assert not screen.query(SpecRow)
        assert _fix_steps(screen) == []
        assert not screen.query_one("#fix-panel").display
        # Read-only: listing an absent directory must not create it.
        assert not (tmp_path / "specs").exists()


async def test_specs_screen_marks_an_unreadable_spec_and_keeps_the_good_ones(
    tmp_path, monkeypatch
):
    """One malformed file never hides the rest — it is marked and gets a step."""
    app = _app(
        tmp_path,
        monkeypatch,
        specs=("vehicle", "character"),
        broken=(("broken", "{not json"),),
    )
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        screen = app.screen

        assert await _wait_for(pilot, lambda: len(screen.query(SpecRow)) == 3)
        labels = _row_labels(screen)
        assert labels[0].startswith("▸ broken")
        assert "unreadable" in labels[0]
        assert labels[1:] == ["▸ character", "▸ vehicle"]

        (step,) = _fix_steps(screen)
        assert "unreadable" in step
        assert "JSON" in step
        # The good rows are still focus stops.
        assert all(row.can_focus for row in screen.query(SpecRow))


async def test_specs_screen_marks_a_name_mismatch(tmp_path, monkeypatch):
    """The stem is the identity, so a file disagreeing with it is surfaced."""
    app = _app(tmp_path, monkeypatch)
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "vehicle.json").write_text(
        json.dumps(schema.skeleton("spaceship")), encoding="utf-8"
    )
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        screen = app.screen

        assert await _wait_for(pilot, lambda: len(screen.query(SpecRow)) == 1)
        (label,) = _row_labels(screen)
        assert "mismatch" in label

        (step,) = _fix_steps(screen)
        assert "mismatch" in step
        assert "filename wins" in step


async def test_specs_screen_fix_block_lists_both_problems_present(
    tmp_path, monkeypatch
):
    """Both problem states at once — one step each, in a fixed order."""
    app = _app(tmp_path, monkeypatch, broken=(("broken", "{nope"),))
    specs = tmp_path / "specs"
    (specs / "vehicle.json").write_text(
        json.dumps(schema.skeleton("spaceship")), encoding="utf-8"
    )
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        screen = app.screen

        assert await _wait_for(pilot, lambda: len(_fix_steps(screen)) == 2)
        unreadable, mismatched = _fix_steps(screen)
        assert "unreadable" in unreadable
        assert "mismatch" in mismatched


async def test_specs_screen_escapes_markup_in_a_spec_name(tmp_path, monkeypatch):
    """A name is user-supplied text rendered through Rich markup — `mech[v2]`
    would otherwise render with a chunk missing."""
    app = _app(tmp_path, monkeypatch)
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "mech[v2].json").write_text(
        json.dumps(schema.skeleton("mech[v2]")), encoding="utf-8"
    )
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        screen = app.screen
        assert await _wait_for(pilot, lambda: len(screen.query(SpecRow)) == 1)
        assert _row_labels(screen) == ["▸ mech[v2]"]


async def test_specs_screen_focus_chain_is_exactly_the_rows(tmp_path, monkeypatch):
    """Rows are the only focus stops — the scroller must opt out, or it becomes
    a stop the user arrows past."""
    app = _app(tmp_path, monkeypatch, specs=("vehicle", "character"))
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        screen = app.screen
        assert await _wait_for(pilot, lambda: len(screen.query(SpecRow)) == 2)

        assert not screen.query_one("#detail-panel").can_focus
        assert await _wait_for(pilot, lambda: isinstance(screen.focused, SpecRow))
        assert screen.focused.model_type == "character"

        await pilot.press("down")
        assert screen.focused.model_type == "vehicle"
        await pilot.press("j")  # wraps, and the vim alias is bound
        assert screen.focused.model_type == "character"
        await pilot.press("k")
        assert screen.focused.model_type == "vehicle"


async def test_specs_screen_enter_on_a_row_opens_its_detail_screen(
    tmp_path, monkeypatch
):
    """The seam pushes the spec's detail screen and still persists nothing."""
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        screen = app.screen
        assert await _wait_for(pilot, lambda: isinstance(screen.focused, SpecRow))

        before = config_store.load(app._config_path)
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecDetailScreen))

        assert app.screen.model_type == "vehicle"
        assert config_store.load(app._config_path) == before


# -- the create flow -------------------------------------------------------


async def _open_modal(pilot, app):
    """Press `n` and wait for the modal to take over."""
    await pilot.press("n")
    assert await _wait_for(pilot, lambda: isinstance(app.screen, NewSpecModal))


def _status(app):
    return _text(app.screen.query_one("#spec-status", Static))


async def test_specs_screen_footer_advertises_the_new_spec_key(tmp_path, monkeypatch):
    """The footer is the only place `n` is discoverable, so assert on what it
    draws from: the screen's active bindings."""
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        shown = [
            (binding.key_display or binding.key, binding.description)
            for _node, binding, enabled, _tooltip in app.screen.active_bindings.values()
            if binding.show and enabled
        ]
        assert ("n", "New spec") in shown
        assert ("escape", "Back") in shown
        assert ("s", "Setup") not in shown
        assert ("q", "Quit") in shown
        # The movement keys are bound but not advertised: the `VerticalScroll`
        # ancestor's own hidden scroll bindings shadow the screen's shown `Move`
        # entry. Same on `ModelsScreen` — a scroller page trades the footer hint
        # for the scrolling, and the keys themselves still move focus (below).
        assert "Move" not in [description for _key, description in shown]
        assert {"down", "j", "up", "k"} <= set(app.screen.active_bindings)


async def test_new_spec_modal_footer_replaces_the_pages(tmp_path, monkeypatch):
    """A `ModalScreen` is transparent, so without a Footer of its own the page
    underneath keeps painting *its* bindings — advertising `n New spec` and
    `q Quit` while neither does anything. Asserted against the composited
    screen, because that is where the wrong footer was actually visible.
    """
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    async with app.run_test(size=(80, 24)) as pilot:
        await _open_specs(pilot, app)
        await _open_modal(pilot, app)

        drawn = "\n".join(
            "".join(segment.text for segment in strip._segments)
            for strip in app.screen._compositor.render_strips()
        )
        assert "Cancel" in drawn
        assert "New spec" not in drawn.splitlines()[-1]
        assert "Quit" not in drawn.splitlines()[-1]


async def test_new_spec_creates_the_file_and_focuses_its_row(tmp_path, monkeypatch):
    """The whole flow: `n` → type → enter → file on disk, modal closed, the new
    row present **and focused** rather than focus snapping back to row one."""
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        assert await _wait_for(pilot, lambda: len(app.screen.query(SpecRow)) == 1)

        await _open_modal(pilot, app)
        app.screen.query_one("#spec-name", Input).value = "Space Ship"
        await pilot.pause()
        # The normalization is visible before committing to it.
        assert "specs/space-ship.json" in _text(
            app.screen.query_one("#spec-preview", Static)
        )

        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))

        created = tmp_path / "specs" / "space-ship.json"
        assert json.loads(created.read_text()) == schema.skeleton("space-ship")

        screen = app.screen
        assert await _wait_for(pilot, lambda: len(screen.query(SpecRow)) == 2)
        assert _row_labels(screen) == ["▸ space-ship", "▸ vehicle"]
        assert await _wait_for(
            pilot,
            lambda: (
                isinstance(screen.focused, SpecRow)
                and screen.focused.model_type == "space-ship"
            ),
        )
        notices = [str(notification.message) for notification in app._notifications]
        assert any("Created space-ship.json" in notice for notice in notices)


async def test_new_spec_creates_the_specs_dir_on_first_use(tmp_path, monkeypatch):
    """A fresh install has no `specs/` until the first create makes it."""
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        assert await _wait_for(pilot, lambda: bool(app.screen.query("#specs-empty")))
        assert not (tmp_path / "specs").exists()

        await _open_modal(pilot, app)
        app.screen.query_one("#spec-name", Input).value = "vehicle"
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))

        assert (tmp_path / "specs" / "vehicle.json").is_file()
        screen = app.screen
        assert await _wait_for(pilot, lambda: _row_labels(screen) == ["▸ vehicle"])
        assert not screen.query("#specs-empty")


async def test_new_spec_rejects_a_duplicate_name_without_touching_the_file(
    tmp_path, monkeypatch
):
    """Never overwrite an existing spec. The modal stays up with a message and
    the Input keeps its text, so the user can just rename."""
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    existing = tmp_path / "specs" / "vehicle.json"
    before = existing.read_bytes()

    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        await _open_modal(pilot, app)

        name = app.screen.query_one("#spec-name", Input)
        name.value = "Vehicle"  # normalizes onto the existing one
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, NewSpecModal)
        assert "already exists" in _status(app)
        assert "vehicle" in _status(app)  # quotes the *normalized* name
        assert name.value == "Vehicle"
        assert existing.read_bytes() == before
        assert len(list((tmp_path / "specs").glob("*.json"))) == 1


async def test_new_spec_rejects_an_invalid_name_and_writes_nothing(
    tmp_path, monkeypatch
):
    """Each rule gets its own message, and nothing reaches the filesystem."""
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        await _open_modal(pilot, app)
        name = app.screen.query_one("#spec-name", Input)

        for value, expected in (
            ("", "Enter a name"),
            ("../escape", "letters, numbers"),
            ("my.spec", "letters, numbers"),
            ("con", "reserved"),
            ("v" * 65, "64 characters"),
        ):
            name.value = value
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, NewSpecModal), value
            assert expected in _status(app), value

        assert not (tmp_path / "specs").exists()


async def test_new_spec_clears_a_stale_error_as_the_user_retypes(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        await _open_modal(pilot, app)

        name = app.screen.query_one("#spec-name", Input)
        name.value = "my.spec"
        await pilot.press("enter")
        await pilot.pause()
        assert _status(app)

        name.value = "myspec"
        await pilot.pause()
        assert _status(app) == ""


async def test_new_spec_surfaces_an_unwritable_specs_dir(tmp_path, monkeypatch):
    """An OSError keeps the modal up with the reason rather than crashing it."""
    app = _app(tmp_path, monkeypatch)

    def _boom(specs_dir, model_type):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(specs_store, "create", _boom)

    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        await _open_modal(pilot, app)
        app.screen.query_one("#spec-name", Input).value = "vehicle"
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, NewSpecModal)
        assert "Could not create spec" in _status(app)
        assert "Permission denied" in _status(app)


async def test_new_spec_escape_cancels_and_writes_nothing(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        await _open_modal(pilot, app)
        app.screen.query_one("#spec-name", Input).value = "vehicle"

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))
        assert not (tmp_path / "specs").exists()
        assert not app.screen.query(SpecRow)


async def test_new_spec_cancel_button_writes_nothing(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        await _open_modal(pilot, app)
        app.screen.query_one("#cancel-spec", Button).press()

        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))
        assert not (tmp_path / "specs").exists()


async def test_new_spec_create_button_creates(tmp_path, monkeypatch):
    """The button and `enter` are the same path, so both are covered."""
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        await _open_modal(pilot, app)
        app.screen.query_one("#spec-name", Input).value = "vehicle"
        app.screen.query_one("#create-spec", Button).press()

        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))
        assert (tmp_path / "specs" / "vehicle.json").is_file()


async def test_new_spec_q_does_not_quit_the_app(tmp_path, monkeypatch):
    """`q` while a Button holds focus must be absorbed by the modal — but `q` on
    the page itself still quits."""
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        await _open_modal(pilot, app)

        modal = app.screen
        modal.query_one("#create-spec", Button).focus()
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert app.screen is modal
        assert app.is_running

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))
        await pilot.press("q")
        assert await _wait_for(pilot, lambda: not app.is_running)


async def test_new_spec_double_n_does_not_stack_two_modals(tmp_path, monkeypatch):
    """`exclusive=True` on the worker is what guards this."""
    app = _app(tmp_path, monkeypatch)
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        await pilot.press("n")
        await pilot.press("n")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, NewSpecModal))

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))


async def test_new_spec_works_without_a_valid_config(tmp_path):
    """`specs_dir` comes from the config *path*, so the create flow works with
    `settings is None`."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is not valid toml {{{")

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.settings is None
        await pilot.press("enter")  # Specs is the only card there is
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))

        await _open_modal(pilot, app)
        app.screen.query_one("#spec-name", Input).value = "vehicle"
        await pilot.press("enter")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))

        assert (tmp_path / "specs" / "vehicle.json").is_file()
        screen = app.screen
        assert await _wait_for(pilot, lambda: _row_labels(screen) == ["▸ vehicle"])


async def test_specs_screen_escape_returns_to_the_dashboard(tmp_path, monkeypatch):
    """`escape` pops, so the screen is not a one-way trip."""
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)

        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))


async def test_specs_screen_lists_without_a_valid_config(tmp_path):
    """It reads a path derived from the config *path*, not its contents — so it
    lists normally with `settings is None`."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is not valid toml {{{")
    specs_store.create(tmp_path / "specs", "vehicle")

    app = ModelMetaApp(config_path=cfg)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.settings is None

        await pilot.press("enter")  # Specs is the only card there is
        assert await _wait_for(pilot, lambda: isinstance(app.screen, SpecsScreen))
        screen = app.screen
        assert await _wait_for(pilot, lambda: _row_labels(screen) == ["▸ vehicle"])


async def test_specs_screen_quit_still_works(tmp_path, monkeypatch):
    """`q` must reach the app's global quit from the screen."""
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))
    async with app.run_test() as pilot:
        await _open_specs(pilot, app)

        await pilot.press("q")
        assert await _wait_for(pilot, lambda: not app.is_running)


async def test_specs_screen_survives_being_closed_mid_load(tmp_path, monkeypatch):
    """Popping the screen while the worker is in flight must not crash it."""
    app = _app(tmp_path, monkeypatch, specs=("vehicle",))

    def slow_list(specs_dir):
        time.sleep(0.2)
        return []

    monkeypatch.setattr(specs_store, "list_specs", slow_list)

    async with app.run_test() as pilot:
        await _open_specs(pilot, app)
        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))

        await asyncio.sleep(0.3)  # let the worker's thread finish and return
        await pilot.pause()
        assert app.is_running
        assert isinstance(app.screen, DashboardScreen)
