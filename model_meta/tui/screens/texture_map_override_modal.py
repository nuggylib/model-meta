"""The texture map override modal — link duplicate meshes' maps under one name."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, SelectionList, Static

from model_meta.core.results import TextureMapOverride

_HELP = (
    "Linked meshes load one shared file for each checked map. Unchecked maps keep "
    "each mesh's own `<mesh>_<map>.png`, so repeated parts can still vary."
)


class TextureMapOverrideModal(ModalScreen[TextureMapOverride | None]):
    """Return the override to add, or `None` on `escape`. Writes nothing."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        Binding("q", "noop", show=False),
    ]

    DEFAULT_CSS = """
    TextureMapOverrideModal {
        align: center middle;
    }
    TextureMapOverrideModal > VerticalScroll {
        width: 80%;
        max-width: 70;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    TextureMapOverrideModal SelectionList {
        height: auto;
        max-height: 8;
    }
    TextureMapOverrideModal .override-label {
        margin-top: 1;
    }
    TextureMapOverrideModal #override-status {
        color: $error;
    }
    """

    def __init__(self, role: str, meshes: list[str], maps: list[str]) -> None:
        super().__init__()
        self.role = role
        self.meshes = meshes
        self.maps = maps

    def compose(self) -> ComposeResult:
        # Scrolls so Save stays reachable in a short terminal.
        with VerticalScroll(can_focus=False):
            yield Static(
                f"Share texture maps in {self.role}",
                classes="section-title",
                markup=False,
            )
            yield Static(_HELP, classes="config-detail", markup=False)
            yield Static("Meshes", classes="override-label")
            yield SelectionList[str](
                *((mesh, mesh, True) for mesh in self.meshes), id="override-meshes"
            )
            yield Static("Maps", classes="override-label")
            yield SelectionList[str](
                *((name, name) for name in self.maps), id="override-maps"
            )
            yield Static("Shared name", classes="override-label")
            yield Input(placeholder="e.g. arm_top", id="override-name")
            yield Static(id="override-preview", classes="config-detail", markup=False)
            yield Static(id="override-status", markup=False)
            yield Button("Save", id="save-override")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#override-maps", SelectionList).focus()
        self._preview()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_noop(self) -> None:
        """Absorb `q` so the app's global quit can't fire from the modal."""

    @on(Input.Changed, "#override-name")
    @on(SelectionList.SelectedChanged)
    def _preview(self) -> None:
        name = self._shared_name() or "<name>"
        maps = self._checked("#override-maps", self.maps)
        files = ", ".join(f"{name}_{m}.png" for m in maps) or "no maps checked"
        self.query_one("#override-preview", Static).update(f"Expected: {files}")
        self.query_one("#override-status", Static).update("")

    @on(Input.Submitted, "#override-name")
    @on(Button.Pressed, "#save-override")
    def _on_save(self) -> None:
        name = self._shared_name()
        meshes = self._checked("#override-meshes", self.meshes)
        maps = self._checked("#override-maps", self.maps)
        if len(meshes) < 2:
            problem = "Check at least two meshes to link."
        elif not maps:
            problem = "Check at least one map to share."
        elif not name:
            problem = "Type the shared name."
        elif any(c in name for c in "/\\"):
            problem = "The shared name can't hold `/` or `\\`."
        else:
            self.dismiss(TextureMapOverride(name, maps, meshes))
            return
        self.query_one("#override-status", Static).update(problem)

    # Not `_name`: `DOMNode` stores the widget's name there.
    def _shared_name(self) -> str:
        return self.query_one("#override-name", Input).value.strip()

    def _checked(self, selector: str, listed: list[str]) -> list[str]:
        """In the listed order, not the order they were checked."""
        checked = set(self.query_one(selector, SelectionList).selected)
        return [item for item in listed if item in checked]
