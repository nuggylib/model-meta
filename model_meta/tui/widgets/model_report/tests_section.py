from __future__ import annotations

import math
from enum import Enum
from functools import partial
from typing import NamedTuple

from rich.console import Console, ConsoleOptions, RenderResult
from rich.style import StyleType
from rich.text import Text
from textual.containers import HorizontalGroup, VerticalGroup, VerticalScroll
from textual.content import Content
from textual.renderables.bar import Bar
from textual.widgets import DataTable, ProgressBar, Static

from model_meta.tui.widgets.section_description import SectionDescription


class TestResult(Enum):
    # Theme variable names, not markup: DataTable renders cells with Rich, which
    # can't resolve `$success`.
    PASS = ("PASS", "success")
    WARN = ("WARN", "warning")
    FAIL = ("FAIL", "error")

    @classmethod
    def of(cls, passed: bool) -> TestResult:
        return cls.PASS if passed else cls.FAIL


class BlockBar(Bar):
    HALF_BAR_LEFT = "▐"
    BAR = "█"
    HALF_BAR_RIGHT = "▌"

    def __init__(
        self,
        *args,
        warning_fraction: float = 0,
        warning_style: StyleType = "",
        **kwargs,
    ) -> None:
        """The last `warning_fraction` of the width in the filled part is drawn in
        `warning_style`."""
        super().__init__(*args, **kwargs)
        self.warning_fraction = warning_fraction
        self.warning_style = warning_style

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        width = self.width or options.max_width
        warnings = round(width * self.warning_fraction)
        if self.warning_fraction:
            warnings = max(warnings, 1)
        start, end = self.highlight_range
        # Whole cells, so the passes don't end on a half cell before the warnings.
        warning_end = min(math.ceil(end), width)
        passing_end = max(math.ceil(start), warning_end - warnings)
        self.highlight_range = (start, passing_end)
        for bar in super().__rich_console__(console, options):
            if not warnings:
                yield bar
                continue
            # Replaced, not restyled: the cell after the passes is a half cell.
            passing, _, rest = bar.divide([passing_end, warning_end])
            yield Text.assemble(
                passing,
                (self.BAR * (warning_end - passing_end), self.warning_style),
                rest,
                end="",
            )


class BlockProgressBar(ProgressBar):
    def __init__(
        self, *, warning_fraction: float, warning_style: StyleType, **kwargs
    ) -> None:
        super().__init__(**kwargs)
        # ProgressBar.compose builds its Bar from this.
        self.BAR_RENDERABLE = partial(
            BlockBar, warning_fraction=warning_fraction, warning_style=warning_style
        )


class TestRow(NamedTuple):
    check: str
    expected: str
    result: TestResult


class TestsSection(VerticalGroup):
    def __init__(
        self,
        title: str,
        description: str,
        rows: list[TestRow],
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
                        warning_fraction=self._count(TestResult.WARN) / len(self._rows)
                        if self._rows
                        else 0,
                        warning_style=self.app.theme_variables["warning"],
                    )
                    yield DataTable(classes="armature-checks")
                with VerticalGroup():
                    yield Static(content="Recommended Fixes", classes="column-heading")
                    with VerticalScroll(classes="fixes-panel"):
                        for fix in self._generate_fixes_content():
                            yield Static(fix)

    def on_mount(self) -> None:
        self.query_one(BlockProgressBar).update(
            progress=len(self._rows) - self._count(TestResult.FAIL)
        )
        table = self.query_one(DataTable)
        table.add_columns("Test", "Condition", "Result")
        table.add_rows(self._generate_rows_content())

    def _count(self, result: TestResult) -> int:
        return sum(row.result is result for row in self._rows)

    def _generate_rows_content(self):
        rows_content = []
        for row in self._rows:
            rows_content.append(self._row(row.check, row.expected, row.result))
        return rows_content

    def _row(self, check: str, expected: str, result: TestResult) -> tuple[Text, ...]:
        label, color = result.value
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
