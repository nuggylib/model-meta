from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeAlias

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalGroup
from textual.content import Content
from textual.css.styles import RulesMap
from textual.strip import Strip
from textual.style import Style
from textual.visual import RenderOptions, Visual
from textual.widget import Widget
from textual.widgets import OptionList, TabbedContent, TabPane
from textual.widgets.option_list import Option

from model_meta.tui.widgets.section_description import SectionDescription

ADD_TAB_LABEL = "+"


class _Options(OptionList):
    # `OptionList` hides its own `enter`; the footer shows the focused widget's first.
    BINDINGS = [
        Binding("enter", "select", "Select"),
        Binding("down", "cursor_down", "Move", key_display="↑↓/jk"),
        Binding("up", "cursor_up", "Move", show=False),
        Binding("j", "cursor_down", "Move", show=False),
        Binding("k", "cursor_up", "Move", show=False),
    ]

    def watch_highlighted(self, old: int | None, new: int | None) -> None:
        super().watch_highlighted(new)
        for idx, focused in ((old, False), (new, True)):
            # `old` can outlive a `clear_options`.
            if idx is None or idx >= self.option_count:
                continue
            prompt = self.get_option_at_index(idx).prompt
            if isinstance(prompt, _SplitRow):
                self.replace_option_prompt_at_index(idx, prompt.focused(focused))


class _SplitRow(Visual):
    def __init__(self, left: Content, detail: str, focused: bool = False):
        self._left = left
        self._detail = detail
        self._right = Content.styled(
            f"({detail})", "$secondary" if focused else "$accent"
        )

    def focused(self, focused: bool) -> "_SplitRow":
        return _SplitRow(self._left, self._detail, focused)

    def render_strips(
        self, width: int, height: int | None, style: Style, options: RenderOptions
    ) -> list[Strip]:
        room = max(width - self._right.cell_length - 2, 0)
        row = Content.assemble(
            self._left.truncate(room, ellipsis=True, pad=True), " ", self._right, " "
        )
        return row.render_strips(width, height, style, options)

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        return self._left.cell_length + 2 + self._right.cell_length

    def get_height(self, rules: RulesMap, width: int) -> int:
        return 1


@dataclass(frozen=True)
class ListOption:
    # The label to display per option
    label: str
    # The value that the options corresponds to
    value: str
    # Shown against the row's right edge in $accent
    detail: str | None = None


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
    _details: Sequence[Widget]

    def __init__(
        self,
        label: str,
        description: str,
        tabs: Sequence[ListTab],
        highlight_last: bool = False,
        delimiter: str | None = None,
        details: Sequence[Widget] = (),
    ):
        """Raises `ValueError` when `highlight_last` is set without a `delimiter`."""
        super().__init__()
        if highlight_last and not delimiter:
            raise ValueError("highlight_last requires a delimiter")
        self._label = label
        self._description = description
        self._tabs = tuple(tabs) or (ListTab(ADD_TAB_LABEL, ()),)
        self._delimiter = delimiter if highlight_last else None
        self._details = tuple(details)

    def compose(self) -> ComposeResult:
        with VerticalGroup(classes=("options-list-container")):
            yield SectionDescription(label=self._label, description=self._description)
            if self._details:
                with VerticalGroup():
                    yield from self._details
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

    @property
    def active_index(self) -> int:
        """Raises `NoMatches` once unmounted."""
        return int(self.query_one(TabbedContent).active.removeprefix("tab-"))

    def _with_separators(self, entries: Sequence[ListEntry]) -> list[Option | None]:
        built: list[Option | None] = []
        for idx, entry in enumerate(entries):
            # Add a separator before every entry EXCEPT the first one (idx = 0 fails the check)
            if idx:
                built.append(None)
            prompt = self._prompt(entry.label)
            if entry.detail is not None:
                prompt = _SplitRow(prompt, entry.detail)
            built.append(Option(prompt, id=entry.value))
        return built

    def _prompt(self, label: str) -> Content:
        if self._delimiter is None:
            return Content(label)
        head, delimiter, last = label.rpartition(self._delimiter)
        return Content.assemble(head + delimiter, (last, "$primary"))
