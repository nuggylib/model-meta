from dataclasses import dataclass

from textual.app import ComposeResult
from textual.widgets import Footer, Static


@dataclass(frozen=True)
class BlenderStatus:
    """`version` is `None` when no working Blender was found. `bridge_version` is `None`
    when the add-on isn't reachable or predates `get_version`."""

    version: str | None
    running: bool = False
    bridge_version: str | None = None


def blender_label(status: BlenderStatus | None) -> str:
    """`None` is a probe that hasn't finished yet."""
    # Not `$text-muted`: it's `auto 60%`, a fade that reads no different here.
    if status is None:
        return "[grey]○ Blender[/]"
    if status.version is None:
        return "[$error]✗[/] Blender"
    if not status.running:
        return f"[grey]●[/] Blender [grey]{status.version}[/]"
    bridge = (
        f"[grey](bridge v{status.bridge_version})[/]"
        if status.bridge_version
        else "[$error](bridge not found)[/]"
    )
    return f"[$success]●[/] Blender [grey]{status.version}[/] {bridge}"


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
        yield BlenderStatusLabel(classes="align-right")
