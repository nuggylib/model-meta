"""The model dashboard — one model checked against the spec it was built from."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterable
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

# A row with no check result in the results file.
_PENDING = "🟡"
_REFRESHING = "🔄"
_PASS = "✅"
_FAIL = "❌"
_NOT_FOUND = "not found"
_NONE = "None"
_LIVE_MODE = "Live Mode"
_MANUAL_MODE = "Manual Mode"
_INACTIVE = "Inactive"
_WRONG_FILE = "Wrong File"
_LIVE_HINT = "Results update when you load a file, or save one, in Blender."
_REFRESH_HINT = "Press r to refresh."
_INACTIVE_HINT = "Start Blender, then press r to refresh."

# A row's status in the results file: `None` when it was never checked.
Status = Callable[[Results], bool | None]


class ModelDashboardScreen(Screen):
    """Pushed as an instance, like `SpecDetailScreen`: it is per model and spec."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("r", "refresh", "Refresh"),
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
        self._armature = ""
        self._roles: dict[str, MeshRole] = {}
        self._rows: list[tuple[int, str, Status]] = []

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
            for index, (depth, text, status) in enumerate(self._rows):
                yield Static(
                    f"{self._emoji(status)} {text}",
                    id=f"model-item-{index}",
                    classes=f"model-item model-item-depth-{depth}",
                    markup=False,
                )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def action_refresh(self) -> None:
        self._load_results()
        self._refresh()

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
        for index, (_, text, status) in enumerate(self._rows):
            try:
                row = self.query_one(f"#model-item-{index}", Static)
            except NoMatches:
                return
            row.update(f"{self._emoji(status)} {text}")

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

    def _emoji(self, status: Status) -> str:
        if self.is_refreshing:
            return _REFRESHING
        passed = None if self.results is None else status(self.results)
        if passed is None:
            return _PENDING
        return _PASS if passed else _FAIL

    def _items(self) -> list[tuple[int, str, Status]]:
        return [
            (0, f"Armature: {self._armature or _NOT_FOUND}", _armature),
            (0, "Mesh Roles:", self._all_roles),
            *((1, name, partial(_role, name)) for name in self._roles),
            (0, "Modifiers", _unchecked),
            (1, "Required:", _unchecked),
            (2, "Skinned Meshes", _unchecked),
            (1, f"Warnings: {_NONE}", _unchecked),
            (1, f"Blocked: {_NONE}", _unchecked),
        ]

    def _all_roles(self, results: Results) -> bool | None:
        if results.mesh_roles is None:
            return None
        return _most_severe(_role(name, results) for name in self._roles)


def _armature(results: Results) -> bool | None:
    return results.armature


def _role(name: str, results: Results) -> bool | None:
    role = (results.mesh_roles or {}).get(name)
    if role is None:
        return None
    return all(check.passed for check in role.checks.values())


def _unchecked(_results: Results) -> None:
    return None


def _most_severe(statuses: Iterable[bool | None]) -> bool | None:
    """A failure, else a pending row, else a pass."""
    statuses = list(statuses)
    if False in statuses:
        return False
    if None in statuses:
        return None
    return True


def _is_model(open_file: str | None, model: Path) -> bool:
    if open_file is None:
        return False
    try:
        # samefile, not ==: a symlinked model or a case-insensitive filesystem still matches.
        return Path(open_file).samefile(model)
    except OSError:
        return False
