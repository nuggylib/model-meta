"""A model's check results at one key path, laid out as the results file nests them."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Protocol

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.signal import Signal
from textual.widget import Widget
from textual.widgets import Footer, Header, Static

from model_meta.core.results import Results, TextureMapOverride
from model_meta.specs.modifiers import format_list
from model_meta.tui.bindings import MOVE
from model_meta.tui.screens.texture_map_override_modal import TextureMapOverrideModal
from model_meta.tui.status import WARNING, icon, is_check, lookup, status_of
from model_meta.tui.widgets.selectable_row import SelectableRow

_NO_RESULTS = "No results yet."
_STATES = {True: "passing", WARNING: "warning", False: "failing"}

Fixes = Callable[[list[dict]], list[str]]


def _once(text: str) -> Fixes:
    return lambda _failures: [text]


def _texture_fixes(failures: list[dict]) -> list[str]:
    return [
        f"Bake a texture map named {file} for {failure['mesh']}"
        for failure in failures
        for file in failure.get("expected", [])
    ]


# Keyed by a check's key in the results file, wherever it sits: its fixes, from its
# failures.
_FIXES: dict[str, Fixes] = {
    "armature": _once(
        "Name the armature object in Blender as the spec's `object_name`."
    ),
    "count": _once(
        "Rename the role's meshes so exactly `count` of them fully match its "
        "`mesh_regex`."
    ),
    "vtx_grp": _once(
        "Add a vertex group matching the role's `vtx_grp` to each listed mesh."
    ),
    "weight": _once(
        "In Weight Paint mode, assign every vertex of each listed mesh to its group "
        "at the role's `weight`."
    ),
    "texture_maps": _texture_fixes,
    "material_slots": _once(
        "Add a material slot for each missing name to the listed mesh."
    ),
    "skinned_meshes": _once(
        "Add each missing modifier to the listed mesh in its Modifier Properties."
    ),
    "warn": _once(
        "Confirm each listed modifier belongs on the mesh, or apply or remove it "
        "before export."
    ),
    "fail": _once("Apply or remove each listed modifier from the mesh before export."),
}

# Failure facts a check's fixes restate, so its section doesn't list them again.
_RESTATED = {"texture_maps": {"expected"}}

# Keyed by a failure's fact; shown once when any failure has it set to `True`.
_WARNINGS = {
    "has_default_uv_map": "A mesh with `has_default_uv_map: True` may not be "
    "unwrapped yet: its UVs match a primitive's default layout. Check them before "
    "baking.",
}

_DUPLICATES_HELP = (
    "The meshes in each `duplicates` group have the same shape, so they can share "
    "texture maps. Select a group to link some of its maps under one name."
)


class ResultsSource(Protocol):
    """The model dashboard: the results it follows, and where overrides are saved."""

    model: Path
    results: Results | None
    results_changed: Signal[Results | None]

    def texture_maps(self, role: str) -> list[str]: ...

    def add_texture_map_override(
        self, role: str, override: TextureMapOverride
    ) -> None: ...


class CheckDetailScreen(Screen):
    """Pushed as an instance, per model and key path. `headings` title each key in
    `path`."""

    BINDINGS = [("escape", "app.pop_screen", "Back"), *MOVE]

    def __init__(
        self, source: ResultsSource, path: tuple[str, ...], headings: tuple[str, ...]
    ) -> None:
        super().__init__()
        self.source = source
        self.path = path
        self.headings = headings
        self._results = source.results
        self._rows: list[str] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            " - ".join(("Models", self.source.model.stem, *self.headings)),
            id="check-title",
            classes="section-title",
            markup=False,
        )
        yield VerticalScroll(id="check-lines")
        yield Footer()

    async def on_mount(self) -> None:
        self.source.results_changed.subscribe(self, self._show)
        await self._show(self._results)

    def on_selectable_row_selected(self, message: SelectableRow.Selected) -> None:
        key = message.row.key
        if isinstance(key, tuple):
            self._link(list(key))
            return
        self.app.push_screen(
            CheckDetailScreen(self.source, (*self.path, key), (*self.headings, key))
        )

    @work(exclusive=True, group="texture-map-override")
    async def _link(self, meshes: list[str]) -> None:
        role = self.path[-1]
        modal = TextureMapOverrideModal(role, meshes, self.source.texture_maps(role))
        override = await self.app.push_screen_wait(modal)
        if override is not None:
            self.source.add_texture_map_override(role, override)

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
        focused = self.focused.key if isinstance(self.focused, SelectableRow) else None
        lines.can_focus = True
        await lines.remove_children()
        if value is None or value == {}:
            await lines.mount(Static(_NO_RESULTS, classes="config-detail"))
            return
        fixes = list(_fixes(value, () if isinstance(value, dict) else self.path[-1:]))
        if fixes:
            await lines.mount(_fix_section(fixes))
        if isinstance(value, dict) and not is_check(value):
            await lines.mount_all(_sections(value, self._overrides(results)))
        else:
            await lines.mount(_section((self.path[-1],), value))
        # A remount drops focus; keep it on the group the user just linked.
        for row in lines.query(SelectableRow):
            if row.key == focused:
                row.focus()

    def _overrides(self, results: Results) -> list[TextureMapOverride]:
        """The overrides of the role at `path`, or none when it isn't a role."""
        match self.path:
            case ("mesh_roles", role):
                return results.texture_map_overrides.get(role, [])
        return []

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


def _sections(
    value: dict,
    overrides: Sequence[TextureMapOverride] = (),
    keys: tuple[str, ...] = (),
) -> Iterator[Vertical]:
    """One section per bool, check or list; a nested container's are titled by path.
    `overrides` are listed in the `texture_maps` section."""
    for key, child in value.items():
        if isinstance(child, dict) and child and not is_check(child):
            yield from _sections(child, keys=(*keys, key))
        elif key == "texture_maps":
            yield _section((*keys, key), child, overrides)
        else:
            yield _section((*keys, key), child)


def _section(
    keys: tuple[str, ...],
    value: object,
    overrides: Sequence[TextureMapOverride] = (),
) -> Vertical:
    key = keys[-1]
    if isinstance(value, bool) or is_check(value):
        status = status_of(value)
        failures = value["failures"] if is_check(value) else []
        restated = _RESTATED.get(key, set())
        facts = [
            {k: v for k, v in failure.items() if k not in restated}
            for failure in failures
        ]
        children: list[Widget] = _statics(
            [f"{icon(status)} {_STATES[status]}", *_fact_lines(facts)]
        )
        duplicates = value.get("duplicates", []) if is_check(value) else []
        if duplicates:
            children += _statics(["duplicates:"])
            children += [
                SelectableRow(tuple(group), _text(group), classes="check-line")
                for group in duplicates
            ]
            children.append(
                Static(_DUPLICATES_HELP, classes="config-detail", markup=False)
            )
        if overrides:
            children += _statics(
                [
                    "texture_map_overrides:",
                    *_fact_lines([override.to_dict() for override in overrides]),
                ]
            )
        children += [
            Static(
                f"Warning: {text}",
                classes="config-detail check-warning",
                markup=False,
            )
            for fact, text in _WARNINGS.items()
            if any(failure.get(fact) is True for failure in failures)
        ]
    else:
        children = _statics([_text(value)])
    section = Vertical(*children, classes="check-section")
    section.border_title = " > ".join(keys)
    return section


def _fixes(value: object, keys: tuple[str, ...]) -> Iterator[tuple[str, list[str]]]:
    """Each failing or warning check's label (its section's title) and fixes."""
    if isinstance(value, bool) or is_check(value):
        fixes = _FIXES.get(keys[-1])
        failures = value["failures"] if is_check(value) else []
        if status_of(value) is not True and fixes and (items := fixes(failures)):
            yield " > ".join(keys), items
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _fixes(child, (*keys, key))


def _fix_section(fixes: list[tuple[str, list[str]]]) -> Vertical:
    children: list[Widget] = []
    for label, items in fixes:
        children.append(Static(label, classes="check-line fix-label", markup=False))
        children += [
            Static(f"{n}. {item}", classes="check-line fix-item", markup=False)
            for n, item in enumerate(items, 1)
        ]
    section = Vertical(*children, classes="check-section check-fixes")
    section.border_title = "Needs Fixes"
    return section


def _statics(lines: list[str]) -> list[Widget]:
    return [Static(text, classes="check-line", markup=False) for text in lines]


def _fact_lines(facts: list[dict]) -> list[str]:
    """Each dict's facts as `key: value` lines, the first marked `- ` like YAML."""
    return [
        f"{'- ' if index == 0 else '  '}{key}: {_text(value)}"
        for fact in facts
        for index, (key, value) in enumerate(fact.items())
    ]


def _text(value: object) -> str:
    if isinstance(value, list):
        return format_list([str(item) for item in value])
    return str(value)
