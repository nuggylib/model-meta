from textual.containers import VerticalGroup
from textual.content import Content

from model_meta.core.results import ArmatureResult
from model_meta.core.spec import ArmatureSpec
from model_meta.specs import parenting
from model_meta.tui.widgets.model_report.tests_section import (
    TestResult,
    TestRow,
    TestsSection,
)


class ArmatureReport(VerticalGroup):
    def __init__(self, armature_spec: ArmatureSpec, armature_result: ArmatureResult):
        super().__init__()
        self._armature_spec = armature_spec
        self._armature_result = armature_result

    def compose(self):
        yield TestsSection(
            title="Armature",
            description="Armature health checks.",
            rows=self._generate_rows(),
            fixes=self._collect_fixes(),
        )

    def _generate_rows(self) -> list[TestRow]:
        armature_rows: list[TestRow] = []
        bone_existence_rows: list[TestRow] = []
        expected_children_rows: list[TestRow] = []
        expected_parents_rows: list[TestRow] = []
        armature_rows.append(
            TestRow(
                self._armature_spec.object_name,
                "exists in blender scene",
                TestResult.of(self._armature_result.exists),
            )
        )
        for bone in self._armature_spec.required_bones:
            bone_existence_rows.append(
                TestRow(
                    bone,
                    "exists in armature",
                    TestResult.of(bone not in self._armature_result.missing_bones),
                )
            )
        for parent_pattern in self._armature_spec.parenting:
            expected_children_rows.append(
                TestRow(
                    parent_pattern,
                    "has expected children",
                    TestResult.of(
                        parent_pattern
                        not in self._armature_result.missing_parenting_rules
                    ),
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
                expected_parents_rows.append(
                    TestRow(
                        child,
                        f"child of {parent_pattern}",
                        TestResult.of(not children.intersection(unparented)),
                    )
                )
        return [
            *armature_rows,
            *bone_existence_rows,
            *expected_children_rows,
            *expected_parents_rows,
        ]

    # Bone names go in as template variables, which are inserted as plain text,
    # because escape() misses uppercase tags like [L].
    def _collect_fixes(self) -> list[str | Content]:
        armature_fixes: list[str | Content] = []
        for missing_bone in self._armature_result.missing_bones:
            armature_fixes.append(
                Content.from_markup(
                    "Add bone [b $primary]$bone[/] to the armature.",
                    bone=missing_bone,
                )
            )
        for (
            parenting_rule,
            unparented_bones,
        ) in self._armature_result.missing_parenting_rules.items():
            for parent, child in self._parent_pairs(parenting_rule, unparented_bones):
                armature_fixes.append(
                    Content.from_markup(
                        "Set [b $primary]$parent[/] as parent for [$primary]$child[/]",
                        parent=parent,
                        child=child,
                    )
                )
        return armature_fixes

    def _parent_pairs(
        self, parenting_rule: str, unparented_bones: list[str]
    ) -> list[tuple[str, str]]:
        """Bones the spec no longer resolves pair with the rule itself, so a stale
        results file still shows every unparented bone."""
        pairs = [
            (parent, child)
            for parent, child in parenting.pairs(
                {parenting_rule: self._armature_spec.parenting.get(parenting_rule, [])},
                self._armature_spec.required_bones,
            )
            if child in unparented_bones
        ]
        resolved = {child for _, child in pairs}
        return pairs + [
            (parenting_rule, bone) for bone in unparented_bones if bone not in resolved
        ]
