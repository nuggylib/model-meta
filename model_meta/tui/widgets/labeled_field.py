from rich.markup import escape
from textual.containers import HorizontalGroup
from textual.content import Content
from textual.widgets import Static


class LabeledField(HorizontalGroup):
    def __init__(self, label: str, val: Content, val_id: str | None = None):
        super().__init__()
        self._label = label
        self._val = val  # val is typed as Content to allow caller to pass flexible values (for interpolated/styled text)
        self._val_id = val_id

    def compose(self):
        with HorizontalGroup():
            yield Static(
                content=f"[b]{escape(self._label)}:[/b]", classes="field-label"
            )
            yield Static(content=self._val, id=self._val_id)
