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

from model_meta.core.blender_connection import BlenderConnection
from model_meta.core.spec import Spec

# Stands in for a validation result until the live Blender connection exists.
_PENDING = "🟡"
_REFRESHING = "🔄"
_NOT_FOUND = "not found"
_NONE = "None"
_MANUAL_MODE = "Manual Mode"
_INACTIVE = "Inactive"
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

    def __init__(self, model_name: str, spec_path: Path) -> None:
        super().__init__()
        self.model_name = model_name
        self.spec_path = spec_path
        self._rows: list[tuple[int, str]] = []

    def compose(self) -> ComposeResult:
        self._rows = self._items()
        yield Header()
        with VerticalScroll(id="detail-panel", can_focus=False):
            with Vertical(id="model-header"):
                with Horizontal(id="model-heading"):
                    yield Static(
                        f"Models - {self.model_name}",
                        id="model-title",
                        classes="section-title",
                        markup=False,
                    )
                    yield Static(id="connection-status", classes="config-detail")
                yield Static(
                    _REFRESH_HINT, id="connection-hint", classes="config-detail"
                )
            yield Static(
                f"Model type: {self.spec_path.stem}",
                id="model-type",
                classes="model-item",
                markup=False,
            )
            for index, (depth, text) in enumerate(self._rows):
                yield Static(
                    f"{self._emoji()} {text}",
                    id=f"model-item-{index}",
                    classes=f"model-item model-item-depth-{depth}",
                    markup=False,
                )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def action_refresh(self) -> None:
        self._refresh()

    @work(exclusive=True, group="blender-check")
    async def _refresh(self) -> None:
        self.is_refreshing = True
        self.blender_running = await asyncio.to_thread(BlenderConnection.is_running)
        self.is_refreshing = False

    def watch_is_refreshing(self) -> None:
        for index, (_, text) in enumerate(self._rows):
            try:
                row = self.query_one(f"#model-item-{index}", Static)
            except NoMatches:
                return
            row.update(f"{self._emoji()} {text}")

    def watch_blender_running(self, running: bool | None) -> None:
        try:
            status = self.query_one("#connection-status", Static)
            hint = self.query_one("#connection-hint", Static)
        except NoMatches:
            return
        if running is None:
            status.update("")
        else:
            status.update(_MANUAL_MODE if running else _INACTIVE)
        hint.update(_INACTIVE_HINT if running is False else _REFRESH_HINT)

    def _emoji(self) -> str:
        return _REFRESHING if self.is_refreshing else _PENDING

    def _items(self) -> list[tuple[int, str]]:
        try:
            spec = Spec.load(self.spec_path)
        except (OSError, ValueError):
            spec = None
        armature = spec.armature.object_name if spec else ""
        roles = list(spec.mesh_roles) if spec else []
        return [
            (0, f"Armature: {armature or _NOT_FOUND}"),
            (0, "Mesh Roles:"),
            *((1, role) for role in roles),
            (0, "Modifiers"),
            (1, "Required:"),
            (2, "Skinned Meshes"),
            (1, f"Warnings: {_NONE}"),
            (1, f"Blocked: {_NONE}"),
        ]
