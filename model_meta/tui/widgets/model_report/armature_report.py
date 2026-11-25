from textual.containers import VerticalGroup
from textual.content import Content
from textual.widgets import ProgressBar

from model_meta.core.results import ArmatureResult
from model_meta.core.spec import Armature
from model_meta.specs import parenting
from model_meta.tui.widgets.model_report.checks_section import ChecksRow, ChecksSection


class ArmatureReport(VerticalGroup):
    def __init__(self, armature_spec: Armature, armature_result: ArmatureResult):
        super().__init__()
        self._armature_spec = armature_spec
        self._armature_result = armature_result

    def compose(self):
        yield ChecksSection(
            title="Armature",
            description="Armature health checks",
            total_check_count=self._get_number_of_checks(),
            rows=self._generate_rows(),
            fixes=self._collect_fixes(),
        )

    def on_mount(self) -> None:
        self.query_one(ProgressBar).update(
            progress=self._get_number_of_passing_checks()
        )

    def _generate_rows(self) -> list[ChecksRow]:
        rows: list[ChecksRow] = []
        rows.append(
            ChecksRow(
                "armature",
                self._armature_spec.object_name,
                self._armature_result.exists,
            )
        )
        for bone in self._armature_spec.required_bones:
            rows.append(
                ChecksRow(
                    bone,
                    "exists in armature",
                    bone not in self._armature_result.missing_bones,
                )
            )
        for parent_pattern in self._armature_spec.parenting:
            rows.append(
                ChecksRow(
                    parent_pattern,
                    "has expected children",
                    parent_pattern not in self._armature_result.missing_parenting_rules,
                )
            )
            unparented = self._armature_result.missing_parenting_rules.get(
                parent_pattern, []
            )
            for child in self._armature_spec.parenting[parent_pattern]:
                children = {
                    bone
                    for _, bone in parenting.pairs(
                        {parent_pattern: [child]}, self._armature_spec.required_bones
                    )
                }
                rows.append(
                    ChecksRow(
                        child,
                        f"child of {parent_pattern}",
                        not children.intersection(unparented),
                    )
                )
        return rows

    # Bone names go in as template variables, which are inserted as plain text,
    # because escape() misses uppercase tags like [L].
    def _collect_fixes(self) -> list[str | Content]:
        armature_issues: list[str | Content] = []
        for missing_bone in self._armature_result.missing_bones:
            armature_issues.append(
                Content.from_markup(
                    "Add bone [b $primary]$bone[/] to the armature.",
                    bone=missing_bone,
                )
            )
        for (
            parenting_rule,
            unparented_bones,
        ) in self._armature_result.missing_parenting_rules.items():
            bones = Content(", ").join(
                Content.from_markup("[$primary]$bone[/]", bone=bone)
                for bone in unparented_bones
            )
            armature_issues.append(
                Content.assemble(
                    Content.from_markup(
                        "Set [b $primary]$bone[/] as the parent bone for: ",
                        bone=parenting_rule,
                    ),
                    bones,
                )
            )
        return armature_issues

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
