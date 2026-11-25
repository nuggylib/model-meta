from textual.containers import VerticalGroup
from textual.content import Content
from textual.widgets import ProgressBar

from model_meta.tui.widgets.model_report.checks_section import ChecksRow, ChecksSection


class MeshRoleReport(VerticalGroup):
    def __init__(self):
        super().__init__()

    def compose(self):
        yield ChecksSection(
            title="Mesh Roles",
            description="Mesh roles health checks",
            total_check_count=self._get_number_of_checks(),
            rows=self._generate_rows(),
            fixes=self._collect_fixes(),
        )

    # TODO: Figure out a good way to have this logic handled in the ChecksSection
    def on_mount(self) -> None:
        self.query_one(ProgressBar).update(
            progress=self._get_number_of_passing_checks()
        )

    def _generate_rows(self) -> list[ChecksRow]:
        rows: list[ChecksRow] = []
        # TODO: Implement row generation logic
        return rows

    def _collect_fixes(self) -> list[str | Content]:
        mesh_role_issues: list[str | Content] = []
        # TODO: Implement fix generation logic
        return mesh_role_issues

    def _get_number_of_checks(self):
        check_count = 1  # always starts at 1; the "armature existence" check
        check_count += len(self._armature_spec.required_bones)
        check_count += len(self._armature_spec.parenting)
        return check_count

    def _get_number_of_passing_checks(self):
        if not self._armature_result.exists:
            return (
                0  # All checks are failing the if the expected armature doesn't exist
            )
        passing_checks = self._get_number_of_checks()
        passing_checks -= len(self._armature_result.missing_bones)
        passing_checks -= len(self._armature_result.missing_parenting_rules)
        return passing_checks
