"""The first-time setup wizard screen.

A 3-step, Back/Next `ContentSwitcher` that captures and validates the anchors the
product hangs off (Blender executable, one or more models directories, Godot
projects root) and returns them as a `Settings` via `dismiss()`, or `None` if the
user cancels.

**Layering:** this screen contains no `subprocess`, no filesystem *walking*, and
no TOML. The slow, blocking work — probing `blender --version` and scanning for
`project.godot` — is delegated to `BlenderConnection` and the `godot` category and
run inside Textual workers (off the event loop) via `asyncio.to_thread`, so the UI
never freezes. Cheap stats (`is_dir`, `mkdir`) and the fast
`BlenderConnection.candidates()` prefill run inline. Persistence (TOML) is the app's job, not the screen's.
"""

import asyncio
import os
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    ContentSwitcher,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
)

from model_meta.config.settings import Settings
from model_meta.core.blender_connection import BlenderConnection
from model_meta.godot import discovery

STEPS = ["step-blender", "step-models", "step-godot"]
_INPUT_FOR_STEP = {0: "#blender-path", 1: "#models-dir", 2: "#godot-root"}


def _normalize(raw: str) -> str:
    """Expand `~`, strip whitespace, and make a path absolute for storage."""
    return os.path.abspath(os.path.expanduser(raw.strip()))


class SetupWizard(Screen[Settings | None]):
    """3-step first-time setup. Returns `Settings` via `dismiss()`, or `None`.

    Pass `existing` to open in *edit mode* (fields pre-populated from the current
    config); leaving it `None` is a fresh first run.

    `escape` cancels. `q` is bound to a no-op purely to shadow the app's global
    quit while the wizard is up: a focused `Input` already swallows a typed `q`
    as text, but a focused `Button` would otherwise let `q` bubble to the app and
    abandon setup — so we absorb it here regardless of what holds focus.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        Binding("q", "noop", show=False),
    ]

    DEFAULT_CSS = """
    SetupWizard {
        align: center middle;
    }
    SetupWizard ContentSwitcher {
        width: 80%;
        max-width: 100;
        height: auto;
    }
    SetupWizard ContentSwitcher > Vertical {
        height: auto;
    }
    SetupWizard Input {
        margin: 1 0;
    }
    SetupWizard Static {
        height: auto;
    }
    SetupWizard #nav {
        width: 80%;
        max-width: 100;
        height: auto;
        align-horizontal: right;
    }
    SetupWizard #nav Button {
        margin: 0 1;
    }
    SetupWizard #models-controls {
        height: auto;
    }
    SetupWizard #models-controls Button {
        margin: 0 1 1 0;
    }
    SetupWizard #models-list {
        height: auto;
        min-height: 3;
        max-height: 10;
        margin: 0 0 1 0;
        border: round $panel;
    }
    /* Wrap long paths instead of clipping them: these are sibling directories,
       so the tail is the part that tells them apart. */
    SetupWizard #models-list ListItem {
        height: auto;
    }
    SetupWizard #models-list Label {
        width: 1fr;
        height: auto;
    }
    /* Keep the Remove target visible even when the list doesn't have focus —
       otherwise Remove deletes a row the user can't see is selected. */
    SetupWizard #models-list > ListItem.--highlight {
        background: $accent 40%;
    }
    SetupWizard #models-list:focus > ListItem.--highlight {
        background: $accent;
    }
    SetupWizard .hidden {
        display: none;
    }
    """

    def __init__(self, existing: Settings | None = None) -> None:
        super().__init__()
        self.existing = existing
        self._index = 0
        self._checking = False
        # Captured values default to the existing config so edit mode round-trips
        # unchanged fields; each is refreshed when its step is advanced past.
        self._blender_exe = existing.blender_executable if existing else ""
        self._blender_version = existing.blender_version if existing else ""
        # Step 2 collects a *list* — order is user-meaningful and preserved.
        self._models_dirs = list(existing.models_directories) if existing else []
        self._godot_root = existing.godot_projects_root if existing else ""

    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial=STEPS[0]):
            with Vertical(id="step-blender"):
                yield Static("Step 1 of 3 — Where is Blender installed?")
                yield Input(
                    value=self._default_blender(),
                    placeholder="/path/to/blender",
                    id="blender-path",
                )
                yield Static("", id="blender-status")
            with Vertical(id="step-models"):
                yield Static(
                    "Step 2 of 3 — Where do your source models live?\n"
                    "Add one or more directories (Enter adds the typed path)."
                )
                # Deliberately blank even in edit mode: the existing locations
                # go in the list below, and prefilling the box would invite
                # adding a duplicate.
                yield Input(placeholder="~/BlenderModels", id="models-dir")
                with Horizontal(id="models-controls"):
                    yield Button("Add", id="add-models", variant="primary")
                    yield Button("Remove", id="remove-models")
                yield ListView(
                    *(ListItem(Label(d)) for d in self._models_dirs),
                    id="models-list",
                )
                yield Static("", id="models-status")
                yield Button(
                    "Create directory",
                    id="create-models",
                    variant="success",
                    classes="hidden",
                )
            with Vertical(id="step-godot"):
                yield Static("Step 3 of 3 — Godot projects root")
                yield Input(
                    value=self.existing.godot_projects_root if self.existing else "",
                    placeholder="~/GodotProjects",
                    id="godot-root",
                )
                yield Static("", id="godot-status")
        with Horizontal(id="nav"):
            yield Button("Back", id="back", disabled=True)
            yield Button("Next", id="next", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#blender-path", Input).focus()

    def _default_blender(self) -> str:
        """Prefill the Blender field: the existing config, else best auto-detect.

        `candidates()` is a fast, stat-based scan (no subprocess, no walk), so
        calling it inline at compose time is safe.
        """
        if self.existing:
            return self.existing.blender_executable
        candidates = BlenderConnection.candidates()
        return str(candidates[0].path) if candidates else ""

    # -- navigation ---------------------------------------------------------

    @on(Button.Pressed, "#back")
    def _on_back(self) -> None:
        if not self._checking and self._index > 0:
            self._goto(self._index - 1)

    @on(Button.Pressed, "#next")
    def _on_next(self) -> None:
        if self._checking:
            return
        if self._index == 0:
            self._advance_blender()
        elif self._index == 1:
            self._advance_models()
        else:
            self._finish()

    def action_cancel(self) -> None:
        """Escape → cancel. On first run this exits; in edit mode it keeps the
        prior config (the app decides — the screen just returns `None`)."""
        self.dismiss(None)

    def action_noop(self) -> None:
        """Absorb `q` so the app's global quit can't fire and abandon setup."""

    def _goto(self, index: int) -> None:
        self._index = index
        self.query_one(ContentSwitcher).current = STEPS[index]
        self.query_one("#back", Button).disabled = index == 0
        last = index == len(STEPS) - 1
        self.query_one("#next", Button).label = "Finish" if last else "Next"
        self.query_one(_INPUT_FOR_STEP[index], Input).focus()
        if index == 2:
            self._maybe_scan()

    # -- step 1: Blender executable ----------------------------------------

    def _advance_blender(self) -> None:
        exe = _normalize(self.query_one("#blender-path", Input).value)
        if not self.query_one("#blender-path", Input).value.strip():
            self._status("blender-status", "Enter the path to your Blender executable.")
            return
        self._set_checking(True)
        self._status("blender-status", "Checking Blender…")
        self._probe(exe)

    @work(exclusive=True, group="probe")
    async def _probe(self, exe: str) -> None:
        # to_thread keeps the blocking subprocess off the event loop; we're back
        # on the loop after the await, so touching widgets here is safe.
        result = await asyncio.to_thread(BlenderConnection(Path(exe)).probe)
        self._set_checking(False)
        if result.ok:
            self._blender_exe = exe
            self._blender_version = result.version
            self._status("blender-status", f"Blender {result.version} ✓")
            self._goto(1)
        else:
            self._status("blender-status", result.message)

    # -- step 2: models directories ----------------------------------------

    def _advance_models(self) -> None:
        """Next out of step 2. Gated on the *list*, never on the input box.

        Text typed but never Added blocks with a hint rather than being silently
        dropped or silently auto-added — either would lose or invent a location
        the user never confirmed.
        """
        if self.query_one("#models-dir", Input).value.strip():
            self._status(
                "models-status", "Press Add to include that path, or clear the box."
            )
            return
        if not self._models_dirs:
            self._status("models-status", "Add at least one models directory.")
            return
        self._goto(2)

    @on(Input.Submitted, "#models-dir")
    def _on_models_submitted(self) -> None:
        """Enter in the models box **adds**; it does not advance the wizard.

        The opposite call from `NewSpecModal`, where Enter creates: there the
        field *is* the whole form, here it feeds a list the user is still
        building.
        """
        self._add_models()

    @on(Button.Pressed, "#add-models")
    def _on_add_models(self) -> None:
        self._add_models()

    def _add_models(self) -> None:
        """Validate the typed path and add it to the list.

        Same per-path rules the single-directory flow used: normalize, accept a
        directory, reject a file, and offer to create a missing one. The guards
        reject *this* Add without touching the already-added list.
        """
        raw = self.query_one("#models-dir", Input).value
        create_button = self.query_one("#create-models", Button)
        if not raw.strip():
            create_button.add_class("hidden")
            self._status("models-status", "Enter the directory where your models live.")
            return
        path = Path(_normalize(raw))
        if path.is_dir():
            self._accept_models_dir(str(path))
        elif path.exists():
            create_button.add_class("hidden")
            self._status("models-status", "That path is a file, not a directory.")
        else:
            # Scoped to the path in the box right now — pressing Create reads the
            # box again, so it can never create some other pending entry.
            create_button.remove_class("hidden")
            self._status(
                "models-status", "That directory doesn't exist yet — create it?"
            )

    def _accept_models_dir(self, directory: str) -> None:
        """Append a validated directory, clear the box, and report what happened.

        Normalization already collapses `~/models`, `~/models/` and the absolute
        form to one string, so a membership test is a sufficient dedup.
        """
        self.query_one("#create-models", Button).add_class("hidden")
        self.query_one("#models-dir", Input).value = ""
        if directory in self._models_dirs:
            self._status("models-status", f"Already added: {directory}")
            return
        self._models_dirs.append(directory)
        self.query_one("#models-list", ListView).append(ListItem(Label(directory)))
        self._status("models-status", f"Added {directory}")

    @on(Button.Pressed, "#remove-models")
    async def _remove_models(self) -> None:
        """Remove the highlighted entry, then keep the highlight somewhere sane.

        Awaits the removal so the index is only reassigned once the item is
        actually gone; after removing the last row the highlight clears and the
        step returns to its empty-gated state.
        """
        listing = self.query_one("#models-list", ListView)
        index = listing.index
        if index is None or not self._models_dirs:
            self._status("models-status", "Select a directory to remove.")
            return
        removed = self._models_dirs.pop(index)
        await listing.pop(index)
        if self._models_dirs:
            # Highlight the entry that slid into this slot, or the new last one.
            listing.index = min(index, len(self._models_dirs) - 1)
            self._status("models-status", f"Removed {removed}")
        else:
            listing.index = None
            self._status("models-status", "Add at least one models directory.")

    @on(Button.Pressed, "#create-models")
    def _create_models(self) -> None:
        path = Path(_normalize(self.query_one("#models-dir", Input).value))
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self._status(
                "models-status",
                f"Could not create directory: {error.strerror or error}",
            )
            return
        self._accept_models_dir(str(path))

    # -- step 3: Godot projects root ---------------------------------------

    @on(Input.Submitted, "#godot-root")
    def _on_godot_submitted(self) -> None:
        self._maybe_scan()

    def _maybe_scan(self) -> None:
        raw = self.query_one("#godot-root", Input).value
        if not raw.strip():
            return
        root = Path(_normalize(raw))
        if not root.is_dir():
            self._status("godot-status", "That directory doesn't exist.")
            return
        self._scan(root)

    @work(exclusive=True, group="scan")
    async def _scan(self, root: Path) -> None:
        self._status("godot-status", "Scanning for Godot projects…")
        projects = await asyncio.to_thread(discovery.find_projects, root)
        if projects:
            listing = "\n".join(f"  • {project}" for project in projects)
            self._status(
                "godot-status", f"Found {len(projects)} project(s):\n{listing}"
            )
        else:
            self._status(
                "godot-status",
                "No Godot projects found under this root (you can still finish).",
            )

    def _finish(self) -> None:
        raw = self.query_one("#godot-root", Input).value
        if not raw.strip():
            self._status("godot-status", "Enter your Godot projects root directory.")
            return
        root = Path(_normalize(raw))
        if not root.is_dir():
            self._status("godot-status", "That directory doesn't exist.")
            return
        self._godot_root = str(root)
        self.dismiss(self._collect())

    # -- helpers -----------------------------------------------------------

    def _collect(self) -> Settings:
        return Settings(
            blender_executable=self._blender_exe,
            blender_version=self._blender_version,
            models_directories=tuple(self._models_dirs),
            godot_projects_root=self._godot_root,
        )

    def _set_checking(self, checking: bool) -> None:
        """Gate the nav buttons while a worker (probe/scan) is in flight."""
        self._checking = checking
        self.query_one("#next", Button).disabled = checking
        self.query_one("#back", Button).disabled = checking or self._index == 0

    def _status(self, widget_id: str, text: str) -> None:
        self.query_one(f"#{widget_id}", Static).update(text)
