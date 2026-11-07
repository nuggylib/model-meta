"""A model's check results at one key path, laid out as the results file nests them."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.signal import Signal
from textual.widget import Widget
from textual.widgets import Footer, Header, Static

from model_meta.core.results import Results
from model_meta.specs.modifiers import format_list
from model_meta.tui.bindings import MOVE
from model_meta.tui.status import icon, is_check, lookup, status_of
from model_meta.tui.widgets.selectable_row import SelectableRow

_NO_RESULTS = "No results yet."
_PASSING = "passing"
_FAILING = "failing"

# Keyed by a check's key in the results file, wherever it sits.
_FIX_STEPS = {
    "armature": "Name the armature object in Blender as the spec's `object_name`.",
    "count": "Rename the role's meshes so exactly `count` of them fully match its "
    "`mesh_regex`.",
    "vtx_grp": "Add a vertex group matching the role's `vtx_grp` to each listed mesh.",
    "weight": "In Weight Paint mode, assign every vertex of each listed mesh to its "
    "group at the role's `weight`.",
    "texture_maps": "Bake each missing map, save it as `<mesh>_<map>.png`, and load it "
    "in an Image Texture node of the mesh's material. If `may_need_unwrap` is `True`, "
    "check the mesh's UVs before baking; it may still hold a primitive's default "
    "layout.",
    "material_slots": "Add a material slot for each missing name to the listed mesh.",
}


class CheckDetailScreen(Screen):
    """Pushed as an instance, per model and key path. `headings` title each key in
    `path`. `updates` publishes each new `Results` (`None` when the file can't be
    read)."""

    BINDINGS = [("escape", "app.pop_screen", "Back"), *MOVE]

    def __init__(
        self,
        model: Path,
        path: tuple[str, ...],
        headings: tuple[str, ...],
        results: Results | None,
        updates: Signal[Results | None],
    ) -> None:
        super().__init__()
        self.model = model
        self.path = path
        self.headings = headings
        self._results = results
        self._updates = updates
        self._rows: list[str] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            " - ".join(("Models", self.model.stem, *self.headings)),
            id="check-title",
            classes="section-title",
            markup=False,
        )
        yield VerticalScroll(id="check-lines")
        yield Footer()

    async def on_mount(self) -> None:
        self._updates.subscribe(self, self._show)
        await self._show(self._results)

    def on_selectable_row_selected(self, message: SelectableRow.Selected) -> None:
        key = message.row.key
        self.app.push_screen(
            CheckDetailScreen(
                self.model,
                (*self.path, key),
                (*self.headings, key),
                self._results,
                self._updates,
            )
        )

    async def _show(self, results: Results | None) -> None:
        self._results = results
        value = None if results is None else lookup(results.to_dict(), self.path)
        try:
            lines = self.query_one("#check-lines", VerticalScroll)
        except NoMatches:
            return
        if _is_listing(value):
            await self._show_rows(lines, value)
            return
        self._rows = None
        lines.can_focus = True
        await lines.remove_children()
        if value is None or value == {}:
            await lines.mount(Static(_NO_RESULTS, classes="config-detail"))
        elif isinstance(value, dict) and not is_check(value):
            await lines.mount_all(_section(key, child) for key, child in value.items())
        else:
            await lines.mount(_section(self.path[-1], value))

    async def _show_rows(self, lines: VerticalScroll, value: dict) -> None:
        labels = {
            key: f"{icon(status_of(child))} {key}" for key, child in value.items()
        }
        if self._rows == list(labels):
            for row in lines.query(SelectableRow):
                row.label = labels[row.key]
            return
        self._rows = list(labels)
        # The rows are the focus stops; focusing one scrolls it into view.
        lines.can_focus = False
        await lines.remove_children()
        rows = [SelectableRow(key, label) for key, label in labels.items()]
        await lines.mount_all(rows)
        rows[0].focus()


def _is_listing(value: object) -> bool:
    """A container of containers, like `mesh_roles`: one row opens each."""
    return (
        isinstance(value, dict)
        and bool(value)
        and not is_check(value)
        and all(isinstance(v, dict) and not is_check(v) for v in value.values())
    )


def _section(key: str, value: object) -> Vertical:
    if isinstance(value, bool) or is_check(value):
        passed = status_of(value)
        lines = [f"{icon(passed)} {_PASSING if passed else _FAILING}"]
        if is_check(value):
            lines += _failure_lines(value["failures"])
        children: list[Widget] = _statics(lines)
        if not passed and key in _FIX_STEPS:
            children.append(
                Static(
                    f"How to fix: {_FIX_STEPS[key]}",
                    classes="config-detail check-fix",
                    markup=False,
                )
            )
    else:
        children = _statics([_text(value)])
    section = Vertical(*children, classes="check-section")
    section.border_title = key
    return section


def _statics(lines: list[str]) -> list[Widget]:
    return [Static(text, classes="check-line", markup=False) for text in lines]


def _failure_lines(failures: list[dict]) -> list[str]:
    """Each failure's facts as `key: value` lines, the first marked `- ` like YAML."""
    return [
        f"{'- ' if index == 0 else '  '}{key}: {_text(value)}"
        for failure in failures
        for index, (key, value) in enumerate(failure.items())
    ]


def _text(value: object) -> str:
    if isinstance(value, list):
        return format_list([str(item) for item in value])
    return str(value)
