"""The model dashboard — one model checked against the spec it was built from."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import aclosing
from dataclasses import replace
from functools import partial
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.screen import Screen
from textual.signal import Signal
from textual.widgets import Footer, Header, Static

from model_meta.checks import mesh_roles
from model_meta.core.blender_bridge import (
    Armatures,
    BridgeError,
    MeshReport,
    OpenFile,
    subscribe_armatures,
    subscribe_meshes,
)
from model_meta.core.blender_connection import BlenderConnection
from model_meta.core.results import Results
from model_meta.core.spec import MeshRole, Spec
from model_meta.tui.bindings import MOVE
from model_meta.tui.screens.check_detail import CheckDetailScreen
from model_meta.tui.status import REFRESHING, icon, most_severe, status_of
from model_meta.tui.widgets.selectable_row import SelectableRow

_NOT_FOUND = "not found"
_NONE = "None"
_LIVE_MODE = "Live Mode"
_MANUAL_MODE = "Manual Mode"
_INACTIVE = "Inactive"
_WRONG_FILE = "Wrong File"
_LIVE_HINT = "Results update when you load a file, or save one, in Blender."
_REFRESH_HINT = "Press r to refresh."
_INACTIVE_HINT = "Start Blender, then press r to refresh."

# Each root row's results file key, and the title its detail screen shows.
_ROOTS = {"armature": "Armature", "mesh_roles": "Mesh Roles", "modifiers": "Modifiers"}

# depth, text, and the row's key path in the results file (`None`: never checked).
Row = tuple[int, str, tuple[str, ...] | None]


class ModelDashboardScreen(Screen):
    """Pushed as an instance, like `SpecDetailScreen`: it is per model and spec."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("r", "refresh", "Refresh"),
        *MOVE,
    ]

    is_refreshing: reactive[bool] = reactive(False)
    blender_running: reactive[bool | None] = reactive(None)
    live: reactive[bool] = reactive(False)
    wrong_file: reactive[bool] = reactive(False)
    results: reactive[Results | None] = reactive(None)

    def __init__(self, model: Path, spec_path: Path, results_path: Path) -> None:
        super().__init__()
        self.model = model
        self.spec_path = spec_path
        self.results_path = results_path
        self.results_changed: Signal[Results | None] = Signal(self, "results_changed")
        self._armature = ""
        self._roles: dict[str, MeshRole] = {}
        self._rows: list[Row] = []

    def compose(self) -> ComposeResult:
        try:
            spec = Spec.load(self.spec_path)
        except (OSError, ValueError):
            spec = None
        self._armature = spec.armature.object_name if spec else ""
        self._roles = dict(spec.mesh_roles) if spec else {}
        self._load_results()
        self._rows = self._items()
        yield Header()
        with VerticalScroll(id="detail-panel", can_focus=False):
            with Vertical(id="model-header"):
                with Horizontal(id="model-heading"):
                    yield Static(
                        f"Models - {self.model.stem}",
                        id="model-title",
                        classes="section-title",
                        markup=False,
                    )
                    yield Static(id="connection-status", classes="config-detail")
                yield Static(
                    _REFRESH_HINT,
                    id="connection-hint",
                    classes="config-detail",
                    markup=False,
                )
            yield Static(
                f"Model type: {self.spec_path.stem}",
                id="model-type",
                classes="model-item",
                markup=False,
            )
            for index, (depth, _, path) in enumerate(self._rows):
                options = {
                    "id": f"model-item-{index}",
                    "classes": f"model-item model-item-depth-{depth}",
                }
                label = self._label(index)
                if depth == 0:
                    yield SelectableRow(path[0], label, **options)
                else:
                    yield Static(label, markup=False, **options)
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def action_refresh(self) -> None:
        self._load_results()
        self._refresh()

    def on_selectable_row_selected(self, message: SelectableRow.Selected) -> None:
        field = message.row.key
        self.app.push_screen(
            CheckDetailScreen(
                self.model, field, _ROOTS[field], self.results, self.results_changed
            )
        )

    @work(exclusive=True, group="blender-check")
    async def _refresh(self) -> None:
        self.is_refreshing = True
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(
                    self._follow(subscribe_armatures(), self._check_armature)
                )
                group.create_task(
                    self._follow(
                        subscribe_meshes(partial(mesh_roles.plan, self._roles)),
                        self._check_mesh_roles,
                    )
                )
        except* BridgeError:
            pass
        self.live = False
        self.wrong_file = False
        self.is_refreshing = True
        self.blender_running = await asyncio.to_thread(BlenderConnection.is_running)
        self.is_refreshing = False

    async def _follow(self, messages: AsyncIterator, check: Callable) -> None:
        """Runs `check` on each result that arrives while the model's file is open."""
        on_model = False
        async with aclosing(messages):
            async for message in messages:
                self.live = True
                self.is_refreshing = False
                if isinstance(message, OpenFile):
                    on_model = _is_model(message.path, self.model)
                    self.wrong_file = not on_model
                elif on_model:
                    check(message)

    def _check_armature(self, message: Armatures) -> None:
        # busy (`None`): keep the last result
        if message.names is not None:
            self._save(armature=self._armature in message.names)

    def _check_mesh_roles(self, report: MeshReport) -> None:
        self._save(mesh_roles=mesh_roles.evaluate(self._roles, report))

    def watch_is_refreshing(self) -> None:
        self._update_rows()

    def watch_results(self) -> None:
        self._update_rows()
        self.results_changed.publish(self.results)

    def _load_results(self) -> None:
        try:
            self.results = Results.load(self.results_path)
        except (OSError, ValueError):
            self.results = None

    def _save(self, **checks: object) -> None:
        try:
            results = Results.load(self.results_path)
            updated = replace(results, **checks)
            if updated != results:
                updated.save()
        except (OSError, ValueError) as error:
            self.notify(
                f"Couldn't save {self.results_path.name}: {error}", severity="error"
            )
            return
        self.results = updated

    def watch_live(self) -> None:
        self._update_connection()

    def watch_blender_running(self) -> None:
        self._update_connection()

    def watch_wrong_file(self) -> None:
        self._update_connection()

    def _update_rows(self) -> None:
        for index in range(len(self._rows)):
            try:
                row = self.query_one(f"#model-item-{index}")
            except NoMatches:
                return
            if isinstance(row, SelectableRow):
                row.label = self._label(index)
            elif isinstance(row, Static):
                row.update(self._label(index))

    def _update_connection(self) -> None:
        try:
            status = self.query_one("#connection-status", Static)
            hint = self.query_one("#connection-hint", Static)
        except NoMatches:
            return
        if self.live and self.wrong_file:
            status.update(_WRONG_FILE)
            hint.update(
                f"Blender doesn't have {self.model.name} open. "
                "Results are paused until it does."
            )
            return
        if self.live:
            status.update(_LIVE_MODE)
            hint.update(_LIVE_HINT)
            return
        running = self.blender_running
        if running is None:
            status.update("")
        else:
            status.update(_MANUAL_MODE if running else _INACTIVE)
        hint.update(_INACTIVE_HINT if running is False else _REFRESH_HINT)

    def _label(self, index: int) -> str:
        text = self._rows[index][1]
        if self.is_refreshing:
            return f"{REFRESHING} {text}"
        data = None if self.results is None else self.results.to_dict()
        return f"{icon(self._status(index, data))} {text}"

    def _status(self, index: int, data: dict | None) -> bool | None:
        """A row with rows beneath it shows the most severe of theirs."""
        path = self._rows[index][2]
        if data is None or path is None or (value := _lookup(data, path)) is None:
            return None
        children = list(self._children(index))
        if children:
            return most_severe(self._status(child, data) for child in children)
        return status_of(value)

    def _children(self, index: int) -> Iterator[int]:
        depth = self._rows[index][0]
        for child in range(index + 1, len(self._rows)):
            if self._rows[child][0] <= depth:
                return
            if self._rows[child][0] == depth + 1:
                yield child

    def _items(self) -> list[Row]:
        return [
            (0, f"{_ROOTS['armature']}: {self._armature or _NOT_FOUND}", ("armature",)),
            (0, f"{_ROOTS['mesh_roles']}:", ("mesh_roles",)),
            *((1, name, ("mesh_roles", name)) for name in self._roles),
            (0, _ROOTS["modifiers"], ("modifiers",)),
            (1, "Required:", None),
            (2, "Skinned Meshes", None),
            (1, f"Warnings: {_NONE}", None),
            (1, f"Blocked: {_NONE}", None),
        ]


def _lookup(data: dict, path: tuple[str, ...]) -> object:
    """The value at `path`, or `None` when any key is missing."""
    value: object = data
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _is_model(open_file: str | None, model: Path) -> bool:
    if open_file is None:
        return False
    try:
        # samefile, not ==: a symlinked model or a case-insensitive filesystem still matches.
        return Path(open_file).samefile(model)
    except OSError:
        return False
