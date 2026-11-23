from textual.containers import VerticalGroup
from textual.widgets import ProgressBar, Static

from model_meta.tui.widgets.model_report.model_report_section import ModelReportSection


class ArmatureReport(VerticalGroup):
    _spec: str
    _model: str

    def __init__():
        super().__init__()

    def compose(self):
        with VerticalGroup():
            ModelReportSection(
                title="Armature",
                description="The armature(s) that this model requires in order for its animations to be fully functional once"
                " exported to Godot. This check ensures your model has the expected armature.",
            )
            Static(content="% Complete")
            ProgressBar()

    def _get_total_value():
        """Get the value for the total to use in the progress bar"""
        # TODO: Load in the spec file for the
        return 0
