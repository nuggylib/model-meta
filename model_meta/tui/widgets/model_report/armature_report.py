from rich.text import Text
from textual.containers import HorizontalGroup, VerticalGroup, VerticalScroll
from textual.content import Content
from textual.renderables.bar import Bar
from textual.widgets import DataTable, ProgressBar, Static

from model_meta.core.results import ArmatureResult
from model_meta.core.spec import Armature
from model_meta.specs import parenting
from model_meta.tui.widgets.section_description import SectionDescription

# Theme variable names, not markup: DataTable renders cells with Rich, which
# can't resolve `$success`.
_RESULTS = {True: ("PASS", "success"), False: ("FAIL", "error")}


class BlockBar(Bar):
    HALF_BAR_LEFT = "▐"
    BAR = "█"
    HALF_BAR_RIGHT = "▌"


class BlockProgressBar(ProgressBar):
    BAR_RENDERABLE = BlockBar


class ArmatureReport(VerticalGroup):
    _armature_spec: Armature
    _armature_result: ArmatureResult

    def __init__(self, armature_spec: Armature, armature_result: ArmatureResult):
        super().__init__()
        self._armature_spec = armature_spec
        self._armature_result = armature_result

    def compose(self):
        with VerticalGroup():
            yield SectionDescription(
                label="Armature",
                description="Armature health checks.",
            )
            with HorizontalGroup(classes="columns"):
                with VerticalGroup():
                    yield BlockProgressBar(
                        total=self._get_number_of_checks(),
                        show_eta=False,
                        classes="section-progress-bar",
                    )
                    yield DataTable(fixed_columns=3, classes="armature-checks")
                with VerticalGroup():
                    yield Static(content="Recommended Fixes", classes="column-heading")
                    with VerticalScroll(classes="fixes-panel"):
                        for fix in self._collect_fixes():
                            yield Static(fix)

    def on_mount(self) -> None:
        self.query_one(ProgressBar).update(
            progress=self._get_number_of_passing_checks()
        )
        table = self.query_one(DataTable)
        table.add_columns("Check", "Expected", "Result")
        table.add_row(
            "Armature",
            self._armature_spec.object_name,
            self._result(self._armature_result.exists),
        )
        required_bone_rows = []
        for bone in self._armature_spec.required_bones:
            required_bone_rows.append(
                (
                    bone,
                    "exists in armature",
                    self._result(bone not in self._armature_result.missing_bones),
                )
            )
        table.add_rows(required_bone_rows)
        parent_pattern_rows = []
        child_pattern_rows = []
        for parent_pattern in self._armature_spec.parenting:
            parent_pattern_rows.append(
                (
                    parent_pattern,
                    "has expected children",
                    self._result(
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
                child_pattern_rows.append(
                    (
                        child,
                        f"child of {parent_pattern}",
                        self._result(not children.intersection(unparented)),
                    )
                )
        table.add_rows(parent_pattern_rows)
        table.add_rows(child_pattern_rows)

    def _result(self, passed: bool) -> Text:
        label, color = _RESULTS[passed]
        return Text(label, style=self.app.theme_variables[color])

    # Bone names go in as template variables, which are inserted as plain text,
    # because escape() misses uppercase tags like [L].
    def _collect_fixes(self) -> list[str | Content]:
        if self._get_number_of_checks() == self._get_number_of_passing_checks():
            return ["All armature checks are passing!"]
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
        width = len(str(len(armature_issues)))
        return [
            Content.assemble(f"{n:>{width}}). ", issue)
            for n, issue in enumerate(armature_issues, start=1)
        ]

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
