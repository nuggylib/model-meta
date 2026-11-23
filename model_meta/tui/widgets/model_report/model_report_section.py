from textual.containers import VerticalGroup

from model_meta.tui.widgets.section_description import SectionDescription


class ModelReportSection(VerticalGroup):
    _title: str
    _description: str

    def __init__(self, title: str, description: str):
        super().__init__()
        self._title = title
        self._description = description

    def compose(self):
        with VerticalGroup():
            yield SectionDescription(
                label=self._title,
                description=self._description,
            )
