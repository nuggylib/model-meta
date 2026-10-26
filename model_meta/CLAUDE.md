# model_meta/

The Model Meta application package. Everything under this directory _is_
Model Meta and is packaged together into the published binary (flat layout —
this package sits at the repository root, not under `src/`).

## Files
- `app.py` — `ModelMetaApp` (the Textual `App`) and the `main()` entry point
  used by both the `model-meta` console script and `python -m model_meta`.
  `main(argv=None)` takes injectable args (unit-testable without `subprocess`)
  and exposes `--version`, `--check`, and `--setup` (re-run the setup wizard);
  bare invocation still launches the TUI.
  `_resource_path()` resolves bundled data files (e.g. `app.tcss`) both frozen
  (`sys._MEIPASS`) and from source — `CSS_PATH` uses it so the packaged binary
  finds its stylesheet.
  `ModelMetaApp(config_path=..., force_setup=...)`: `on_mount` routes off the
  config file — **valid** → dashboard, **absent** → first-time setup wizard
  (`_first_run`, saved only on completion), **corrupt** → dashboard + a
  non-blocking recovery notice (never auto-overwritten). `force_setup` (the
  `--setup` flag) layers on top of that routing rather than bypassing it: with
  no config it *is* the first run (`_first_run`, cancel exits), and with a config
  it opens the wizard over the dashboard via `_open_setup` (edit mode when valid;
  a cancel keeps the prior config) — so a cancelled `--setup` never strands a
  config-less dashboard. The dashboard's `s` key also re-opens via `_open_setup`.
  `SCREENS` registers the dashboard (the hub) plus the per-section detail
  screens its cards name as their `target` — `blender-detail`, `specs`,
  `models`, `godot-detail`, in the dashboard's visual order. Everything there
  is pushed **by name** and constructed with no arguments; screens receive data
  by reading app-level state instead.
  Both `_first_run`/`_open_setup` are `@work(exclusive=True, group="setup")`
  (one wizard at a time) and run `push_screen_wait` inside the worker; saves go
  through `_save`, which turns an `OSError` into an error notice instead of
  crashing the worker. `config_path` is the test/injection seam.
  The loaded config is held as app-level state — `settings: reactive[Settings |
  None]` (`None` when absent/corrupt) — rather than discarded at boot. The
  dashboard reads and `watch`es it; after a successful save the app **reassigns**
  `self.settings` (never mutates — `Settings` is frozen) so the reactive fires
  and the dashboard refreshes without a restart.
  `specs_dir` is a read-only property surfacing `paths.specs_dir(config_path)`
  as app-level state. It is derived from the config *path*, not its contents, so
  it resolves even with an absent or corrupt config, and the injected
  `config_path` test seam carries over. Screens read `self.app.specs_dir`, never
  `paths` directly — the same rule that keeps them off `self.app._config_path`.
- `__main__.py` — enables `python -m model_meta`.
- `app.tcss` — application-level Textual stylesheet (loaded via `App.CSS_PATH`).
- `__init__.py` — package marker; holds `__version__`, imported from an optional
  CI-generated `_version.py` with a static `pyproject`-synced fallback.

## Build-time version (`_version.py`)
`__init__.py` imports `__version__` from `model_meta._version` if present,
else falls back to a literal kept in sync with `pyproject.toml` by
`tests/test_version.py`. `_version.py` is **gitignored** — CI writes the fully
resolved canary/dev string there before freezing a binary; it never exists in a
normal checkout. Do not commit or hand-edit it.

## Subpackages (categories)
- `core/` — core app business logic shared across categories: `JsonDocument`,
  the typed, atomically-written JSON document base, and `Spec`, the spec
  document built on it; `AppConnection`, the base for an external app at a path,
  `BlenderConnection` (executable detection and `--version` probe) and
  `GodotConnection` (a bounded scan for `project.godot` under the projects
  root). No Textual, no UI.
- `tui/` — Textual screens (`tui/screens/`) and the reusable widgets they are
  assembled from (`tui/widgets/`).
- `config/` — persistence: the on-disk config first-time setup writes and every
  launch reads (`Settings`, path resolution, atomic load/save). No Textual, no I/O
  beyond the config file.
- `diagnostics/` — build/launch self-tests (`run_headless_check`, the `--check`
  smoke gate). Release-pipeline concerns kept out of `app.py`.
- `models/` — source-model discovery: a bounded scan for `.blend` files under a
  configured models directory (`discovery.find_blend_files`). Locates models
  only; reading their contents belongs to `BlenderConnection`. No Textual, no UI.
- `specs/` — validation specs: the document vocabulary (`schema.py`), the
  model-type name rules (`naming.py`), and the JSON files on disk. The spec
  files themselves are the list of supported model types. No Textual, no UI.

## Conventions
- Group new code by category into subpackages here rather than adding loose
  top-level modules. Create a new category subpackage when none fits, and give
  it its own `CLAUDE.md`.
