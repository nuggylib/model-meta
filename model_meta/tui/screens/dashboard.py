from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.content import Content
from textual.css.query import NoMatches
from textual.widgets import Collapsible, Link, OptionList, Static, TabbedContent

from model_meta.core.app_connection import PathState
from model_meta.core.results import Results
from model_meta.core.spec import Spec
from model_meta.models import discovery
from model_meta.specs import store as specs_store
from model_meta.specs.store import SpecState
from model_meta.tui.screens.link_spec_modal import LinkSpecModal
from model_meta.tui.screens.model_report import ModelReportScreen
from model_meta.tui.templates.layout import Layout
from model_meta.tui.widgets.labeled_field import LabeledField
from model_meta.tui.widgets.option_list_container import (
    ListEntry,
    ListOption,
    ListTab,
    OptionListContainer,
    OptionsListContainerConfig,
)
from model_meta.tui.widgets.section_card import SectionCard

if TYPE_CHECKING:
    from model_meta.app import ModelMetaApp
    from model_meta.config.settings import Settings


def _linked_specs(results_dir: Path, models: Sequence[Path]) -> dict[Path, str]:
    """Models without a readable results file are left out."""
    specs: dict[Path, str] = {}
    for model in models:
        try:
            specs[model] = Results.load(Results.path_for(results_dir, model)).spec
        except (OSError, ValueError):
            continue
    return specs


class DashboardScreen(Layout):
    def __init__(self):
        super().__init__(page_title="Dashboard")
        self.description = (
            "Welcome to model-meta! This is a tool intended to serve as an in-depth checklist for 3D modelers"
            " to use when preparing an asset for export into Godot. It's especially useful for games with assets"
            " that use repeating parts."
        )
        # (total, linked) per models-directory tab index.
        self._model_counts: dict[int, tuple[int, int]] = {}

    def compose_heading(self):
        with Collapsible(collapsed=True, title="ACTIVE DEVELOPMENT NOTICE (click me)"):
            yield Static(
                Content.from_markup(
                    "[$secondary]model-meta is undergoing active development and is subject to change. This tool is being developed"
                    " in parallel with an internal independent game project and is being developed with opinions that are necessary"
                    " and useful for our needs. We hope the choices we've made are generic enough for most 3D modelers to adopt"
                    " to their own flow, but we're aware that we're only one shop. We truly appreciate our users and understand"
                    " that everyone has different needs. If you find there is a shortcoming of some kind within model-meta, please"
                    " open an issue or propose a change. We are open to collaboration![/]"
                )
            )
            yield Link(
                text="Report a bug",
                url="https://github.com/nuggylib/model-meta/issues/new?labels=bug",
                tooltip="Click to report a bug",
            )
            yield Link(
                text="Request a feature",
                url="https://github.com/nuggylib/model-meta/issues/new?labels=enhancement",
                tooltip="Click to request a feature",
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
            tabs,
            config=OptionsListContainerConfig(
                label="Specs",
                description="The list of specifications ('specs') that you've created for your model files. You can either create a"
                " spec manually, or select a model file that is not yet associated with a spec; you will be prompted to "
                " create one any time you attempt to evaluate a model file that has not been linked to a spec.",
                highlight_last=False,
                delimiter=None,
            ),
        )

    def _models_section(self, settings: Settings) -> OptionListContainer:
        tabs = [ListTab(Path(dir).name, ()) for dir in settings.models_directories]
        container = OptionListContainer(
            tabs,
            details=(
                LabeledField("Total Models", Content("—"), val_id="total-models"),
                LabeledField("Linked Models", Content("—"), val_id="linked-models"),
            ),
            config=OptionsListContainerConfig(
                label="Model Directories",
                description="Your model directories, separated by tab. Each tab contains the full list of .blend files that were"
                " detected. To evaluate a model file, select one from the list. If a model does not have an associated"
                " spec file, yet, you will be prompted to create one.",
                highlight_last=True,
                delimiter="/",
            ),
        )
        container.id = "models-list"
        return container

    @work(exclusive=True, group="models-scan")
    async def _scan_models(self) -> None:
        app = cast("ModelMetaApp", self.app)
        settings = app.settings
        if settings is None:
            return
        self._model_counts = {}
        for idx, directory in enumerate(settings.models_directories):
            path = Path(directory).expanduser()
            if not path.is_dir():
                continue
            try:
                found = await asyncio.to_thread(discovery.find_blend_files, path)
                specs = await asyncio.to_thread(_linked_specs, app.results_dir, found)
            except OSError:
                continue
            entries = [
                ListOption(
                    discovery.relative_label(model, path), str(model), specs.get(model)
                )
                for model in found
            ]
            self._model_counts[idx] = (len(found), len(specs))
            try:
                self.query_one("#models-list", OptionListContainer).set_entries(
                    idx, entries
                )
                self._show_model_counts()
            except NoMatches:
                return  # recomposed away before the scan returned

    @on(TabbedContent.TabActivated, "#models-list TabbedContent")
    def _on_models_tab_activated(self) -> None:
        try:
            self._show_model_counts()
        except NoMatches:
            return

    def _show_model_counts(self) -> None:
        """Raises `NoMatches` once unmounted."""
        idx = self.query_one("#models-list", OptionListContainer).active_index
        total, linked = (
            (str(count) for count in self._model_counts[idx])
            if idx in self._model_counts
            else ("—", "—")
        )
        self.query_one("#total-models", Static).update(total)
        self.query_one("#linked-models", Static).update(linked)

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
            self.notify(
                f"The results file for {model.name} can't be read.", severity="error"
            )
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
