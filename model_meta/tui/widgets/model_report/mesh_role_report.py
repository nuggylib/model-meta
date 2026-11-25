from textual.containers import VerticalGroup
from textual.content import Content

from model_meta.core.results import MeshRolesResult
from model_meta.core.spec import MeshRole
from model_meta.tui.widgets.model_report.tests_section import TestRow, TestsSection


class MeshRoleReport(VerticalGroup):
    def __init__(
        self,
        mesh_roles_spec: dict[str, MeshRole],
        mesh_roles_result: MeshRolesResult,
    ):
        super().__init__()
        self._mesh_roles_spec = mesh_roles_spec
        self._mesh_roles_result = mesh_roles_result

    def compose(self):
        yield TestsSection(
            title="Mesh Roles",
            description="Mesh roles health checks",
            rows=self._generate_rows(),
            fixes=self._collect_fixes(),
        )

    def _generate_rows(self) -> list[TestRow]:
        role_rows: list[TestRow] = []
        vtx_grp_rows: list[TestRow] = []
        count_rows: list[TestRow] = []
        weight_rows: list[TestRow] = []
        # TODO: Update the results file to track if all meshes in the group are UV unwrapped (does not need to be in spec - implied need when texture maps exist)
        # uv_unwrap_rows: list[ChecksRow] = []
        texture_map_rows: list[TestRow] = []
        for role in self._mesh_roles_spec:  # remember: role is just the name for the mesh role and is not something in Blender
            result = self._mesh_roles_result[role]
            vtx_grp_rows.append(
                TestRow(
                    f"{role} > vertex group",
                    "vertices assigned",
                    result.vtx_grp.passed,
                )
            )
            count_rows.append(
                TestRow(
                    f"{role} > mesh count",
                    f"expects {self._mesh_roles_spec[role].count | 0} meshes",
                    result.count.passed,
                )
            )

        return [*role_rows, *vtx_grp_rows, *count_rows, *weight_rows, *texture_map_rows]

    def _collect_fixes(self) -> list[str | Content]:
        mesh_role_issues: list[str | Content] = []
        # TODO: Implement fix generation logic
        return mesh_role_issues
