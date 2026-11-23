from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeAlias

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import HorizontalGroup, VerticalGroup
from textual.content import Content
from textual.widgets import OptionList, Static, TabbedContent, TabPane
from textual.widgets.option_list import Option

ADD_TAB_LABEL = "+"


class _Options(OptionList):
    # `OptionList` hides its own `enter`; the footer shows the focused widget's first.
    BINDINGS = [Binding("enter", "select", "Select")]


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
    _delimiter: str | None

    def __init__(
        self,
        label: str,
        description: str,
        tabs: Sequence[ListTab],
        highlight_last: bool = False,
        delimiter: str | None = None,
    ):
        """Raises `ValueError` when `highlight_last` is set without a `delimiter`."""
        super().__init__()
        if highlight_last and not delimiter:
            raise ValueError("highlight_last requires a delimiter")
        self._label = label
        self._description = description
        self._tabs = tuple(tabs) or (ListTab(ADD_TAB_LABEL, ()),)
        self._delimiter = delimiter if highlight_last else None

    def compose(self) -> ComposeResult:
        with VerticalGroup(classes=("options-list-container")):
            with HorizontalGroup(classes="section-heading"):
                yield Static(content=self._label, classes="h2")
            yield Static(content=self._description, classes=("description"))
            with TabbedContent():
                for idx, tab in enumerate(self._tabs):
                    # Content, not str: a directory name like `cars[wip]` isn't markup.
                    with TabPane(Content(tab.label), id=f"tab-{idx}"):
                        # Not constructor args: those highlight the first option.
                        yield _Options().add_options(self._with_separators(tab.entries))

    def on_descendant_blur(self, event: events.DescendantBlur) -> None:
        if isinstance(event.widget, OptionList):
            event.widget.highlighted = None

    def set_entries(self, idx: int, entries: Sequence[ListEntry]) -> None:
        """Replace tab `idx`'s entries. Raises `NoMatches` once unmounted."""
        options = self.query_one(f"#tab-{idx} OptionList", OptionList)
        options.clear_options()
        options.add_options(self._with_separators(entries))

    def _with_separators(self, entries: Sequence[ListEntry]) -> list[Option | None]:
        built: list[Option | None] = []
        for idx, entry in enumerate(entries):
            # Add a separator before every entry EXCEPT the first one (idx = 0 fails the check)
            if idx:
                built.append(None)
            built.append(Option(self._prompt(entry.label), id=entry.value))
        return built

    def _prompt(self, label: str) -> Content:
        if self._delimiter is None:
            return Content(label)
        head, delimiter, last = label.rpartition(self._delimiter)
        return Content.assemble(head + delimiter, (last, "$primary"))
