"""The model dashboard — one model checked against the spec it was built from."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from model_meta.core.spec import Spec

# Stands in for a validation result until the live Blender connection exists.
_PENDING = "🟡"
_NOT_FOUND = "not found"
_NONE = "None"


class ModelDashboardScreen(Screen):
    """Pushed as an instance, like `SpecDetailScreen`: it is per model and spec."""

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self, model_name: str, spec_path: Path) -> None:
        super().__init__()
        self.model_name = model_name
        self.spec_path = spec_path

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="detail-panel", can_focus=False):
            yield Static(
                f"Models - {self.model_name}",
                id="model-title",
                classes="section-title",
                markup=False,
            )
            yield Static(
                f"Model type: {self.spec_path.stem}",
                id="model-type",
                classes="model-item",
                markup=False,
            )
            for depth, text in self._items():
                yield Static(
                    f"{_PENDING} {text}",
                    classes=f"model-item model-item-depth-{depth}",
                    markup=False,
                )
        yield Footer()

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
