from typing import NamedTuple

from rich.text import Text
from textual.containers import HorizontalGroup, VerticalGroup, VerticalScroll
from textual.content import Content
from textual.renderables.bar import Bar
from textual.widgets import DataTable, ProgressBar, Static

from model_meta.tui.widgets.section_description import SectionDescription

# Theme variable names, not markup: DataTable renders cells with Rich, which
# can't resolve `$success`.
_RESULTS = {True: ("PASS", "success"), False: ("FAIL", "error")}


class BlockBar(Bar):
    HALF_BAR_LEFT = "▐"
    BAR = "█"
    HALF_BAR_RIGHT = "▌"


class BlockProgressBar(ProgressBar):
    BAR_RENDERABLE = BlockBar


class ChecksRow(NamedTuple):
    check: str
    expected: str
    passed: bool


class ChecksSection(VerticalGroup):
    def __init__(
        self,
        title: str,
        description: str,
        rows: list[ChecksRow],
        fixes: list[str | Content],
    ):
        super().__init__()
        self._title = title
        self._description = description
        self._rows = rows
        self._fixes = fixes

    def compose(self):
        with VerticalGroup():
            yield SectionDescription(
                label=self._title,
                description=self._description,
            )
            with HorizontalGroup(classes="columns"):
                with VerticalGroup():
                    yield BlockProgressBar(
                        total=len(self._rows),
                        show_eta=False,
                        classes="section-progress-bar",
                    )
                    yield DataTable(classes="armature-checks")
                with VerticalGroup():
                    yield Static(content="Recommended Fixes", classes="column-heading")
                    with VerticalScroll(classes="fixes-panel"):
                        for fix in self._generate_fixes_content():
                            yield Static(fix)

    def on_mount(self) -> None:
        self.query_one(BlockProgressBar).update(
            progress=sum(row.passed for row in self._rows)
        )
        table = self.query_one(DataTable)
        table.add_columns("Test", "Condition", "Result")
        table.add_rows(self._generate_rows_content())

    def _generate_rows_content(self):
        rows_content = []
        for row in self._rows:
            rows_content.append(self._row(row.check, row.expected, row.passed))
        return rows_content

    def _row(self, check: str, expected: str, passed: bool) -> tuple[Text, ...]:
        label, color = _RESULTS[passed]
        theme = self.app.theme_variables
        return (
            Text(check, style=theme["primary"]),
            Text(expected, style=theme["secondary"]),
            Text(label, style=theme[color]),
        )

    def _generate_fixes_content(self):
        if len(self._fixes) == 0:
            return ["All checks are passing!"]
        return [Content.assemble("- ", fix) for fix in self._fixes]
