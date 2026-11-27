# tests/

Test suite for Model Meta. Run with `uv run pytest`.

## Conventions
- UI tests drive the app through Textual's headless `App.run_test()` pilot
  harness — never `App.run()` (that needs a real TTY and fails under pytest/CI).
- Tests are `async def`; `asyncio_mode = "auto"` (in `pyproject.toml`) runs them
  without a `@pytest.mark.asyncio` marker.
- `conftest.py` stubs `ModelMetaApp._find_blender` to `None` for every test,
  so booting the app never runs a real Blender. A test that needs a detected
  Blender patches it again; one testing `_find_blender` itself calls
  `monkeypatch.undo()` first.
- `test_app.py` is the boot smoke test (app mounts the dashboard, `q` quits,
  exit code 0). Add feature tests alongside as behavior grows.
