from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widgets import OptionList, Static

from model_meta.core.app_connection import PathState
from model_meta.core.results import Results
from model_meta.core.spec import Spec
from model_meta.models import discovery
from model_meta.specs import store as specs_store
from model_meta.specs.store import SpecState
from model_meta.tui.screens.link_spec_modal import LinkSpecModal
from model_meta.tui.screens.model_report import ModelReportScreen
from model_meta.tui.templates.layout import Layout
from model_meta.tui.widgets.option_list_container import (
    ListEntry,
    ListOption,
    ListTab,
    OptionListContainer,
)
from model_meta.tui.widgets.section_card import SectionCard

if TYPE_CHECKING:
    from model_meta.app import ModelMetaApp
    from model_meta.config.settings import Settings


class DashboardScreen(Layout):
    def __init__(self):
        super().__init__()
        self.description = (
            "Welcome to model-meta! This is a tool intended to serve as an in-depth checklist for 3D modelers"
            " to use when preparing an asset for export into Godot. It's especially useful for games with assets"
            " that use repeating parts. When using a properly-configured spec file, model-meta helps ensure that: "
            " (1) All meshes are present, (2) All meshes are parented to the correct bone(s), (3) All meshes have"
            " the correct weights assigned to them, (4) All meshes are properly UV unwrapped, (5) TODO"
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
                self._specs_section(settings),
                id="config-panel",
            )

    def on_mount(self) -> None:
        self._scan_godot()
        self._scan_models()
        self._focus_section()
        self.watch(self.app, "settings", self._on_settings_changed, init=False)

    async def _on_settings_changed(self, _settings: Settings | None) -> None:
        focused = self.focused
        previous = focused.id if isinstance(focused, SectionCard) else None
        await self.recompose()
        self._focus_section(previous)
        self._scan_godot()
        self._scan_models()

    def on_section_card_opened(self, message: SectionCard.Opened) -> None:
        self.app.push_screen(message.target)

    def _focus_section(self, section_id: str | None = None) -> None:
        cards = list(self.query(SectionCard))
        if not cards:
            return
        target = next((card for card in cards if card.id == section_id), cards[0])
        target.focus()

    def _specs_section(self, settings: Settings | None = None) -> OptionListContainer:
        built: list[ListEntry] = []
        specs = specs_store.list_specs(cast("ModelMetaApp", self.app).specs_dir)
        for spec in specs:
            built.append(ListOption(spec.model_type, spec.model_type))
        directories = settings.models_directories if settings else ()
        # Specs aren't namespaced on disk yet, so they all belong to the first namespace.
        tabs = [
            ListTab(Path(dir).name, built if idx == 0 else ())
            for idx, dir in enumerate(directories)
        ]
        return OptionListContainer(
            "Specs",
            "The list of specifications ('specs') that you've created for your model files. You can either create a"
            " spec manually, or select a model file that is not yet associated with a spec; you will be prompted to "
            " create one any time you attempt to evaluate a model file that has not been linked to a spec.",
            tabs,
        )

    def _models_section(self, settings: Settings) -> OptionListContainer:
        tabs = [ListTab(Path(dir).name, ()) for dir in settings.models_directories]
        container = OptionListContainer(
            "Model Directories",
            "Your model directories, separated by tab. Each tab contains the full list of .blend files that were"
            " detected. To evaluate a model file, select one from the list. If a model does not have an associated"
            " spec file, yet, you will be prompted to create one.",
            tabs,
            highlight_last=True,
            delimiter="/",
        )
        container.id = "models-list"
        return container

    @work(exclusive=True, group="models-scan")
    async def _scan_models(self) -> None:
        settings = cast("ModelMetaApp", self.app).settings
        if settings is None:
            return
        for idx, directory in enumerate(settings.models_directories):
            path = Path(directory).expanduser()
            if not path.is_dir():
                continue
            try:
                found = await asyncio.to_thread(discovery.find_blend_files, path)
            except OSError:
                continue
            entries = [
                ListOption(discovery.relative_label(model, path), str(model))
                for model in found
            ]
            try:
                self.query_one("#models-list", OptionListContainer).set_entries(
                    idx, entries
                )
            except NoMatches:
                return  # recomposed away before the scan returned

    @on(OptionList.OptionSelected, "#models-list OptionList")
    def _on_model_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id is not None:
            self._open_model(Path(event.option_id))

    @work(exclusive=True, group="open-model")
    async def _open_model(self, model: Path) -> None:
        """Open the model's dashboard, linking it to a spec first if it has no results."""
        app = cast("ModelMetaApp", self.app)
        results_path = Results.path_for(app.results_dir, model)
        try:
            spec = Results.load(results_path).spec
        except FileNotFoundError:
            entries = await asyncio.to_thread(specs_store.list_specs, app.specs_dir)
            names = [
                entry.model_type for entry in entries if entry.state is SpecState.OK
            ]
            spec = await app.push_screen_wait(LinkSpecModal(model.name, names))
            if spec is None:
                return
            try:
                Results(model_file=str(model), spec=spec, path=results_path).create()
            except OSError as error:
                self.notify(
                    f"Couldn't save {results_path.name}: {error}", severity="error"
                )
                return
        except (OSError, ValueError):
            self.notify(f"{results_path.name} can't be read.", severity="error")
            return
        try:
            spec_path = Spec.path_for(app.specs_dir, spec)
        except ValueError:
            self.notify(f"{results_path.name} names an invalid spec.", severity="error")
            return
        app.push_screen(ModelReportScreen(model, spec_path, results_path))

    @work(exclusive=True, group="godot-scan")
    async def _scan_godot(self) -> None:
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
