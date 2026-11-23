from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Header, Static

from model_meta.tui.bindings import MOVE
from model_meta.tui.widgets.app_footer import AppFooter


class Layout(Screen):
    """The root layout for all screens in this application.

    Subclasses of this class must implement the compose_body() method, otherwise
    they will end up with an empty body instead of an error. Styles for this Screen
    are defined in the root app.tcss file.
    """

    BINDINGS = [
        Binding("escape", "back", "Back"),
        *MOVE,
        Binding("tab", "app.focus_next", "Next"),
    ]

    # Optional description; when empty, does not render a Static Widget. Use this to
    # explain the purpose of a root page. Leave it empty for pages with multiple interaction
    # areas and instead use nested descriptions in those locations.
    description = ""

    def __init__(self, page_title: str) -> None:
        super().__init__()
        self.page_title = page_title

    def compose(self) -> ComposeResult:
        self.title = f"{self.app.title} - {self.page_title}"
        yield Header()
        # can_focus=False keeps the body out of the MOVE focus chain.
        with VerticalScroll(id="body", classes=("body"), can_focus=False):
            if len(self.description) > 0:
                yield Static(content=self.description, classes=("description"))
            # Anything yielded inside the with block becomes a child of this container
            # without the subclass knowing about it.
            yield from self.compose_body()
        yield AppFooter()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        # Index 0 is Textual's default screen; popping onto it leaves a blank app.
        if action == "back":
            return self.app.screen_stack.index(self) > 1
        return True

    def action_back(self) -> None:
        self.app.pop_screen()

    # A subclass that doesn't override compose_body() gets an empty body instead of an error.
    def compose_body() -> ComposeResult:
        return
        # return followed by yield default is a Python trick. Because the word yield appears
        # in the body, Python treats the function as a generator. The return runs first, so
        # the generator ends immediately.
        yield
