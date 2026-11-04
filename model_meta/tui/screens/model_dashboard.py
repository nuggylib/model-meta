"""The model dashboard — one model checked against the spec it was built from."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from model_meta.core.blender_bridge import (
    BridgeError,
    OpenFile,
    subscribe_armatures,
)
from model_meta.core.blender_connection import BlenderConnection
from model_meta.core.results import Results
from model_meta.core.spec import Spec

# A row with no check result in the results file.
_PENDING = "🟡"
_REFRESHING = "🔄"
_PASS = "✅"
_FAIL = "❌"
_ARMATURE_ROW = 0
_NOT_FOUND = "not found"
_NONE = "None"
_LIVE_MODE = "Live Mode"
_MANUAL_MODE = "Manual Mode"
_INACTIVE = "Inactive"
_WRONG_FILE = "Wrong File"
_LIVE_HINT = "Results update when you load a file, or save one, in Blender."
_REFRESH_HINT = "Press r to refresh."
_INACTIVE_HINT = "Start Blender, then press r to refresh."


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
    armature_passed: reactive[bool | None] = reactive(None)

    def __init__(self, model: Path, spec_path: Path, results_path: Path) -> None:
        super().__init__()
        self.model = model
        self.spec_path = spec_path
        self.results_path = results_path
        self._armature = ""
        self._rows: list[tuple[int, str]] = []
        self._on_model = False

    def compose(self) -> ComposeResult:
        try:
            spec = Spec.load(self.spec_path)
        except (OSError, ValueError):
            spec = None
        self._armature = spec.armature.object_name if spec else ""
        self._load_results()
        self._rows = self._items(spec)
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
            for index, (depth, text) in enumerate(self._rows):
                yield Static(
                    f"{self._emoji(index)} {text}",
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
            async for message in subscribe_armatures():
                self.live = True
                self.is_refreshing = False
                if isinstance(message, OpenFile):
                    self._on_model = _is_model(message.path, self.model)
                    self.wrong_file = not self._on_model
                # busy (`None`): keep the last result
                elif message.names is not None and self._on_model:
                    self._save_armature(self._armature in message.names)
        except BridgeError:
            pass
        self._on_model = False
        self.live = False
        self.wrong_file = False
        self.is_refreshing = True
        self.blender_running = await asyncio.to_thread(BlenderConnection.is_running)
        self.is_refreshing = False

    def watch_is_refreshing(self) -> None:
        self._update_rows()

    def watch_armature_passed(self) -> None:
        self._update_rows()

    def _load_results(self) -> None:
        try:
            self.armature_passed = Results.load(self.results_path).armature
        except (OSError, ValueError):
            self.armature_passed = None

    def _save_armature(self, passed: bool) -> None:
        try:
            results = Results.load(self.results_path)
            if results.armature is not passed:
                results.armature = passed
                results.save()
        except (OSError, ValueError) as error:
            self.notify(
                f"Couldn't save {self.results_path.name}: {error}", severity="error"
            )
            return
        self.armature_passed = passed

    def watch_live(self) -> None:
        self._update_connection()

    def watch_blender_running(self) -> None:
        self._update_connection()

    def watch_wrong_file(self) -> None:
        self._update_connection()

    def _update_rows(self) -> None:
        for index, (_, text) in enumerate(self._rows):
            try:
                row = self.query_one(f"#model-item-{index}", Static)
            except NoMatches:
                return
            row.update(f"{self._emoji(index)} {text}")

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

    def _emoji(self, index: int) -> str:
        if self.is_refreshing:
            return _REFRESHING
        if index == _ARMATURE_ROW and self.armature_passed is not None:
            return _PASS if self.armature_passed else _FAIL
        return _PENDING

    def _items(self, spec: Spec | None) -> list[tuple[int, str]]:
        roles = list(spec.mesh_roles) if spec else []
        return [
            (0, f"Armature: {self._armature or _NOT_FOUND}"),
            (0, "Mesh Roles:"),
            *((1, role) for role in roles),
            (0, "Modifiers"),
            (1, "Required:"),
            (2, "Skinned Meshes"),
            (1, f"Warnings: {_NONE}"),
            (1, f"Blocked: {_NONE}"),
        ]


def _is_model(open_file: str | None, model: Path) -> bool:
    if open_file is None:
        return False
    try:
        # samefile, not ==: a symlinked model or a case-insensitive filesystem still matches.
        return Path(open_file).samefile(model)
    except OSError:
        return False
