"""One root field's check results for a model, laid out as the results file nests them."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.signal import Signal
from textual.widgets import Footer, Header, Static

from model_meta.core.results import Results
from model_meta.specs.modifiers import format_list
from model_meta.tui.status import icon, is_check, status_of
from model_meta.tui.widgets.fix_panel import FixPanel

_NO_RESULTS = "No results yet."

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
}

Line = tuple[int, str]


class CheckDetailScreen(Screen):
    """Pushed as an instance, per model and field. `updates` publishes each new
    `Results` (`None` when the file can't be read)."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(
        self,
        model: Path,
        field: str,
        heading: str,
        results: Results | None,
        updates: Signal[Results | None],
    ) -> None:
        super().__init__()
        self.model = model
        self.field = field
        self.heading = heading
        self._results = results
        self._updates = updates

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            f"Models - {self.model.stem} - {self.heading}",
            id="check-title",
            classes="section-title",
            markup=False,
        )
        yield VerticalScroll(id="check-lines")
        yield FixPanel(id="fix-panel")
        yield Footer()

    async def on_mount(self) -> None:
        self._updates.subscribe(self, self._show)
        await self._show(self._results)

    async def _show(self, results: Results | None) -> None:
        self._results = results
        value = None if results is None else results.to_dict().get(self.field)
        try:
            lines = self.query_one("#check-lines", VerticalScroll)
            panel = self.query_one("#fix-panel", FixPanel)
        except NoMatches:
            return
        await lines.remove_children()
        if value is None:
            await lines.mount(Static(_NO_RESULTS, classes="config-detail"))
        else:
            await lines.mount_all(
                Static(text, classes=f"check-line check-depth-{depth}", markup=False)
                for depth, text in _root_lines(self.field, value)
            )
        failing = dict.fromkeys(_failing(self.field, value))
        panel.steps = tuple(_FIX_STEPS[key] for key in failing if key in _FIX_STEPS)


def _root_lines(field: str, value: object) -> list[Line]:
    # The title already names the field, so a container's children start the page.
    if isinstance(value, dict) and not is_check(value):
        return [line for key, child in value.items() for line in _lines(key, child, 0)]
    return _lines(field, value, 0)


def _lines(key: str, value: object, depth: int) -> list[Line]:
    if isinstance(value, bool | dict):
        lines = [(depth, f"{icon(status_of(value))} {key}")]
        if is_check(value):
            lines += _failure_lines(value["failures"], depth + 1)
        elif isinstance(value, dict):
            for child_key, child in value.items():
                lines += _lines(child_key, child, depth + 1)
        return lines
    if isinstance(value, list):
        return [(depth, f"{key}: {format_list([str(item) for item in value])}")]
    return [(depth, f"{key}: {value}")]


def _failure_lines(failures: list[dict], depth: int) -> list[Line]:
    """Each failure's facts as `key: value` lines, the first marked `- ` like YAML."""
    lines = []
    for failure in failures:
        for index, (key, value) in enumerate(failure.items()):
            bullet = "- " if index == 0 else "  "
            lines += [(d, f"{bullet}{text}") for d, text in _lines(key, value, depth)]
    return lines


def _failing(key: str, value: object) -> list[str]:
    """The keys of every failing check under `value`, in file order."""
    if status_of(value) is not False:
        return []
    if isinstance(value, bool) or is_check(value):
        return [key]
    return [found for child, item in value.items() for found in _failing(child, item)]
