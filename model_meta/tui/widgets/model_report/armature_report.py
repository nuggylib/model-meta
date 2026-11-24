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
                title="Armature",
                description="",
            )
            Static(content="% Complete")
            ProgressBar(total=self._get_total_value())

    def _get_total_value(self):
        return len(vars(self._armature_data).items())
