"""A model's check results at one key path, laid out as the results file nests them."""

from __future__ import annotations

from collections.abc import Iterator
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
from model_meta.tui.status import WARNING, icon, is_check, lookup, status_of
from model_meta.tui.widgets.selectable_row import SelectableRow

_NO_RESULTS = "No results yet."
_STATES = {True: "passing", WARNING: "warning", False: "failing"}

# Keyed by a check's key in the results file, wherever it sits.
_FIX_STEPS = {
    "armature": "Name the armature object in Blender as the spec's `object_name`.",
    "count": "Rename the role's meshes so exactly `count` of them fully match its "
    "`mesh_regex`.",
    "vtx_grp": "Add a vertex group matching the role's `vtx_grp` to each listed mesh.",
    "weight": "In Weight Paint mode, assign every vertex of each listed mesh to its "
    "group at the role's `weight`.",
    "texture_maps": "Bake each missing map, save it as `<mesh>_<map>.png`, and load it "
    "in an Image Texture node of the mesh's material.",
    "material_slots": "Add a material slot for each missing name to the listed mesh.",
    "skinned_meshes": "Add each missing modifier to the listed mesh in its Modifier "
    "Properties.",
    "warn": "Confirm each listed modifier belongs on the mesh, or apply or remove it "
    "before export.",
    "fail": "Apply or remove each listed modifier from the mesh before export.",
}

# Keyed by a failure's fact; shown once when any failure has it set to `True`.
_WARNINGS = {
    "has_default_uv_map": "A mesh with `has_default_uv_map: True` may not be "
    "unwrapped yet: its UVs match a primitive's default layout. Check them before "
    "baking.",
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
            await lines.mount_all(_sections(value))
        else:
            await lines.mount(_section((self.path[-1],), value))

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


def _sections(value: dict, keys: tuple[str, ...] = ()) -> Iterator[Vertical]:
    """One section per bool, check or list; a nested container's are titled by path."""
    for key, child in value.items():
        if isinstance(child, dict) and child and not is_check(child):
            yield from _sections(child, (*keys, key))
        else:
            yield _section((*keys, key), child)


def _section(keys: tuple[str, ...], value: object) -> Vertical:
    key = keys[-1]
    if isinstance(value, bool) or is_check(value):
        status = status_of(value)
        lines = [f"{icon(status)} {_STATES[status]}"]
        failures = value["failures"] if is_check(value) else []
        lines += _failure_lines(failures)
        children: list[Widget] = _statics(lines)
        children += [
            Static(
                f"Warning: {text}",
                classes="config-detail check-warning",
                markup=False,
            )
            for fact, text in _WARNINGS.items()
            if any(failure.get(fact) is True for failure in failures)
        ]
        if status is not True and key in _FIX_STEPS:
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
    section.border_title = " > ".join(keys)
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
