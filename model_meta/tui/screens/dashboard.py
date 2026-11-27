from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
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
from model_meta.tui.screens.confirm_modal import ConfirmModal
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
    specs: dict[Path, str] = {}
    for model in models:
        try:
            spec = Results.load(Results.path_for(results_dir, model)).spec
        except (OSError, ValueError):
            continue
        if spec is not None:
            specs[model] = spec
    return specs


_RELINK_REVERSIBLE = (
    "This operation is reversible for this model. You can re-link your model file to"
    " the same spec and the results will be regenerated exactly the same."
)
_KEPT_OVERRIDES = (
    "Model-specific settings aren't cleared, so this model keeps its texture map"
    " overrides with any spec you link next. Review them below:"
)


def _clear_link_details(results: Results) -> Static:
    lines = [_RELINK_REVERSIBLE]
    if results.texture_map_overrides:
        lines.extend(["", _KEPT_OVERRIDES, "", "• texture_map_overrides"])
        lines.extend(
            f"  • {role}: {', '.join(override.name for override in overrides)}"
            for role, overrides in results.texture_map_overrides.items()
        )
    return Static(Content.from_markup("[$accent]$text[/]", text="\n".join(lines)))


class DashboardScreen(Layout):
    BINDINGS = [Binding("x", "clear_link", "Clear link")]

    def __init__(self):
        super().__init__(page_title="Dashboard")
        self.description = (
            "Welcome to model-meta! This is a tool intended to serve as an in-depth checklist for 3D modelers"
            " to use when preparing an asset for export into Godot. It's especially useful for games with assets"
            " that use repeating parts."
        )
        # (total, linked) per models-directory tab index.
        self._model_counts: dict[int, tuple[int, int]] = {}
        self._linked_models: set[Path] = set()

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
        self._linked_models = set()
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
            self._linked_models.update(specs)
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
        self.query_one("#total-models", Static).update(
            Content.from_markup("[$secondary]$total[/]", total=total)
        )
        self.query_one("#linked-models", Static).update(
            Content.from_markup("[$secondary]$linked[/]", linked=linked)
        )

    @on(OptionList.OptionSelected, "#models-list OptionList")
    def _on_model_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id is not None:
            self._open_model(Path(event.option_id))

    @on(OptionList.OptionHighlighted, "#models-list OptionList")
    def _on_model_highlighted(self) -> None:
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        if action == "clear_link":
            return self._focused_model() in self._linked_models
        return super().check_action(action, parameters)

    def action_clear_link(self) -> None:
        model = self._focused_model()
        if model is not None:
            self._confirm_clear_link(model)

    @work(exclusive=True, group="clear-link")
    async def _confirm_clear_link(self, model: Path) -> None:
        app = cast("ModelMetaApp", self.app)
        results_path = Results.path_for(app.results_dir, model)
        try:
            results = Results.load(results_path)
        except (OSError, ValueError):
            self.notify(
                f"The results file for {model.name} can't be read.", severity="error"
            )
            return
        question = Content.from_markup(
            "[b]Clear spec for [$primary]$model[/]?[/b]", model=model.name
        )
        confirmed = await app.push_screen_wait(
            ConfirmModal(question, details=(_clear_link_details(results),))
        )
        if not confirmed:
            return
        try:
            Results.load(results_path).unlinked().save()
        except (OSError, ValueError) as error:
            self.notify(
                f"Couldn't clear {results_path.name}: {error}", severity="error"
            )
            return
        self._scan_models()

    def _focused_model(self) -> Path | None:
        focused = self.focused
        if not isinstance(focused, OptionList) or focused.highlighted is None:
            return None
        if focused not in self.query("#models-list OptionList"):
            return None
        option_id = focused.get_option_at_index(focused.highlighted).id
        return Path(option_id) if option_id is not None else None

    @work(exclusive=True, group="open-model")
    async def _open_model(self, model: Path) -> None:
        """Open the model's dashboard, linking it to a spec first if it has no results."""
        app = cast("ModelMetaApp", self.app)
        results_path = Results.path_for(app.results_dir, model)
        try:
            spec = Results.load(results_path).spec
            exists = True
        except FileNotFoundError:
            spec = None
            exists = False
        except (OSError, ValueError):
            self.notify(
                f"The results file for {model.name} can't be read.", severity="error"
            )
            return
        if spec is None:
            entries = await asyncio.to_thread(specs_store.list_specs, app.specs_dir)
            names = [
                entry.model_type for entry in entries if entry.state is SpecState.OK
            ]
            spec = await app.push_screen_wait(LinkSpecModal(model.name, names))
            if spec is None:
                return
            try:
                if exists:
                    results = Results.load(results_path)
                    results.spec = spec
                    results.save()
                else:
                    Results(
                        model_file=str(model), spec=spec, path=results_path
                    ).create()
            except (OSError, ValueError) as error:
                self.notify(
                    f"Couldn't save {results_path.name}: {error}", severity="error"
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
