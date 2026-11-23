from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeAlias

from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalGroup
from textual.content import Content
from textual.widgets import OptionList, Static, TabbedContent, TabPane
from textual.widgets.option_list import Option

ADD_TAB_LABEL = "+"


@dataclass(frozen=True)
class ListOption:
    # The label to display per option
    label: str
    # The value that the options corresponds to
    value: str


# None is excluded as an option since the component adds them automatically between rows; callers
# should not have to set up the dividers.
ListEntry: TypeAlias = ListOption


@dataclass(frozen=True)
class ListTab:
    # The label to display on the tab
    label: str
    # The entries listed in this tab's OptionList
    entries: Sequence[ListEntry]


class OptionListContainer(VerticalGroup):
    # TODO: Update this later
    # CSS_PATH = "option_list.tcss"

    _label: str
    _description: str
    _tabs: Sequence[ListTab]

    def __init__(self, label: str, description: str, tabs: Sequence[ListTab]):
        super().__init__()
        self._label = label
        self._description = description
        self._tabs = tuple(tabs) or (ListTab(ADD_TAB_LABEL, ()),)

    def compose(self) -> ComposeResult:
        with VerticalGroup(classes=("options-list-container")):
            with HorizontalGroup(classes="section-heading"):
                yield Static(content=self._label, classes="h2")
            yield Static(content=self._description, classes=("description"))
            with TabbedContent():
                for idx, tab in enumerate(self._tabs):
                    # Content, not str: a directory name like `cars[wip]` isn't markup.
                    with TabPane(Content(tab.label), id=f"tab-{idx}"):
                        yield OptionList(*_with_separators(tab.entries))

    def set_entries(self, idx: int, entries: Sequence[ListEntry]) -> None:
        """Replace tab `idx`'s entries. Raises `NoMatches` once unmounted."""
        options = self.query_one(f"#tab-{idx} OptionList", OptionList)
        options.clear_options()
        options.add_options(_with_separators(entries))


def _with_separators(entries: Sequence[ListEntry]) -> list[Option | None]:
    built: list[Option | None] = []
    for idx, entry in enumerate(entries):
        # Add a separator before every entry EXCEPT the first one (idx = 0 fails the check)
        if idx:
            built.append(None)
        built.append(Option(Content(entry.label), id=entry.value))
    return built
