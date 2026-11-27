from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalGroup
from textual.reactive import reactive

from model_meta.core.results import Results
from model_meta.core.spec import ArmatureSpec, MeshRolesSpec
from model_meta.tui.widgets.model_report.armature_report import ArmatureReport
from model_meta.tui.widgets.model_report.mesh_role_report import MeshRoleReport


class Reports(VerticalGroup):
    results: reactive[Results | None] = reactive(None, recompose=True)

    def __init__(self, armature_spec: ArmatureSpec, mesh_roles_spec: MeshRolesSpec):
        super().__init__()
        self._armature_spec = armature_spec
        self._mesh_roles_spec = mesh_roles_spec

    def compose(self) -> ComposeResult:
        if self.results is None:
            return
        if self.results.armature is not None:
            yield ArmatureReport(
                armature_spec=self._armature_spec,
                armature_result=self.results.armature,
            )
        if self.results.mesh_roles is not None:
            yield MeshRoleReport(
                mesh_roles_spec=self._mesh_roles_spec,
                mesh_roles_result=self.results.mesh_roles,
            )
