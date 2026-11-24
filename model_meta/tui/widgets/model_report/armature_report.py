from textual.containers import VerticalGroup
from textual.widgets import ProgressBar, Static

from model_meta.core.spec import Armature
from model_meta.tui.widgets.section_description import SectionDescription


class ArmatureReport(VerticalGroup):
    _armature_data: Armature

    def __init__(self, armature: Armature):
        super().__init__()
        self._armature_data = armature

    def compose(self):
        with VerticalGroup():
            SectionDescription(
                label="Armature",
                description="",
            )
            Static(content="% Complete")
            ProgressBar(total=self._get_total_value())

    def _get_number_of_checks(self):
        check_count = 1  # always starts at 1; the "armature existence" check
        check_count += len(self._armature_data.required_bones)
        check_count += len(vars(self._armature_data.parenting).items())
        return check_count

    def _get_number_of_passing_checks(self):
        return 0

    def _get_total_value(self):
        return len(vars(self._armature_data).items())
