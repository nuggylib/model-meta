from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widgets import Static

from model_meta.core.app_connection import PathState
from model_meta.specs import store as specs_store
from model_meta.tui.screens.specs import plural_specs
from model_meta.tui.templates.layout import Layout
from model_meta.tui.widgets.option_list_container import ListEntry, OptionListContainer
from model_meta.tui.widgets.section_card import SectionCard

if TYPE_CHECKING:
    from model_meta.app import ModelMetaApp
    from model_meta.config.settings import Settings

_FOUND = "[green]✓ found[/]"
_MISSING = "[red]✗ not found[/]"


class DashboardScreen(Layout):
    def __init__(self):
        super().__init__()
        self.description = (
            "Welcome to model-meta! To get started, create a spec to describe a model file (or, select a model "
            "file directly - you'll be prompted to create a spec, if needed)."
        )

    def compose_body(self) -> ComposeResult:
        settings = cast("ModelMetaApp", self.app).settings
        if settings is None:
            yield Static(
                "Setup incomplete or unreadable — run `model-meta --setup`.",
                id="setup-prompt",
            )
            yield Vertical(self._specs_section(), id="config-panel")
        else:
            yield Vertical(
                self._models_section(settings),
                self._specs_section(),
                id="config-panel",
            )

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
        self.app.push_screen(message.target)

    def _focus_section(self, section_id: str | None = None) -> None:
        cards = list(self.query(SectionCard))
        if not cards:
            return
        target = next((card for card in cards if card.id == section_id), cards[0])
        target.focus()

    def _specs_section(self) -> SectionCard:
        built: list[ListEntry] = []
        specs = specs_store.list_specs(cast("ModelMetaApp", self.app).specs_dir)
        for spec in specs:
            built.append(spec.model_type)
        return OptionListContainer(
            "Specs",
            "The list of specifications ('specs') that you've created for your model files.",
            built,
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
        built: list[ListEntry] = []
        for dir in settings.models_directories:
            built.append(dir)
        return OptionListContainer(
            "Model Directories",
            "The list of directories you've configured as sources for Blender model files.",
            built,
        )

    def _godot_section(self, settings: Settings) -> SectionCard:
        found = settings.godot.state() is PathState.OK
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
        godot = settings.godot
        if godot.state() is not PathState.OK:
            return  # inline marker already shows "not found"; leave count at "—"
        try:
            projects = await asyncio.to_thread(godot.find_projects)
            text = f"{len(projects)} Godot project(s) found"
        except OSError:
            text = "Project count unavailable."
        try:
            self.query_one("#godot-count", Static).update(text)
        except NoMatches:
            return  # recomposed away before the scan returned
