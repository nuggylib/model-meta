from __future__ import annotations

from collections.abc import Sequence

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import HorizontalGroup, VerticalGroup
from textual.content import Content
from textual.widget import Widget
from textual.widgets import Button, Static

from model_meta.tui.templates.layout import Layout


class ConfirmModal(Layout):
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        Binding("left", "app.focus_previous", show=False),
        Binding("right", "app.focus_next", show=False),
        Binding("q", "noop", show=False),
    ]

    def __init__(
        self,
        question: str | Content,
        details: Sequence[Widget] = (),
    ) -> None:
        super().__init__(page_title="Confirm")
        self.question = question
        self._details = details

    def compose_body(self) -> ComposeResult:
        with VerticalGroup(classes="centered"):
            yield Static(self.question, id="confirm-question", markup=False)
            yield from self._details
            with HorizontalGroup(id="confirm-buttons"):
                yield Button("No", id="confirm-no")
                yield Button("Yes", id="confirm-yes", variant="default")

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
