"""Root Model Meta application and its entry point."""

import argparse
import asyncio
import sys
from pathlib import Path

from textual import work
from textual.app import App
from textual.reactive import reactive

from model_meta import __version__
from model_meta.config import legacy_dir, paths, store
from model_meta.config.settings import Settings
from model_meta.diagnostics import run_headless_check
from model_meta.tui.screens.blender_detail import BlenderDetailScreen
from model_meta.tui.screens.dashboard import DashboardScreen
from model_meta.tui.screens.godot_detail import GodotDetailScreen
from model_meta.tui.screens.models import ModelsScreen
from model_meta.tui.screens.setup_wizard import SetupWizard
from model_meta.tui.screens.specs import SpecsScreen


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
    """The Model Meta TUI.

    This is the spine the product hangs off of: future work adds reactive
    validation state driven by a Blender-polling worker, plus category detail
    screens pushed on top of the dashboard.

    Boot routing keys off the config file: a *valid* config goes straight to the
    dashboard, an *absent* one runs the first-time setup wizard, and a *corrupt*
    one boots the dashboard with a non-blocking recovery notice (never
    auto-overwritten). `config_path` is injectable so tests — and the future
    `model-meta setup` entry — can point at a throwaway file instead of the
    real `platformdirs` location.

    `force_setup` (the `--setup` flag) opens the wizard on top of whatever the
    config state routes to, rather than bypassing that routing: with no config
    it *is* the first run (cancel exits), and with a config it edits over the
    dashboard (cancel returns there) — so the same "no valid config + cancel"
    input never strands a config-less dashboard.
    """

    # Header text; Textual otherwise falls back to the class name.
    TITLE = "model-meta"
    CSS_PATH = _resource_path("app.tcss")
    BINDINGS = [("q", "quit", "Quit")]
    # The dashboard is the hub; the rest are the per-section detail screens its
    # `SectionCard`s name as their `target`. Pushed by name, never constructed
    # with arguments — screens read app-level state instead.
    SCREENS = {
        "dashboard": DashboardScreen,
        "blender-detail": BlenderDetailScreen,
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

    def on_mount(self) -> None:
        self.theme = "textual-dark"
        state, settings = store.load(self._config_path)
        self.settings = settings  # None when absent/corrupt
        if state == store.ABSENT:
            # No config: run first-time setup (cancel exits, no partial config).
            # `--setup` makes no difference here — there is nothing to edit.
            self._first_run()
            return
        # A config exists (valid or corrupt): the dashboard is always reachable.
        self.push_screen("dashboard")
        if state == store.CORRUPT:
            self.notify(
                "Config unreadable — press 's' to re-run setup.",
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

    def action_open_setup(self) -> None:
        """Bound to the dashboard's `s` key (`app.open_setup`)."""
        self._open_setup()

    @work(exclusive=True, group="setup")
    async def _open_setup(self) -> None:
        """Re-run setup over the dashboard. Pre-populates from a valid config
        (edit mode); a cancel keeps the prior config untouched.

        `exclusive` (shared with `_first_run`) guards against a fast double
        activation stacking two wizard screens."""
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
