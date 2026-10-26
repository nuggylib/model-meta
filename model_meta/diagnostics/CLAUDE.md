# model_meta/diagnostics/

Build/launch diagnostics: self-tests that verify a **packaged** Model Meta
actually launches. These are release-pipeline concerns, deliberately kept out of
`app.py` so the application module carries no CI/packaging machinery.

## Files
- `smoke.py` — `run_headless_check(app)`, the headless launch gate. Mounts the
  app it is given through Textual's pilot (forcing `app.tcss` to parse and the import graph to
  resolve) and raises on failure. Owns its own `_CHECK_TIMEOUT_SECONDS`.
- `__init__.py` — re-exports `run_headless_check`.

## Conventions
- `app.py`'s `main()` dispatches `model-meta --check` here, passing a fresh
  `ModelMetaApp()`. Nothing in this package imports `model_meta.app`: taking
  the app as an argument is what keeps the import one-way, with no cycle.
- Knobs that belong to a check (timeouts, sizes) live with the check, not on
  `ModelMetaApp`.
- Anything here must be awaitable directly from tests under
  `asyncio_mode = "auto"` — don't wrap coroutines in `asyncio.run()` at module
  or function boundaries the tests call into.
