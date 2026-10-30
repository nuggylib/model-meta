"""The link-spec modal — pick the spec a model is validated against."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

_NO_SPECS = "No specs yet. Create one on the Specs page."


class LinkSpecModal(ModalScreen[str | None]):
    """Return the chosen spec name, or `None` on `escape`. Writes nothing.

    `specs` are the selectable spec names; the caller loads and filters them.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        Binding("q", "noop", show=False),
    ]

    DEFAULT_CSS = """
    LinkSpecModal {
        align: center middle;
    }
    LinkSpecModal > Vertical {
        width: 80%;
        max-width: 60;
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    LinkSpecModal OptionList {
        margin-top: 1;
        height: auto;
        max-height: 15;
    }
    LinkSpecModal #no-specs {
        margin-top: 1;
    }
    """

    def __init__(self, model_name: str, specs: list[str]) -> None:
        super().__init__()
        self.model_name = model_name
        self.specs = specs

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                f"Link {self.model_name} to a spec…",
                classes="section-title",
                markup=False,
            )
            if self.specs:
                yield OptionList(
                    *(Option(spec, id=spec) for spec in self.specs), id="spec-options"
                )
            else:
                yield Static(_NO_SPECS, id="no-specs", classes="config-detail")
        yield Footer()

    def on_mount(self) -> None:
        if self.specs:
            options = self.query_one("#spec-options", OptionList)
            options.highlighted = 0
            options.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_noop(self) -> None:
        """Absorb `q` so the app's global quit can't fire from the picker."""

    @on(OptionList.OptionSelected, "#spec-options")
    def _on_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)
