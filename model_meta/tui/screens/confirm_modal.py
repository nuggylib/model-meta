"""The confirm modal — one Yes/No question before a destructive write."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Static


class ConfirmModal(ModalScreen[bool]):
    """Ask `question`; return `True` for Yes, `False` for No or `escape`.

    **No** has focus on open, so a stray Enter cancels. `left`/`right` move
    between the buttons. Writes nothing. Composes its own `Footer` and shadows
    `q`, like `NewSpecModal`.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        Binding("left", "app.focus_previous", show=False),
        Binding("right", "app.focus_next", show=False),
        Binding("q", "noop", show=False),
    ]

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    ConfirmModal > Vertical {
        width: 80%;
        max-width: 50;
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    ConfirmModal #confirm-question {
        height: auto;
    }
    ConfirmModal #confirm-buttons {
        height: auto;
        align-horizontal: right;
    }
    ConfirmModal #confirm-buttons Button {
        margin: 1 0 0 1;
    }
    """

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.question, id="confirm-question", markup=False)
            with Horizontal(id="confirm-buttons"):
                yield Button("No", id="confirm-no")
                yield Button("Yes", id="confirm-yes", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#confirm-no", Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_noop(self) -> None:
        """Absorb `q` so the app's global quit can't fire from the dialog."""

    @on(Button.Pressed, "#confirm-yes")
    def _on_yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#confirm-no")
    def _on_no(self) -> None:
        self.dismiss(False)
