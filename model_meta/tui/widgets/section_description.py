from textual.containers import HorizontalGroup, VerticalGroup
from textual.widgets import Static


class SectionDescription(VerticalGroup):
    _label: str
    _description: str

    def __init__(self, label: str, description: str):
        super().__init__()
        self._label = label
        self._description = description

    def compose(self):
        with VerticalGroup():
            with HorizontalGroup(classes="section-heading"):
                yield Static(content=self._label, classes="h2")
            if len(self._description) > 0:
                yield Static(content=self._description, classes=("description"))
