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

from model_meta.checks import mesh_roles
from model_meta.checks.mesh_roles import Stems, texture_file
from model_meta.core.results import Results, TextureMapOverride
from model_meta.specs.modifiers import format_list
from model_meta.tui.bindings import MOVE
from model_meta.tui.screens.texture_map_override_modal import TextureMapOverrideModal
from model_meta.tui.status import WARNING, icon, is_check, lookup, status_of
from model_meta.tui.widgets.selectable_row import SelectableRow

_NO_RESULTS = "No results yet."
_STATES = {True: "passing", WARNING: "warning", False: "failing"}

Fixes = Callable[[list[dict], Stems], list[str]]


def _once(text: str) -> Fixes:
    return lambda _failures, _stems: [text]


def _texture_fixes(failures: list[dict], stems: Stems) -> list[str]:
    # Named from `missing` and the current overrides, not the stored `expected`, so
    # a new override shows before Blender saves again. An override's meshes share one
    # item, at its first mesh's place.
    items: dict[str, list[str]] = {}
    for failure in failures:
        if not isinstance(mesh := failure.get("mesh"), str):
            continue
        for name in failure.get("missing", []):
            file = texture_file(stems, mesh, name)
            if (mesh, name) in stems:
                items.setdefault(file, []).append(mesh)
            else:
                items[f"Bake a texture map named {file} for {mesh}"] = []
    return [_linked(meshes, key) if meshes else key for key, meshes in items.items()]


def _linked(meshes: list[str], file: str) -> str:
    if len(meshes) == 1:
        return f"Mesh {meshes[0]} needs {file} baked or linked"
    return f"Meshes {format_list(meshes)} need {file} baked or linked"


# Keyed by a check's key in the results file, wherever it sits: its fixes, from its
# failures and the role's overrides.
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
        keys = () if isinstance(value, dict) else self.path[-1:]
        stems = mesh_roles.stems_of(self._overrides(results))
        fixes = list(_fixes(value, keys, stems))
        if fixes:
            await lines.mount(_fix_section(fixes))
        if isinstance(value, dict) and not is_check(value):
            await lines.mount_all(_sections(value, self._overrides(results)))
        else:
            await lines.mount_all(_field_sections((self.path[-1],), value))
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
    `overrides` are listed in the `texture_maps` duplicates section."""
    for key, child in value.items():
        if isinstance(child, dict) and child and not is_check(child):
            yield from _sections(child, keys=(*keys, key))
        elif key == "texture_maps":
            yield from _field_sections((*keys, key), child, overrides)
        else:
            yield from _field_sections((*keys, key), child)


def _field_sections(
    keys: tuple[str, ...],
    value: object,
    overrides: Sequence[TextureMapOverride] = (),
) -> Iterator[Vertical]:
    yield _section(keys, value)
    duplicates = value.get("duplicates", []) if is_check(value) else []
    # Overrides outlive their group (a renamed mesh), so they alone keep the section.
    if not duplicates and not overrides:
        return
    blocks: list[list[Widget]] = []
    if duplicates:
        blocks.append([Static(_DUPLICATES_HELP, classes="config-detail", markup=False)])
        blocks.append(
            [
                SelectableRow(tuple(group), _text(group), classes="check-line")
                for group in duplicates
            ]
        )
    if overrides:
        blocks.append(
            _statics(
                [
                    "texture_map_overrides:",
                    *_fact_lines([override.to_dict() for override in overrides]),
                ]
            )
        )
    yield _box(" > ".join((*keys, "duplicates")), blocks)


def _section(keys: tuple[str, ...], value: object) -> Vertical:
    key = keys[-1]
    if not (isinstance(value, bool) or is_check(value)):
        return _box(" > ".join(keys), [_statics([_text(value)])])
    status = status_of(value)
    failures = value["failures"] if is_check(value) else []
    restated = _RESTATED.get(key, set())
    facts = [
        {k: v for k, v in failure.items() if k not in restated} for failure in failures
    ]
    blocks = [_statics([f"{icon(status)} {_STATES[status]}", *_fact_lines(facts)])]
    blocks += [
        [
            Static(
                f"Warning: {text}", classes="config-detail check-warning", markup=False
            )
        ]
        for fact, text in _WARNINGS.items()
        if any(failure.get(fact) is True for failure in failures)
    ]
    return _box(" > ".join(keys), blocks)


def _box(title: str, blocks: list[list[Widget]], classes: str = "") -> Vertical:
    # Not `:first-child`: Textual can match it stale on constructor children.
    section = Vertical(
        *(
            Vertical(*block, classes="check-block" + (" spaced" if i else ""))
            for i, block in enumerate(blocks)
        ),
        classes=f"check-section {classes}".strip(),
    )
    section.border_title = title
    return section


def _fixes(
    value: object, keys: tuple[str, ...], stems: Stems
) -> Iterator[tuple[str, list[str]]]:
    """Each failing or warning check's label (its section's title) and fixes."""
    if isinstance(value, bool) or is_check(value):
        fixes = _FIXES.get(keys[-1])
        failures = value["failures"] if is_check(value) else []
        if status_of(value) is not True and fixes and (items := fixes(failures, stems)):
            yield " > ".join(keys), items
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _fixes(child, (*keys, key), stems)


def _fix_section(fixes: list[tuple[str, list[str]]]) -> Vertical:
    blocks: list[list[Widget]] = [
        [
            Static(label, classes="check-line fix-label", markup=False),
            *(
                Static(f"{n}. {item}", classes="check-line fix-item", markup=False)
                for n, item in enumerate(items, 1)
            ),
        ]
        for label, items in fixes
    ]
    return _box("Needs Fixes", blocks, "check-fixes")


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
