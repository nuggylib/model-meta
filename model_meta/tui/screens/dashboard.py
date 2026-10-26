"""The dashboard screen — the app's landing view and navigation hub.

Displays four sections — **Blender → Specs → Models → Godot**. The three
configured anchors each carry a lightweight live existence/validity marker so
the user can tell at a glance whether a saved path has since moved or been
deleted; Specs is config-free — its location is a path convention, not an
anchor — so it renders a muted live spec count with no marker.

**Navigation:** each section is a focusable `SectionCard`. `↑`/`↓` (and `j`/`k`)
step through them, `enter` opens the focused section's detail screen. The cards
are the screen's only focus stops, so the arrow keys never land somewhere
unexpected — see `SectionCard` for how that invariant is held.

**Layering:** the screen holds no config of its own — it reads `self.app.settings`
(app-level state) and never touches TOML or spawns a subprocess. Cheap file stats
(`is_dir` / `BlenderConnection.state`) run inline; the one job that walks the filesystem —
counting Godot projects — is delegated to the `godot` category inside a Textual
`@work` worker (via `asyncio.to_thread`), exactly as the setup wizard does, so the
event loop never blocks.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, cast

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from model_meta.core.app_connection import PathState
from model_meta.godot import discovery
from model_meta.specs import store as specs_store
from model_meta.tui.screens.specs import plural_specs
from model_meta.tui.widgets.section_card import SectionCard

if TYPE_CHECKING:
    from model_meta.app import ModelMetaApp
    from model_meta.config.settings import Settings

_FOUND = "[green]✓ found[/]"
_MISSING = "[red]✗ not found[/]"


class DashboardScreen(Screen):
    """The landing view: the configured anchors plus live validity markers.

    Reads `self.app.settings` and re-renders whenever it changes (an edit via `s`
    reassigns it). When there is no valid config (`settings is None`) it shows a
    "run setup" prompt in place of the config-derived sections — but the Specs
    card reads no settings, so it renders there too and the navigation keys act
    on exactly that one card.

    The Specs count is refreshed on `ScreenResume` as well as on compose: a spec
    created on the Specs page lands while this screen is suspended, and a pop
    does not recompose.

    Future: live validation results driven by a Blender-polling worker, filling
    in the detail screens the sections already open.
    """

    BINDINGS = [
        ("s", "app.open_setup", "Setup"),
        # One binding per key: Textual expands a comma-joined pair into one
        # binding each, drawing the footer entry twice. Only one is shown.
        Binding("down", "app.focus_next", "Move", key_display="↑↓"),
        Binding("j", "app.focus_next", "Move", show=False),
        Binding("up", "app.focus_previous", "Move", show=False),
        Binding("k", "app.focus_previous", "Move", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        settings = cast("ModelMetaApp", self.app).settings
        if settings is None:
            yield Static(
                "Setup incomplete or unreadable — press 's' to run setup.",
                id="setup-prompt",
            )
            yield Vertical(self._specs_section(), id="config-panel")
        else:
            yield Vertical(
                self._blender_section(settings),
                self._specs_section(),
                self._models_section(settings),
                self._godot_section(settings),
                id="config-panel",
            )
        yield Footer()

    def on_mount(self) -> None:
        # Kick off the (filesystem-walking) Godot count once the sections exist,
        # and re-render + re-scan whenever the app's config is reassigned. `init`
        # is off so this doesn't fire redundantly against the value compose already
        # read.
        self._scan_godot()
        self._focus_section()
        self.watch(self.app, "settings", self._on_settings_changed, init=False)

    def on_screen_resume(self) -> None:
        """Refresh the spec count — a spec created on the Specs page lands while
        this screen is suspended, and a pop does not recompose.

        Targeted at `#specs-value` only: a full `recompose` would re-trigger the
        Godot filesystem scan on every `escape`.
        """
        self._update_specs_count()

    async def _on_settings_changed(self, _settings: Settings | None) -> None:
        # `recompose` destroys every widget, the focused card included, so note
        # which section held focus and hand it back afterwards — otherwise saving
        # an edit silently moves the user's highlight.
        focused = self.focused
        previous = focused.id if isinstance(focused, SectionCard) else None
        await self.recompose()
        self._focus_section(previous)
        self._scan_godot()

    # -- navigation --------------------------------------------------------

    def on_section_card_opened(self, message: SectionCard.Opened) -> None:
        """A card was activated — push the detail screen it stands for.

        Navigation is the hub's job, not the card's; the card only names its
        target. Screens are pushed by name, per the `SCREENS` convention.
        """
        self.app.push_screen(message.target)

    def _focus_section(self, section_id: str | None = None) -> None:
        """Focus `section_id`, falling back to the first section.

        The fallback covers both the initial mount and a recompose that dropped
        the previously focused section (a config edit can remove one).
        """
        cards = list(self.query(SectionCard))
        if not cards:
            return
        target = next((card for card in cards if card.id == section_id), cards[0])
        target.focus()

    # -- sections ----------------------------------------------------------

    def _blender_section(self, settings: Settings) -> SectionCard:
        state = settings.blender.state()
        if state is PathState.OK:
            marker = "[green]✓ executable[/]"
        elif state is PathState.INVALID:
            marker = "[yellow]⚠ present, not executable[/]"
        else:
            marker = _MISSING
        version = settings.blender_version or "unknown version"
        return SectionCard(
            Static("Blender", classes="section-title"),
            Static(
                f"{escape(settings.blender_executable)}  {marker}",
                id="blender-value",
                classes="config-value",
            ),
            Static(f"Recorded version: {escape(version)}", classes="config-detail"),
            target="blender-detail",
            id="section-blender",
            classes="section",
        )

    def _specs_section(self) -> SectionCard:
        # No `settings` argument and no ✓/✗ marker: the specs location is a path
        # convention, not a configured anchor, so there is nothing to validate.
        return SectionCard(
            Static("Specs", classes="section-title"),
            Static(self._specs_count(), id="specs-value", classes="config-detail"),
            target="specs",
            id="section-specs",
            classes="section",
        )

    def _specs_count(self) -> str:
        """`No specs yet` / `N specs`.

        A single-directory glob with no parsing — the same class of work as the
        `is_dir()` the other cards do inline, so it needs no worker.
        """
        count = specs_store.count(cast("ModelMetaApp", self.app).specs_dir)
        if not count:
            return "No specs yet — open to create one."
        return plural_specs(count)

    def _update_specs_count(self) -> None:
        try:
            self.query_one("#specs-value", Static).update(self._specs_count())
        except NoMatches:
            return  # recomposed away

    def _models_section(self, settings: Settings) -> SectionCard:
        # One row per configured location, in stored order (the order the user
        # added them in the wizard). The schema and the wizard both enforce at
        # least one, so there is no empty-list state to render.
        rows = [
            Static(
                f"{escape(directory)}  "
                f"{_FOUND if Path(directory).expanduser().is_dir() else _MISSING}",
                classes="config-value models-value",
            )
            for directory in settings.models_directories
        ]
        return SectionCard(
            Static("Models", classes="section-title"),
            *rows,
            target="models",
            id="section-models",
            classes="section",
        )

    def _godot_section(self, settings: Settings) -> SectionCard:
        found = Path(settings.godot_projects_root).expanduser().is_dir()
        # The count is filled in by `_scan_godot` (it walks the fs); until then show
        # a placeholder, or a dash when the root is missing and there is nothing to
        # scan.
        count = "Scanning…" if found else "—"
        return SectionCard(
            Static("Godot", classes="section-title"),
            Static(
                f"{escape(settings.godot_projects_root)}  "
                f"{_FOUND if found else _MISSING}",
                id="godot-value",
                classes="config-value",
            ),
            Static(count, id="godot-count", classes="config-detail"),
            target="godot-detail",
            id="section-godot",
            classes="section",
        )

    # -- workers -----------------------------------------------------------

    @work(exclusive=True, group="godot-scan")
    async def _scan_godot(self) -> None:
        """Count Godot projects under the configured root, off the event loop.

        The scan walks the filesystem, so it runs in a thread (like the wizard's).
        A missing root needs no scan (the inline marker already says so); zero
        projects is a valid `0`, and any failure degrades to "count unavailable"
        rather than crashing the screen.
        """
        settings = cast("ModelMetaApp", self.app).settings
        if settings is None:
            return
        root = Path(settings.godot_projects_root).expanduser()
        if not root.is_dir():
            return  # inline marker already shows "not found"; leave count at "—"
        try:
            projects = await asyncio.to_thread(discovery.find_projects, root)
            text = f"{len(projects)} Godot project(s) found"
        except OSError:
            text = "Project count unavailable."
        try:
            self.query_one("#godot-count", Static).update(text)
        except NoMatches:
            return  # recomposed away before the scan returned
