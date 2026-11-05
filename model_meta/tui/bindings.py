"""Bindings shared by screens whose focus stops are a list to step through."""

from textual.binding import Binding

# One binding per key: Textual expands a comma-joined pair into one binding each,
# drawing the footer entry twice. Only one is shown.
MOVE = [
    Binding("down", "app.focus_next", "Move", key_display="↑↓"),
    Binding("j", "app.focus_next", "Move", show=False),
    Binding("up", "app.focus_previous", "Move", show=False),
    Binding("k", "app.focus_previous", "Move", show=False),
]
