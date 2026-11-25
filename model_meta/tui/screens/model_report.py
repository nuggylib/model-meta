"""The model report — one model checked against the spec it was built from."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import aclosing
from dataclasses import replace
from functools import partial
from pathlib import Path

from rich.markup import escape
from textual import work
from textual.app import ComposeResult
from textual.containers import VerticalGroup
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.signal import Signal
from textual.widgets import Static

from model_meta.checks import armature, mesh_roles, modifiers
from model_meta.core.blender_bridge import (
    Armatures,
    BridgeError,
    MeshReport,
    OpenFile,
    subscribe_armatures,
    subscribe_meshes,
)
from model_meta.core.blender_connection import BlenderConnection
from model_meta.core.results import Results, TextureMapOverride
from model_meta.core.spec import (
    ArmatureSpec,
    MeshRolesSpec,
    ModifiersSpec,
    Spec,
)
from model_meta.tui.screens.check_detail import CheckDetailScreen
from model_meta.tui.status import Status, lookup, most_severe, status_of
from model_meta.tui.templates.layout import Layout
from model_meta.tui.widgets.app_footer import BlenderStatus
from model_meta.tui.widgets.labeled_field import LabeledField
from model_meta.tui.widgets.model_report.armature_report import ArmatureReport
from model_meta.tui.widgets.model_report.mesh_role_report import MeshRoleReport
from model_meta.tui.widgets.selectable_row import SelectableRow

# Each root row's results file key, and the title its detail screen shows.
_ROOTS = {"armature": "Armature", "mesh_roles": "Mesh Roles", "modifiers": "Modifiers"}

# depth, text, and the row's key path in the results file (`None`: never checked).
Row = tuple[int, str, tuple[str, ...] | None]


class ModelReportScreen(Layout):
    """Pushed as an instance, like `SpecDetailScreen`: it is per model and spec."""

    is_refreshing: reactive[bool] = reactive(False)
    blender_running: reactive[bool | None] = reactive(None)
    bridge_connected: reactive[bool] = reactive(False)
    wrong_file: reactive[bool] = reactive(False)
    results: reactive[Results | None] = reactive(None)

    def __init__(self, model: Path, spec_path: Path, results_path: Path) -> None:
        super().__init__(page_title=f"Model Report > {model.name}")
        self.model = model
        self.spec_path = spec_path
        self.results_path = results_path
        self.results_changed: Signal[Results | None] = Signal(self, "results_changed")
        self._armature_spec = ArmatureSpec()
        self._mesh_roles_spec: MeshRolesSpec
        self._modifiers_spec = ModifiersSpec()
        self._rows: list[Row] = []
        # The model's last scene report, re-checked when an override is saved.
        self._report: MeshReport | None = None
        self.description = (
            f"This is your model report for [b $primary]{self.model.name}[/]. Keep this page open while working."
            " It will update each time you save or load a file in Blender."
        )

    def compose_body(self) -> ComposeResult:
        try:
            spec = Spec.load(self.spec_path)
        except (OSError, ValueError):
            spec = None
        self._armature_spec = spec.armature if spec else ArmatureSpec()
        self._mesh_roles_spec = spec.mesh_roles if spec else {}
        self._modifiers_spec = spec.modifiers if spec else ModifiersSpec()
        self._load_results()
        with VerticalGroup(classes="layout-heading-content"):
            yield LabeledField(
                label="Spec",
                val=f"[$primary]{escape(self.spec_path.name)}[/]",
            )
            yield LabeledField(
                label="File Path", val=self._file_path_text(), val_id="file-path"
            )
        yield ArmatureReport(
            armature_spec=self._armature_spec, armature_result=self.results.armature
        )
        yield MeshRoleReport(
            mesh_roles_spec=spec.mesh_roles, mesh_roles_result=self.results.mesh_roles
        )

    def on_mount(self) -> None:
        self._refresh()
        # init=False: the _refresh above already covers the status at mount.
        self.watch(self.app, "blender_status", self._on_blender_status, init=False)

    def _on_blender_status(self, status: BlenderStatus | None) -> None:
        # The worker's own check lands while a closing Blender is still exiting.
        if status and not self.bridge_connected and not self.is_refreshing:
            self.blender_running = status.running
        # Wait for bridge_version, not just running: Blender is up before its add-on listens.
        if (
            status
            and status.running
            and status.bridge_version
            and not self.bridge_connected
        ):
            self._refresh()

    def on_selectable_row_selected(self, message: SelectableRow.Selected) -> None:
        field = message.row.key
        self.app.push_screen(CheckDetailScreen(self, (field,), (_ROOTS[field],)))

    def texture_maps(self, role: str) -> list[str]:
        return self._mesh_roles_spec[role].texture_maps or []

    def add_texture_map_override(self, role: str, override: TextureMapOverride) -> None:
        self._change_overrides(role, lambda overrides: [*overrides, override], "saved")

    def replace_texture_map_override(
        self, role: str, old: TextureMapOverride, new: TextureMapOverride
    ) -> None:
        self._swap_override(role, old, [new], "saved")

    def delete_texture_map_override(
        self, role: str, override: TextureMapOverride
    ) -> None:
        self._swap_override(role, override, [], "deleted")

    def _swap_override(
        self,
        role: str,
        old: TextureMapOverride,
        new: list[TextureMapOverride],
        done: str,
    ) -> None:
        def swap(overrides: list[TextureMapOverride]) -> list[TextureMapOverride]:
            if old not in overrides:
                raise ValueError(f"override '{old.name}' is no longer in it")
            index = overrides.index(old)
            return [*overrides[:index], *new, *overrides[index + 1 :]]

        self._change_overrides(role, swap, done)

    def _change_overrides(
        self,
        role: str,
        change: Callable[[list[TextureMapOverride]], list[TextureMapOverride]],
        done: str,
    ) -> None:
        def apply(results: Results) -> Results:
            current = results.texture_map_overrides
            updated = {**current, role: change(current.get(role, []))}
            return replace(
                results,
                texture_map_overrides={n: o for n, o in updated.items() if o},
            )

        if not self._update(apply):
            return
        if self._report is None:
            self.notify(f"Override {done}. It's checked when Blender next saves.")
            return
        self._check_mesh_roles(self._report)
        self.notify(f"Override {done} and checked.")

    @work(exclusive=True, group="blender-check")
    async def _refresh(self) -> None:
        self.is_refreshing = True
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(
                    self._follow(subscribe_armatures(), self._check_armature)
                )
                group.create_task(
                    self._follow(
                        subscribe_meshes(
                            partial(mesh_roles.plan, self._mesh_roles_spec)
                        ),
                        self._check_mesh_roles,
                    )
                )
        except* BridgeError:
            pass
        self.bridge_connected = False
        self.wrong_file = False
        self.is_refreshing = True
        self.blender_running = await asyncio.to_thread(BlenderConnection.is_running)
        self.is_refreshing = False

    async def _follow(self, messages: AsyncIterator, check: Callable) -> None:
        """Runs `check` on each result that arrives while the model's file is open."""
        on_model = False
        async with aclosing(messages):
            async for message in messages:
                self.bridge_connected = True
                self.blender_running = True
                self.is_refreshing = False
                if isinstance(message, OpenFile):
                    on_model = _is_model(message.path, self.model)
                    self.wrong_file = not on_model
                elif on_model:
                    check(message)

    def _check_armature(self, message: Armatures) -> None:
        # busy (`None`): keep the last result
        if message.armatures is not None:
            self._save(
                armature=armature.evaluate(self._armature_spec, message.armatures)
            )

    def _check_mesh_roles(self, report: MeshReport) -> None:
        self._report = report
        overrides = {} if self.results is None else self.results.texture_map_overrides
        roles = mesh_roles.evaluate(self._mesh_roles_spec, report, overrides)
        # An add-on before 0.4.0: keep the stored modifier results.
        if report.modifiers is None:
            self._save(mesh_roles=roles)
            return
        checked, roles = modifiers.evaluate(
            self._modifiers_spec, roles, report.modifiers
        )
        self._save(mesh_roles=roles, modifiers=checked)

    def watch_results(self) -> None:
        self.results_changed.publish(self.results)

    def _load_results(self) -> None:
        try:
            self.results = Results.load(self.results_path)
        except (OSError, ValueError):
            self.results = None

    def _save(self, **fields: object) -> bool:
        return self._update(lambda results: replace(results, **fields))

    def _update(self, change: Callable[[Results], Results]) -> bool:
        """Applies `change` to the file as it is now. `False` after a failed load or
        save, which it reports."""
        try:
            results = Results.load(self.results_path)
            updated = change(results)
            if updated != results:
                updated.save()
        except (OSError, ValueError) as error:
            self.notify(
                f"Couldn't save {self.results_path.name}: {error}", severity="error"
            )
            return False
        self.results = updated
        return True

    def _display_path(self) -> str:
        for directory in self.app.settings.models_directories:
            root = Path(directory).expanduser()
            if self.model.is_relative_to(root):
                return f".../{self.model.relative_to(root.parent)}"
        return str(self.model)

    def _file_path_text(self) -> str:
        path = f"[$primary]{escape(self._display_path())}[/]"
        if self.bridge_connected and self.wrong_file:
            return f"{path} [$error](Wrong file open)[/]"
        if self.bridge_connected:
            return f"{path} [$success](Connected)[/]"
        if self.blender_running and not self.bridge_connected:
            return f"{path} [$warning](Bridge not found)[/]"
        if self.blender_running is False:
            return f"{path} [$text-muted](Blender inactive)[/]"
        return path

    def watch_bridge_connected(self) -> None:
        self._update_file_path()

    def watch_blender_running(self) -> None:
        self._update_file_path()

    def watch_wrong_file(self) -> None:
        self._update_file_path()

    def _update_file_path(self) -> None:
        try:
            self.query_one("#file-path", Static).update(self._file_path_text())
        except NoMatches:
            pass

    def _get_field_status(self, index: int) -> Status:
        data = None if self.results is None else self.results.to_dict()
        return self._status(index, data)

    def _get_text_for_row(self, index: int) -> str:
        return self._rows[index][1]

    def _status(self, index: int, data: dict | None) -> Status:
        """A row with rows beneath it shows the most severe of theirs."""
        path = self._rows[index][2]
        if data is None or path is None or (value := lookup(data, path)) is None:
            return None
        children = list(self._children(index))
        if children:
            return most_severe(self._status(child, data) for child in children)
        return status_of(value)

    def _children(self, index: int) -> Iterator[int]:
        depth = self._rows[index][0]
        for child in range(index + 1, len(self._rows)):
            if self._rows[child][0] <= depth:
                return
            if self._rows[child][0] == depth + 1:
                yield child


def _is_model(open_file: str | None, model: Path) -> bool:
    if open_file is None:
        return False
    try:
        # samefile, not ==: a symlinked model or a case-insensitive filesystem still matches.
        return Path(open_file).samefile(model)
    except OSError:
        return False
