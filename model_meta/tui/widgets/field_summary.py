"""One spec root field at a glance, as a titled box of rows and/or item columns."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Static

COLUMN_LENGTH = 10


class FieldSummary(Vertical):
    """A titled border around `label: value` rows, then `items` in columns.

    A row whose value is `(key, value)` pairs renders as `label:` with each pair
    indented beneath it (`.field-row-child`).

    Assign `rows` and/or `items`; children come from `compose` via `recompose`
    reactives, as in `FixPanel`, so the auto height re-measures. `items` are
    numbered `1). ` (right-aligned) and fill columns of `COLUMN_LENGTH` top to
    bottom, left to right. `empty` shows when both are empty. Text renders
    without markup.
    """

    rows: reactive[tuple[tuple[str, str | tuple[tuple[str, str], ...]], ...]] = (
        reactive((), recompose=True)
    )
    items: reactive[tuple[str, ...]] = reactive((), recompose=True)

    def __init__(self, title: str, empty: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = title
        self._empty = empty

    def compose(self) -> ComposeResult:
        for label, value in self.rows:
            if isinstance(value, str):
                yield Static(f"{label}: {value}", classes="field-row", markup=False)
                continue
            yield Static(f"{label}:", classes="field-row", markup=False)
            for key, child in value:
                yield Static(
                    f"{key}: {child}",
                    classes="field-row field-row-child",
                    markup=False,
                )
        if self.items:
            width = len(str(len(self.items)))
            numbered = [
                f"{n:>{width}}). {item}" for n, item in enumerate(self.items, start=1)
            ]
            with Horizontal(classes="field-columns"):
                for start in range(0, len(numbered), COLUMN_LENGTH):
                    with Vertical(classes="field-column"):
                        for line in numbered[start : start + COLUMN_LENGTH]:
                            yield Static(line, classes="field-item", markup=False)
        elif not self.rows and self._empty:
            yield Static(self._empty, classes="field-empty", markup=False)
