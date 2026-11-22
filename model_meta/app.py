"""Root Model Meta application and its entry point."""

import argparse
import asyncio
import sys
from dataclasses import replace
from pathlib import Path

from textual import work
from textual.app import App
from textual.reactive import reactive

from model_meta import __version__
from model_meta.config import legacy_dir, paths, store
from model_meta.config.settings import Settings
from model_meta.core.blender_connection import BlenderConnection
from model_meta.diagnostics import run_headless_check
from model_meta.tui.screens.dashboard import DashboardScreen
from model_meta.tui.screens.godot_detail import GodotDetailScreen
from model_meta.tui.screens.models import ModelsScreen
from model_meta.tui.screens.setup_wizard import SetupWizard
from model_meta.tui.screens.specs import SpecsScreen
from model_meta.tui.theme import MCNUGGIES
from model_meta.tui.widgets.app_footer import BlenderStatus


def _resource_path(name: str) -> Path:
    """Resolve a bundled data file both when frozen and from a source checkout.

    In a PyInstaller build ``sys.frozen`` is set and ``sys._MEIPASS`` points at
    the extracted bundle root; ``collect_data_files("model_meta")`` ships our
    data under the preserved ``model_meta/`` package prefix, so we join that
    explicitly rather than guessing from the filesystem. From a normal checkout
    the file sits next to this module.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "model_meta" / name  # type: ignore[attr-defined]
    return Path(__file__).parent / name


class ModelMetaApp(App):
    """The Model Meta TUI."""

    # Header text; Textual otherwise falls back to the class name.
    TITLE = "model-meta"
    CSS_PATH = _resource_path("app.tcss")
    BINDINGS = [("q", "quit", "Quit")]
    # The dashboard is the hub; the rest are the per-section detail screens its
    # `SectionCard`s name as their `target`. Pushed by name, never constructed
    # with arguments — screens read app-level state instead.
    SCREENS = {
        "dashboard": DashboardScreen,
        "specs": SpecsScreen,
        "models": ModelsScreen,
        "godot-detail": GodotDetailScreen,
    }

    # The loaded config, surfaced to screens as app-level state (the house
    # convention: screens read app state, they don't touch TOML or the fs). The
    # dashboard watches this and re-renders when it changes; `None` means no valid
    # config (absent/corrupt), which the dashboard renders as a "run setup" prompt.
    # Always *reassign* (never mutate) — `Settings` is frozen, and only a fresh
    # assignment fires the reactive.
    settings: reactive[Settings | None] = reactive(None)
    # `None` until the first probe finishes.
    blender_status: reactive[BlenderStatus | None] = reactive(None)
    BLENDER_POLL_SECONDS = 5.0

    def __init__(
        self, config_path: Path | None = None, force_setup: bool = False
    ) -> None:
        super().__init__()
        self._config_path = config_path or paths.config_file()
        self._force_setup = force_setup

    @property
    def specs_dir(self) -> Path:
        """Where spec files live, surfaced to screens as app-level state.

        Derived from the config *path*, not its contents, so it resolves even
        when the config is absent or corrupt — and the injected `config_path`
        test seam carries over for free.
        """
        return paths.specs_dir(self._config_path)

    @property
    def results_dir(self) -> Path:
        """Where results files live; resolved like `specs_dir`."""
        return paths.results_dir(self._config_path)

    def on_mount(self) -> None:
        self.register_theme(MCNUGGIES)
        self.theme = MCNUGGIES.name
        self._blender_poll = self.set_interval(
            self.BLENDER_POLL_SECONDS, self._check_blender_running
        )
        state, settings = store.load(self._config_path)
        self.settings = settings  # None when absent/corrupt
        self.watch(self, "settings", self._detect_blender)
        if state == store.ABSENT:
            # No config: run first-time setup (cancel exits, no partial config).
            # `--setup` makes no difference here — there is nothing to edit.
            self._first_run()
            return
        # A config exists (valid or corrupt): the dashboard is always reachable.
        self.push_screen("dashboard")
        if state == store.CORRUPT:
            self.notify(
                "Config unreadable — run `model-meta --setup` to redo setup.",
                severity="warning",
                timeout=10,
            )
        if self._force_setup:
            # --setup: open the wizard over the dashboard so a cancel returns
            # somewhere sensible. Edit mode when the config is valid; fresh
            # (but non-overwriting) when it is corrupt.
            self._open_setup()

    @work(exclusive=True, group="setup")
    async def _first_run(self) -> None:
        """Absent config → run the wizard. Save only on completion; a cancel
        (dismiss `None`) writes nothing and exits, so no partial config lingers."""
        settings = await self.push_screen_wait(SetupWizard())
        if settings is None:
            self.exit()
            return
        if self._save(settings):
            self.settings = settings  # reassign (frozen) so the dashboard picks it up
        self.push_screen("dashboard")

    @work(exclusive=True, group="setup")
    async def _open_setup(self) -> None:
        """Re-run setup over the dashboard. Pre-populates from a valid config
        (edit mode); a cancel keeps the prior config untouched."""
        state, settings = store.load(self._config_path)
        existing = settings if state == store.VALID else None
        result = await self.push_screen_wait(SetupWizard(existing=existing))
        if result is not None and self._save(result):
            # Reassign (never mutate — frozen) so the dashboard's reactive fires
            # and it re-renders behind the wizard without a restart.
            self.settings = result
            self.notify("Setup saved.")

    def _save(self, settings: Settings) -> bool:
        """Persist the config, surfacing an OSError as an error notice instead of
        letting it crash the worker and lose the user's just-entered answers.

        Returns whether the write succeeded. `store.save` writes atomically, so a
        failure leaves no partial config behind (and boot re-runs setup)."""
        try:
            store.save(self._config_path, settings)
        except OSError as error:
            self.notify(
                f"Could not save config: {error.strerror or error}",
                severity="error",
                timeout=10,
            )
            return False
        return True

    def _find_blender(self, settings: Settings | None) -> BlenderConnection | None:
        """The configured executable overrides the standard install locations."""
        if settings is not None and settings.blender_executable:
            return settings.blender
        return next(iter(BlenderConnection.candidates()), None)

    @work(exclusive=True, group="blender-detect")
    async def _detect_blender(self, settings: Settings | None) -> None:
        blender = self._find_blender(settings)
        probe = await asyncio.to_thread(blender.probe) if blender else None
        if probe is None or not probe.ok:
            self.blender_status = BlenderStatus(version=None)
            return
        running = await asyncio.to_thread(BlenderConnection.is_running)
        self.blender_status = BlenderStatus(probe.version, running)

    def _check_blender_running(self) -> None:
        status = self.blender_status
        if status is None or status.version is None:
            return
        # Skip, not `exclusive`: cancelling the in-flight check on each tick would
        # starve it whenever `ps` outlasts the interval.
        if any(w.group == "blender-running" and w.is_running for w in self.workers):
            return
        self._update_blender_running(status)

    @work(group="blender-running")
    async def _update_blender_running(self, status: BlenderStatus) -> None:
        running = await asyncio.to_thread(BlenderConnection.is_running)
        if self.blender_status is status:  # a re-probe that landed meanwhile wins
            self.blender_status = replace(status, running=running)

    def on_app_blur(self) -> None:
        self._blender_poll.pause()

    def on_app_focus(self) -> None:
        self._blender_poll.resume()
        self._check_blender_running()


def main(argv: list[str] | None = None) -> None:
    """Console-script / ``python -m model_meta`` entry point.

    Bare invocation launches the TUI (unchanged behavior). ``--version`` and
    ``--check`` are non-interactive utilities the release pipeline relies on;
    ``--setup`` launches straight into the setup wizard to re-run first-time
    setup. ``argv`` is injectable so the CLI is unit-testable without
    ``subprocess``.
    """
    parser = argparse.ArgumentParser(
        prog="model-meta",
        description=(
            "TUI for defining Godot-compatible 3D model specs and validating "
            "an open modeling scene against them."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Boot the app headlessly and exit 0 if it launches (smoke test).",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Launch straight into the setup wizard to re-run first-time setup.",
    )
    args = parser.parse_args(argv)

    if args.check:
        asyncio.run(run_headless_check(ModelMetaApp()))
        return

    legacy_dir.migrate()
    ModelMetaApp(force_setup=args.setup).run()


if __name__ == "__main__":
    main()
