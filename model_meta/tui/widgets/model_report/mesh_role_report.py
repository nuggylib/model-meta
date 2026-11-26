from textual.containers import VerticalGroup
from textual.content import Content

from model_meta.core.results import MeshRolesResult
from model_meta.core.spec import MeshRole
from model_meta.tui.widgets.model_report.tests_section import (
    TestResult,
    TestRow,
    TestsSection,
)


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
        vtx_grp_rows: list[TestRow] = []
        count_rows: list[TestRow] = []
        weight_rows: list[TestRow] = []
        texture_map_rows: list[TestRow] = []
        uv_unwrap_rows: list[TestRow] = []
        for role in self._mesh_roles_spec:  # remember: role is just the name for the mesh role and is not something in Blender
            result = self._mesh_roles_result.get(role)
            if result is None:
                continue
            if result.vtx_grp is not None:
                vtx_grp_rows.append(
                    TestRow(
                        f"vertex group > {role}",
                        "vertices assigned",
                        TestResult.of(result.vtx_grp.passed),
                    )
                )
            if result.count is not None:
                count_rows.append(
                    TestRow(
                        f"mesh count > {role}",
                        f"expects {self._mesh_roles_spec[role].count} meshes",
                        TestResult.of(result.count.passed),
                    )
                )
            if result.weight is not None:
                weight_rows.append(
                    TestRow(
                        f"weight > {role}",
                        "vertices at correct weight",
                        TestResult.of(result.weight.passed),
                    )
                )
            if result.texture_maps is not None:
                texture_map_rows.append(
                    TestRow(
                        f"maps > {role}",
                        "meshes have all textures",
                        TestResult.of(result.texture_maps.passed),
                    )
                )
            if result.uv_unwrap is not None:
                # A failure without a mesh (an add-on too old for UVs) fails every mesh.
                failed = {f.get("mesh") for f in result.uv_unwrap.failures}
                warned = {w.get("mesh") for w in result.uv_unwrap.warnings}
                for mesh in result.meshes:
                    if failed.intersection({mesh, None}):
                        uv_result = TestResult.FAIL
                    elif mesh in warned:
                        uv_result = TestResult.WARN
                    else:
                        uv_result = TestResult.PASS
                    uv_unwrap_rows.append(
                        TestRow(f"UV > {role} > {mesh}", "has a UV map", uv_result)
                    )

        return [
            *vtx_grp_rows,
            *count_rows,
            *weight_rows,
            *texture_map_rows,
            *uv_unwrap_rows,
        ]

    def _collect_fixes(self) -> list[str | Content]:
        mesh_role_issues: list[str | Content] = []
        # TODO: Implement fix generation logic
        return mesh_role_issues
