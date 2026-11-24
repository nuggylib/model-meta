from textual.containers import HorizontalGroup, VerticalGroup
from textual.content import Content
from textual.renderables.bar import Bar
from textual.widgets import ProgressBar, Static

from model_meta.core.results import ArmatureResult
from model_meta.core.spec import Armature
from model_meta.tui.widgets.section_description import SectionDescription


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
            yield Static(content="Passing Checks")
            with HorizontalGroup(classes="columns"):
                with VerticalGroup():
                    yield BlockProgressBar(
                        total=self._get_number_of_checks(), show_eta=False
                    )
                with VerticalGroup():
                    for issue in self._collect_fixes():
                        yield Static(content=issue)

    def on_mount(self) -> None:
        self.query_one(ProgressBar).update(
            progress=self._get_number_of_passing_checks()
        )

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
