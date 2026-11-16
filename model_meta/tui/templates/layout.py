from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static


class Layout(Screen):
    """The root layout for all screens in this application.

    Subclasses of this class must implement the compose_body() method, otherwise
    they will end up with an empty body instead of an error.
    """

    description = "PAGE DESCRIPTION"

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="body", classes=("body")):
            yield Static(content=self.description, classes=("description"))
            # Anything yielded inside the with block becomes a child of this container
            # without the subclass knowing about it.
            yield from self.compose_body()
        yield Footer()

    # A subclass that doesn't override compose_body() gets an empty body instead of an error.
    def compose_body() -> ComposeResult:
        return
        # return followed by yield default is a Python trick. Because the word yield appears
        # in the body, Python treats the function as a generator. The return runs first, so
        # the generator ends immediately.
        yield
