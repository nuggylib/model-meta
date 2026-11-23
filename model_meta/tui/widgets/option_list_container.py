from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeAlias

from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalGroup
from textual.widgets import Button, OptionList, Static


@dataclass(frozen=True)
class ListOption:
    # The label to display per option
    label: str
    # The value that the options corresponds to
    value: str


# None is excluded as an option since the component adds them automatically between rows; callers
# should not have to set up the dividers.
ListEntry: TypeAlias = ListOption


class OptionListContainer(VerticalGroup):
    # TODO: Update this later
    # CSS_PATH = "option_list.tcss"

    _label: str
    _description: str
    _entries: Sequence[ListEntry | None]

    def __init__(self, label: str, description: str, entries: Sequence[ListEntry]):
        super().__init__()
        self._label = label
        self._description = description
        built: list[ListEntry] = []
        for idx, entry in enumerate(entries):
            # Add a separator before every entry EXCEPT the first one (idx = 0 fails the check)
            if idx:
                built.append(None)
            built.append(entry)
        self._entries = tuple(built)

    def compose(self) -> ComposeResult:
        with VerticalGroup(classes=("options-list-container")):
            yield Static(content=self._label, classes=("h2"))
            yield Static(content=self._description, classes=("description"))
            yield OptionList(*self._entries)
            with HorizontalGroup():
                yield Button("Add", variant="primary")
