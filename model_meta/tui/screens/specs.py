"""The Specs screen — the validation specs on disk, and the way to make one.

One focusable row per `specs/*.json`, with a fix block for the files that could
not be read. Zero specs is the normal state on a fresh install, not a problem,
so it gets a plain note and contributes no fix step.

`n` opens `NewSpecModal` and reloads if it wrote something. The modal takes no
arguments and returns a `Path`, so a second entry point to the create flow is
one `await` away rather than a reimplementation.

`enter` on a row opens `SpecDetailScreen` for that spec — pushed as an instance,
because the screen is per spec and there is no app-level "current spec" to read.

The directory listing parses JSON per file, so it runs in a `@work` worker via
`asyncio.to_thread` — never on the event loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from model_meta.specs import store
from model_meta.specs.store import SpecState
from model_meta.tui.screens.new_spec_modal import NewSpecModal
from model_meta.tui.screens.spec_detail import SpecDetailScreen
from model_meta.tui.widgets.fix_panel import FixPanel
from model_meta.tui.widgets.selectable_row import SelectableRow

if TYPE_CHECKING:
    from model_meta.app import ModelMetaApp

_LOADING = "Loading…"
_EMPTY = "No specs yet — press `n` to create one."

_MARKERS = {
    SpecState.UNREADABLE: "[yellow]⚠ unreadable[/]",
    SpecState.MISMATCHED: "[yellow]⚠ name mismatch[/]",
}

# One step per *problem* state; OK has nothing to fix, so a healthy page shows
# nothing. An empty directory is not a problem and is not listed here.
_FIX_STEPS = {
    SpecState.UNREADABLE: (
        "[b]⚠ unreadable[/] — the file is not valid JSON; open it in an editor "
        "to repair it, or delete it and create the spec again."
    ),
    SpecState.MISMATCHED: (
        "[b]⚠ name mismatch[/] — the file's `model_type` disagrees with its "
        "filename. The filename wins; edit the file to match it."
    ),
}
# Fixed order, so the block doesn't reshuffle between loads.
_STEP_ORDER = (SpecState.UNREADABLE, SpecState.MISMATCHED)


def plural_specs(count: int) -> str:
    """`1 spec` / `2 specs`. Shared with the dashboard's Specs card, so the two
    never drift into saying it differently."""
    return f"{count} spec" if count == 1 else f"{count} specs"


class SpecsScreen(Screen):
    """Detail view for the validation specs in `specs/`.

    Navigation mirrors the Models screen: rows are focusable (`SelectableRow`), `↑`/`↓`
    and `j`/`k` step through them, `enter` selects one. The rows are the only
    focus stops — the title and summary lines are plain `Static`s.

    Selecting a spec pushes `SpecDetailScreen` for it, handed the row's name and
    path, so nothing persists a "current spec".
    """

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        Binding("n", "new_spec", "New spec"),
        # One binding per key: Textual expands a comma-joined pair into one
        # binding each, drawing the footer entry twice.
        Binding("down", "app.focus_next", "Move", key_display="↑↓"),
        Binding("j", "app.focus_next", "Move", show=False),
        Binding("up", "app.focus_previous", "Move", show=False),
        Binding("k", "app.focus_previous", "Move", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        # can_focus=False keeps the scroller out of the row focus chain.
        yield VerticalScroll(
            Static("Specs", classes="section-title"),
            Static(_LOADING, id="specs-summary", classes="config-detail"),
            id="detail-panel",
            can_focus=False,
        )
        # Outside the scroller, so it survives a long list. The load fills it.
        yield FixPanel(id="fix-panel")
        yield Footer()

    def __init__(self) -> None:
        super().__init__()
        # Set by the create flow so the load hands focus to the *new* row rather
        # than row one; cleared once it has been honored.
        self._focus_after_load: Path | None = None

    def on_mount(self) -> None:
        self._load_specs()

    # -- create ------------------------------------------------------------

    def action_new_spec(self) -> None:
        self._new_spec()

    @work(exclusive=True, group="new-spec")
    async def _new_spec(self) -> None:
        """Open the modal and reload if it wrote something.

        `exclusive` means a fast double `n` cannot stack two modals — the same
        guard `app._open_setup` relies on.
        """
        path = await self.app.push_screen_wait(NewSpecModal())
        if path is None:
            return  # cancelled — nothing written, nothing to refresh
        self.notify(f"Created {path.name}")
        self._focus_after_load = path
        await self.recompose()
        self._load_specs()

    # -- workers -----------------------------------------------------------

    @work(exclusive=True, group="specs-load")
    async def _load_specs(self) -> None:
        """List the specs directory off the event loop (it parses JSON)."""
        specs_dir = cast("ModelMetaApp", self.app).specs_dir
        entries = await asyncio.to_thread(store.list_specs, specs_dir)

        try:
            panel = self.query_one("#detail-panel", VerticalScroll)
            summary = self.query_one("#specs-summary", Static)
        except NoMatches:
            return  # popped or recomposed away mid-load

        if not entries:
            # Zero specs is the normal state on a fresh install, so this is a
            # plain note rather than a count of nothing — and no fix step.
            summary.display = False
            await panel.mount(Static(_EMPTY, id="specs-empty", classes="config-detail"))
            self._show_fix_steps(set())
            return

        summary.display = True
        summary.update(plural_specs(len(entries)))
        await panel.mount_all(
            SelectableRow(entry, entry.model_type, marker=_MARKERS.get(entry.state, ""))
            for entry in entries
        )
        self._show_fix_steps({entry.state for entry in entries})
        self._focus_first_row()

    def _show_fix_steps(self, seen: set[SpecState]) -> None:
        """Show a step per problem state that occurred; none hides the panel."""
        try:
            panel = self.query_one("#fix-panel", FixPanel)
        except NoMatches:
            return  # recomposed away mid-load
        panel.steps = tuple(_FIX_STEPS[state] for state in _STEP_ORDER if state in seen)

    def _focus_first_row(self) -> None:
        """Focus the just-created spec, else the first, else leave focus alone."""
        rows = list(self.query(SelectableRow))
        if not rows:
            return
        target, self._focus_after_load = self._focus_after_load, None
        if target is not None:
            row = next((row for row in rows if row.key.path == target), None)
            if row is not None:
                row.focus()
                return
        if isinstance(self.focused, SelectableRow):
            return
        rows[0].focus()

    # -- selection ---------------------------------------------------------

    def on_selectable_row_selected(self, message: SelectableRow.Selected) -> None:
        entry = message.row.key
        self.app.push_screen(SpecDetailScreen(entry.model_type, entry.path))
