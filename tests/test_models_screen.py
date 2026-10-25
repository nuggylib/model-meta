"""Models detail-screen tests.

Drive the app through Textual's headless ``run_test()`` pilot, pointing at an
injected ``config_path``. The scan (``find_blend_files``) is patched per test —
its filesystem behavior is unit-tested in ``test_models_discovery.py``; these
tests exercise the wiring (worker → four states → rows) and the navigation.
"""

import asyncio
import time
from pathlib import Path

from textual.widgets import Static

from model_meta.app import ModelMetaApp
from model_meta.config import store
from model_meta.config.settings import Settings
from model_meta.godot import discovery as godot_discovery
from model_meta.models import discovery as models_discovery
from model_meta.tui.screens.dashboard import DashboardScreen
from model_meta.tui.screens.models import ModelsScreen
from model_meta.tui.widgets.model_row import ModelRow


def _text(widget):
    """The plain rendered text of a Static, markup applied/stripped."""
    return str(widget.render())


async def _wait_for(pilot, predicate, tries=100):
    for _ in range(tries):
        if predicate():
            return True
        await pilot.pause()
    return False


def _app(tmp_path, monkeypatch, directories, blend_files=None):
    """An app whose config holds `directories`, with the model scan patched.

    `blend_files` maps a directory to the paths the scan returns for it; a
    directory absent from the map but present on disk scans as empty, and a
    directory mapped to an `OSError` instance raises it (the unreadable case).
    """
    monkeypatch.setattr(godot_discovery, "find_projects", lambda root, max_depth=4: [])
    results = blend_files or {}

    def fake_scan(directory, max_depth=4):
        found = results.get(Path(directory), [])
        if isinstance(found, OSError):
            raise found
        return list(found)

    monkeypatch.setattr(models_discovery, "find_blend_files", fake_scan)

    cfg = tmp_path / "config.toml"
    godot = tmp_path / "godot"
    godot.mkdir()
    store.save(
        cfg,
        Settings(
            blender_executable="blender",
            blender_version="4.5.0",
            models_directories=tuple(str(d) for d in directories),
            godot_projects_root=str(godot),
        ),
    )
    return ModelMetaApp(config_path=cfg)


async def _open_models(pilot, app):
    """Navigate the dashboard to the Models screen."""
    await pilot.pause()
    await pilot.press("down", "down")  # Blender → Specs → Models
    await pilot.press("enter")
    assert await _wait_for(pilot, lambda: isinstance(app.screen, ModelsScreen))


def _state_lines(screen):
    """The per-directory state line of every group, in rendered order."""
    return [
        _text(line)
        for line in screen.query(".models-group .config-detail")
        if line.id and line.id.startswith("models-state-")
    ]


def _row_labels(screen):
    return [_text(row) for row in screen.query(ModelRow)]


async def test_models_screen_lists_models_per_directory(tmp_path, monkeypatch):
    """The populated case — one row per model, grouped under its directory, in
    the stored directory order."""
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    characters = tmp_path / "characters"
    characters.mkdir()
    app = _app(
        tmp_path,
        monkeypatch,
        [vehicles, characters],
        {
            vehicles: [vehicles / "sedan.blend", vehicles / "truck.blend"],
            characters: [characters / "hero.blend"],
        },
    )
    async with app.run_test() as pilot:
        await _open_models(pilot, app)
        screen = app.screen

        assert await _wait_for(pilot, lambda: len(screen.query(ModelRow)) == 3)
        assert _row_labels(screen) == ["▸ sedan.blend", "▸ truck.blend", "▸ hero.blend"]

        directories = [_text(line) for line in screen.query(".models-directory")]
        assert directories == [str(vehicles), str(characters)]
        assert _state_lines(screen) == ["2 models", "1 model"]


async def test_models_screen_summary_counts_directories_and_models(
    tmp_path, monkeypatch
):
    """The header summarizes the page, pluralized properly."""
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    props = tmp_path / "props"
    props.mkdir()
    app = _app(
        tmp_path,
        monkeypatch,
        [vehicles, props],
        {vehicles: [vehicles / "sedan.blend"], props: [props / "crate.blend"]},
    )
    async with app.run_test() as pilot:
        await _open_models(pilot, app)
        summary = app.screen.query_one("#models-summary", Static)
        assert await _wait_for(
            pilot, lambda: _text(summary) == "2 directories · 2 models"
        )


async def test_models_screen_summary_is_singular_for_one_of_each(tmp_path, monkeypatch):
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    app = _app(
        tmp_path, monkeypatch, [vehicles], {vehicles: [vehicles / "sedan.blend"]}
    )
    async with app.run_test() as pilot:
        await _open_models(pilot, app)
        summary = app.screen.query_one("#models-summary", Static)
        assert await _wait_for(pilot, lambda: _text(summary) == "1 directory · 1 model")


async def test_models_screen_distinguishes_the_four_directory_states(
    tmp_path, monkeypatch
):
    """The point of the page: an *empty* directory must not read like a
    *missing* one, and neither like an *unreadable* one.

    A directory that exists but holds no models shows as a healthy "✓ found" on
    the dashboard — this screen is where that misconfiguration becomes visible.
    """
    populated = tmp_path / "populated"
    populated.mkdir()
    empty = tmp_path / "empty"
    empty.mkdir()
    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    missing = tmp_path / "missing"  # never created

    app = _app(
        tmp_path,
        monkeypatch,
        [populated, empty, unreadable, missing],
        {
            populated: [populated / "sedan.blend"],
            empty: [],
            unreadable: PermissionError(13, "Permission denied"),
        },
    )
    async with app.run_test() as pilot:
        await _open_models(pilot, app)
        screen = app.screen
        assert await _wait_for(pilot, lambda: len(screen.query(ModelRow)) == 1)

        populated_state, empty_state, unreadable_state, missing_state = _state_lines(
            screen
        )
        assert populated_state == "1 model"
        assert empty_state == "0 models"
        assert "unavailable" in unreadable_state
        assert "permission" in unreadable_state.lower()
        assert "not found" in missing_state

        # All four are distinct — the whole reason the screen exists.
        assert len({populated_state, empty_state, unreadable_state, missing_state}) == 4

        # An unreadable directory contributes no rows, and does not abort the
        # scan for the directories after it.
        assert _row_labels(screen) == ["▸ sedan.blend"]


async def test_models_screen_shows_nested_models_relative_to_their_directory(
    tmp_path, monkeypatch
):
    """A model in a subfolder keeps that context, without repeating the
    configured directory prefix on every row."""
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    app = _app(
        tmp_path,
        monkeypatch,
        [vehicles],
        {vehicles: [vehicles / "civilian" / "sedan.blend"]},
    )
    async with app.run_test() as pilot:
        await _open_models(pilot, app)
        screen = app.screen
        assert await _wait_for(pilot, lambda: len(screen.query(ModelRow)) == 1)
        assert _row_labels(screen) == [f"▸ {Path('civilian') / 'sedan.blend'}"]


def _fix_steps(screen):
    return [_text(step) for step in screen.query(".fix-step")]


async def test_models_screen_shows_a_fix_step_only_for_problems_present(
    tmp_path, monkeypatch
):
    """Workflow step 7 — each failure state present gets a step saying what to
    do, and the states that did *not* occur contribute nothing.

    An always-on reference block would eat rows the list needs, so the block
    carries only live problems.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    app = _app(tmp_path, monkeypatch, [empty])
    async with app.run_test() as pilot:
        await _open_models(pilot, app)
        screen = app.screen
        assert await _wait_for(pilot, lambda: len(_fix_steps(screen)) == 1)

        (step,) = _fix_steps(screen)
        assert "0 models" in step
        assert ".blend1" in step  # backups are ignored on purpose — say so
        # The depth cap is quoted from the scan, not hard-coded in the copy.
        assert str(models_discovery.DEFAULT_MAX_DEPTH) in step

        # The problems that did not occur are not advertised.
        joined = " ".join(_fix_steps(screen))
        assert "not found" not in joined
        assert "permissions" not in joined

        assert screen.query_one("#fix-heading", Static)
        assert screen.query_one("#fix-panel").display


async def test_models_screen_fix_block_lists_every_problem_present(
    tmp_path, monkeypatch
):
    """All three problem states at once — one step each, in a fixed order so the
    block does not reshuffle between scans."""
    empty = tmp_path / "empty"
    empty.mkdir()
    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    missing = tmp_path / "missing"  # never created

    app = _app(
        tmp_path,
        monkeypatch,
        [empty, unreadable, missing],
        {empty: [], unreadable: PermissionError(13, "Permission denied")},
    )
    async with app.run_test() as pilot:
        await _open_models(pilot, app)
        screen = app.screen
        assert await _wait_for(pilot, lambda: len(_fix_steps(screen)) == 3)

        found, unavailable, zero = _fix_steps(screen)
        assert "not found" in found
        assert "permissions" in unavailable
        assert "0 models" in zero


async def test_models_screen_hides_the_fix_block_when_all_is_well(
    tmp_path, monkeypatch
):
    """Nothing to fix means nothing docked — the list gets the full height."""
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    app = _app(
        tmp_path, monkeypatch, [vehicles], {vehicles: [vehicles / "sedan.blend"]}
    )
    async with app.run_test() as pilot:
        await _open_models(pilot, app)
        screen = app.screen
        assert await _wait_for(pilot, lambda: len(screen.query(ModelRow)) == 1)

        assert not screen.query_one("#fix-panel").display
        assert _fix_steps(screen) == []


async def test_models_screen_fix_block_stays_visible_under_a_long_list(
    tmp_path, monkeypatch
):
    """The regression this guards: the advice used to sit at the end of the
    scrolling page, so a long model list pushed it off screen entirely.

    Asserted against the composited screen — what is actually drawn — because
    region arithmetic alone called the old layout "visible" too.
    """
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    missing = tmp_path / "missing"  # never created → one docked step
    app = _app(
        tmp_path,
        monkeypatch,
        [vehicles, missing],
        {vehicles: [vehicles / f"m{i:02d}.blend" for i in range(40)]},
    )
    async with app.run_test(size=(80, 16)) as pilot:
        await _open_models(pilot, app)
        screen = app.screen
        assert await _wait_for(pilot, lambda: len(screen.query(ModelRow)) == 40)
        assert await _wait_for(pilot, lambda: len(_fix_steps(screen)) == 1)

        def drawn():
            return "\n".join(
                "".join(segment.text for segment in strip._segments)
                for strip in app.screen._compositor.render_strips()
            )

        # Visible before scrolling...
        assert "How to fix issues" in drawn()

        # ...and still visible at the bottom of a list far taller than the
        # terminal, which is the case that used to lose it.
        for _ in range(39):
            await pilot.press("down")
        await pilot.pause()
        text = drawn()
        assert "How to fix issues" in text
        assert "re-point it from the dashboard's setup" in text
        assert "m39.blend" in text  # the list did scroll
        assert "Quit" in text  # and the key footer is still there too


async def test_models_screen_navigates_and_selects_rows(tmp_path, monkeypatch):
    """Rows are the only focus stops; enter selects one and says plainly that
    nothing acts on it yet."""
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    app = _app(
        tmp_path,
        monkeypatch,
        [vehicles],
        {vehicles: [vehicles / "sedan.blend", vehicles / "truck.blend"]},
    )
    async with app.run_test() as pilot:
        await _open_models(pilot, app)
        screen = app.screen
        assert await _wait_for(pilot, lambda: len(screen.query(ModelRow)) == 2)

        # The scan focuses the first row once there is one to focus.
        assert await _wait_for(pilot, lambda: isinstance(screen.focused, ModelRow))
        assert screen.focused.path.name == "sedan.blend"

        await pilot.press("down")
        assert screen.focused.path.name == "truck.blend"
        await pilot.press("j")  # wraps, and the vim alias is bound
        assert screen.focused.path.name == "sedan.blend"
        await pilot.press("k")
        assert screen.focused.path.name == "truck.blend"

        await pilot.press("enter")
        await pilot.pause()
        notices = [str(notification.message) for notification in app._notifications]
        assert any("truck.blend" in notice for notice in notices)
        assert any("not wired up yet" in notice for notice in notices)


async def test_models_screen_scroller_is_not_a_focus_stop(tmp_path, monkeypatch):
    """The page scrolls, and `ScrollableContainer` is focusable by default — so
    the container must opt out or it becomes a stop the user arrows past."""
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    app = _app(
        tmp_path, monkeypatch, [vehicles], {vehicles: [vehicles / "sedan.blend"]}
    )
    async with app.run_test() as pilot:
        await _open_models(pilot, app)
        screen = app.screen
        assert await _wait_for(pilot, lambda: len(screen.query(ModelRow)) == 1)

        assert not screen.query_one("#detail-panel").can_focus
        # One model means one stop: `down` leaves focus exactly where it was.
        await pilot.press("down")
        assert screen.focused.path.name == "sedan.blend"


async def test_models_screen_returns_to_dashboard_on_escape(tmp_path, monkeypatch):
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    app = _app(
        tmp_path, monkeypatch, [vehicles], {vehicles: [vehicles / "sedan.blend"]}
    )
    async with app.run_test() as pilot:
        await _open_models(pilot, app)
        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))


async def test_models_screen_rescans_when_config_changes(tmp_path, monkeypatch):
    """A save while this page is open must not leave stale paths on screen."""
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    props = tmp_path / "props"
    props.mkdir()
    app = _app(
        tmp_path,
        monkeypatch,
        [vehicles],
        {
            vehicles: [vehicles / "sedan.blend"],
            props: [props / "crate.blend"],
        },
    )
    async with app.run_test() as pilot:
        await _open_models(pilot, app)
        screen = app.screen
        assert await _wait_for(pilot, lambda: _row_labels(screen) == ["▸ sedan.blend"])

        app.settings = Settings(
            blender_executable=app.settings.blender_executable,
            blender_version=app.settings.blender_version,
            models_directories=(str(props),),
            godot_projects_root=app.settings.godot_projects_root,
        )

        assert await _wait_for(
            pilot, lambda: _row_labels(app.screen) == ["▸ crate.blend"]
        )
        assert [_text(line) for line in app.screen.query(".models-directory")] == [
            str(props)
        ]


async def test_models_screen_survives_being_closed_mid_scan(tmp_path, monkeypatch):
    """Popping the screen while the worker is in flight must not crash it.

    The scan is made slow on purpose so `escape` lands before it returns.
    """
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    app = _app(tmp_path, monkeypatch, [vehicles])

    def slow_scan(directory, max_depth=4):
        time.sleep(0.2)
        return [Path(directory) / "sedan.blend"]

    monkeypatch.setattr(models_discovery, "find_blend_files", slow_scan)

    async with app.run_test() as pilot:
        await _open_models(pilot, app)
        await pilot.press("escape")
        assert await _wait_for(pilot, lambda: isinstance(app.screen, DashboardScreen))

        await asyncio.sleep(0.3)  # let the worker's thread finish and return
        await pilot.pause()
        assert app.is_running
        assert isinstance(app.screen, DashboardScreen)
