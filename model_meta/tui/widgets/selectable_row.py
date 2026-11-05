"""A focusable row that stands for one thing and posts `Selected` on `enter`."""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static


class SelectableRow(Static, can_focus=True):
    """`key` is what the row stands for; the screen reads it off `Selected.row`.

    `label` is plain text and `marker` is markup shown beside it.
    """

    BINDINGS = [Binding("enter", "select", "Select")]

    label: reactive[str] = reactive("")

    class Selected(Message):
        def __init__(self, row: SelectableRow) -> None:
            super().__init__()
            self.row = row

        @property
        def control(self) -> SelectableRow:
            return self.row

    def __init__(self, key: object, label: str, marker: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.key = key
        self.marker = marker
        self.set_reactive(SelectableRow.label, label)

    def render(self) -> Text:
        # Text, not markup: `rich.markup.escape` misses uppercase tags like `[L]`.
        text = Text(f"▸ {self.label}")
        if self.marker:
            text.append("  ").append_text(Text.from_markup(self.marker))
        return text

    def action_select(self) -> None:
        self.post_message(self.Selected(self))
