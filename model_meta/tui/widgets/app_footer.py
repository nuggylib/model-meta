from dataclasses import dataclass

from textual.app import ComposeResult
from textual.widgets import Footer, Static


@dataclass(frozen=True)
class BlenderStatus:
    """`version` is `None` when no working Blender was found."""

    version: str | None
    running: bool = False


def blender_label(status: BlenderStatus | None) -> str:
    """`None` is a probe that hasn't finished yet."""
    if status is None:
        return "[$text-muted]○ Blender[/]"
    if status.version is None:
        return "[$error]✗[/] Blender"
    dot = "[$success]●[/]" if status.running else "[$text-muted]●[/]"
    return f"{dot} Blender {status.version}"


class BlenderStatusLabel(Static):
    def on_mount(self) -> None:
        self.watch(self.app, "blender_status", self._show)

    def _show(self, status: BlenderStatus | None) -> None:
        self.update(blender_label(status))


class AppFooter(Footer):
    def compose(self) -> ComposeResult:
        # `Footer` recomposes on every bindings change, so the label is rebuilt
        # each time and reads the app's current status on mount.
        yield from super().compose()
        yield BlenderStatusLabel()
