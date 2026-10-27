"""The edit-data modal — pick which root field of a spec to edit."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

# (spec root key, label). A new root field is one entry here plus one route in
# `SpecDetailScreen._edit_data`.
FIELDS = (
    ("armature", "Armature"),
    ("mesh_roles", "Mesh roles"),
    ("modifiers", "Modifiers"),
)


class EditDataModal(ModalScreen[str | None]):
    """Return the chosen root-field key, or `None` on `escape`. Writes nothing.

    Composes its own `Footer` and shadows `q`, like `NewSpecModal`.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        Binding("q", "noop", show=False),
    ]

    DEFAULT_CSS = """
    EditDataModal {
        align: center middle;
    }
    EditDataModal > Vertical {
        width: 80%;
        max-width: 50;
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    EditDataModal OptionList {
        margin-top: 1;
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Edit data…", classes="section-title")
            yield OptionList(
                *(Option(label, id=key) for key, label in FIELDS), id="data-fields"
            )
        yield Footer()

    def on_mount(self) -> None:
        options = self.query_one("#data-fields", OptionList)
        options.highlighted = 0
        options.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_noop(self) -> None:
        """Absorb `q` so the app's global quit can't fire from the picker."""

    @on(OptionList.OptionSelected, "#data-fields")
    def _on_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)
